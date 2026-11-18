import csv
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from core import (Segment, Store, tokens, search_segments, search_store,
                  export_csv, copy_recordings)
from engine import transcribe_batch


class AddressSearchTests(unittest.TestCase):
    def find(self, text, query='Тополиная 5', fuzzy=False):
        return search_segments(1, 'call.mp3', [Segment(0, 10, text)], query, fuzzy)

    def test_address_inflection_and_number(self):
        self.assertTrue(self.find('На Тополиной, дом пять.'))
        self.assertTrue(self.find('Тополиная, д. 5.'))
        self.assertTrue(self.find('Дом пять на Тополиной.'))

    def test_different_house_does_not_match(self):
        for text in ['Тополиная 25', 'Тополиная двадцать пять', 'Тополиная 15',
                     'Тополиная 5а', 'Тополиная 5-А', 'Тополиная 5/1', 'Тополиная 25 квартира 5']:
            with self.subTest(text=text):
                self.assertFalse(self.find(text))

    def test_approximate_is_explicit(self):
        self.assertFalse(self.find('Таполиная пять'))
        result = self.find('Таполиная пять', fuzzy=True)
        self.assertEqual(result[0].kind, 'Похожее написание')
        self.assertFalse(self.find('Таполиная двадцать пять', fuzzy=True))
        self.assertTrue(self.find('Линина восемь', 'Ленина 8', fuzzy=True))

    def test_cross_segment_and_long_gap(self):
        nearby = [Segment(0, 2, 'Тополиная.'), Segment(2.5, 4, 'Дом пять.')]
        self.assertEqual(len(search_segments(1, 'x', nearby, 'Тополиная 5')), 1)
        nearby[1].start, nearby[1].end = 60, 64
        self.assertFalse(search_segments(1, 'x', nearby, 'Тополиная 5'))

    def test_tight_window_and_repeated_hits(self):
        parts = [Segment(0, 2, 'Здравствуйте.'), Segment(2, 5, 'Тополиная пять.'),
                 Segment(5, 7, 'Спасибо.'), Segment(7, 10, 'Тополиная пять.')]
        found = search_segments(1, 'x', parts, 'Тополиная 5')
        self.assertEqual([(m.start, m.end) for m in found], [(2, 5), (7, 10)])

    def test_alternative_phrases_and_unrelated(self):
        self.assertTrue(self.find('Улица Ленина, дом восемь.', 'Тополиная 5; Ленина 8'))
        self.assertFalse(self.find('Ленина пять'))
        self.assertFalse(self.find('Тополиная пять', ' ; '))

    def test_number_composition(self):
        self.assertEqual(tokens('сто двадцать пять'), ['125'])
        self.assertEqual(tokens('дом пятого'), ['5'])
        self.assertEqual(tokens('Тополиная 5а')[-1], '5а')


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'db.sqlite3'
        self.audio = self.root / 'разговор.mp3'
        self.audio.write_bytes(b'test')
        self.store = Store(self.db)
        self.store.add_files([self.audio])
        self.rid = self.store.rows()[0]['id']

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def save(self):
        self.store.save(self.rid, 'small', 10, [Segment(1, 3, 'Тополиная пять.')])

    def test_resume_and_model_change(self):
        self.save()
        self.assertFalse(self.store.pending('small'))
        self.assertEqual(len(self.store.pending('medium')), 1)
        self.assertEqual(len(search_store(self.store, 'Тополиная 5')), 1)

    def test_modified_file_invalidates_cached_words(self):
        self.save()
        self.audio.write_bytes(b'changed recording')
        added, changed, _ = self.store.add_files([self.audio])
        self.assertEqual((added, changed), (0, 1))
        self.assertFalse(search_store(self.store, 'Тополиная 5'))

    def test_copy_deduplicates_and_preserves_existing(self):
        self.save()
        matches = search_store(self.store, 'Тополиная 5')
        out = self.root / 'selected'
        out.mkdir()
        (out / self.audio.name).write_bytes(b'original')
        copied, failures = copy_recordings(matches * 2, out)
        self.assertEqual(len(copied), 1)
        self.assertFalse(failures)
        self.assertEqual((out / self.audio.name).read_bytes(), b'original')
        self.assertEqual(copied[0].read_bytes(), b'test')
        self.assertTrue(self.audio.exists())

    def test_csv_quotes_and_formula_escape(self):
        self.save()
        matches = search_store(self.store, 'Тополиная 5')
        matches[0].text = '=1+1; "quoted"\nnext line'
        path = self.root / 'results.csv'
        export_csv(path, matches)
        with path.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f, delimiter=';'))
        self.assertEqual(rows[0], ['Файл', 'Время в записи', 'Фрагмент разговора', 'Кратко, что обсуждали'])
        self.assertEqual(rows[1][2], "'=1+1; \"quoted\"\nnext line")

    def test_interrupted_state_is_recoverable(self):
        self.store.state(self.rid, 'running')
        self.store.recover()
        self.assertEqual(self.store.row(self.rid)['status'], 'pending')

    def test_worker_failure_continues_next_file(self):
        other = self.root / 'second.mp3'
        other.write_bytes(b'second')
        self.store.add_files([other])
        class FakeModel:
            def transcribe(_, path, **kwargs):
                if Path(path).name == 'second.mp3':
                    raise ValueError('broken audio')
                part = SimpleNamespace(start=0, end=2, text='Тополиная пять', avg_logprob=-0.1, no_speech_prob=0.1)
                return iter([part]), SimpleNamespace(duration=2)
        result = transcribe_batch(self.db, self.root, 'small', threading.Event(), lambda *a: None,
                                  lambda: None, lambda *a: FakeModel())
        self.assertEqual((result['ok'], result['failed']), (1, 1))
        self.assertEqual(len(search_store(self.store, 'Тополиная 5')), 1)

    def test_stop_never_saves_partial_transcript(self):
        cancel = threading.Event()
        class FakeModel:
            def transcribe(_, path, **kwargs):
                def generate():
                    yield SimpleNamespace(start=0, end=2, text='Тополиная пять', avg_logprob=-0.1, no_speech_prob=0.1)
                    cancel.set()
                    yield SimpleNamespace(start=2, end=4, text='конец', avg_logprob=-0.1, no_speech_prob=0.1)
                return generate(), SimpleNamespace(duration=4)
        result = transcribe_batch(self.db, self.root, 'small', cancel, lambda *a: None,
                                  lambda: None, lambda *a: FakeModel())
        self.assertTrue(result['stopped'])
        self.assertEqual(self.store.row(self.rid)['status'], 'pending')
        self.assertFalse(self.store.segments(self.rid))


if __name__ == '__main__':
    unittest.main()
