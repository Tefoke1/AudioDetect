import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from core import Segment, Store, search_store
from semantic import make_units, validate_blocks, analyze_recording, analyze_batch, chunks
from engine import speech_segments
from types import SimpleNamespace

TEXT = [
    'Здравствуйте.',
    'На Тополиной, дом пять, нужны проектные работы.',
    'Там надо подготовить чертежи отопления.',
    'Срок сдачи — пятница. Согласуем с заказчиком.',
    'Теперь другой объект: Тополиная, дом двадцать пять.',
    'Там аварийный ремонт кровли, мастер приедет сегодня.',
    'Вернёмся к Тополиной, дом пять.',
    'Договор по этому объекту отправлю завтра.',
]

def segments():
    return [Segment(i * 5, (i + 1) * 5, t) for i, t in enumerate(TEXT)]

class ReplyClient:
    def complete(self, payload):
        replies = [
            {'first': 1, 'last': 4, 'summary': 'Проектные работы по Тополиной, 5: чертежи отопления к пятнице и согласование с заказчиком.', 'continues': False},
            {'first': 7, 'last': 8, 'summary': 'Договор по Тополиной, 5 отправят завтра.', 'continues': True},
        ]
        lo, hi = payload['реплики'][0]['id'], payload['реплики'][-1]['id']
        return {'blocks': [r for r in replies if lo <= r['first'] <= r['last'] <= hi]}

class DiscussionTests(unittest.TestCase):
    def test_long_continuation_is_carried_across_context_windows(self):
        parts = [Segment(0, 4, 'Тополиная, дом пять. Нужен проект.')]
        parts += [Segment(i * 4, i * 4 + 4, 'Обсуждаем состав чертежей отопления и требования заказчика.') for i in range(1, 12)]
        class ContinuationClient:
            def complete(self, payload):
                rows = payload['реплики']
                return {'blocks': [{'first': rows[0]['id'], 'last': rows[-1]['id'],
                                    'summary': 'Обсуждают проект и требования к чертежам.', 'continues': True}]}
        with patch('semantic.chunks', side_effect=lambda units: chunks(units, limit=250)):
            found = analyze_recording(1, 'x.mp3', parts, 'Тополиная 5', False, ContinuationClient(), threading.Event())
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].end, 48)
        self.assertEqual(found[0].text.count('требования заказчика'), 11)

    def test_asr_sentence_times_come_from_real_word_timestamps(self):
        part = SimpleNamespace(start=0, end=10, text='Дом пять. Нужен проект.', avg_logprob=-0.1, no_speech_prob=0.0,
            words=[SimpleNamespace(start=1.0, end=1.5, word='Дом'), SimpleNamespace(start=1.7, end=2.2, word=' пять.'),
                   SimpleNamespace(start=5.0, end=5.8, word=' Нужен'), SimpleNamespace(start=6.0, end=7.0, word=' проект.')])
        found = speech_segments(part)
        self.assertEqual([(s.start, s.end, s.text) for s in found], [(1.0, 2.2, 'Дом пять.'), (5.0, 7.0, 'Нужен проект.')])

    def test_continuation_without_repeat_and_return_to_address(self):
        units = make_units(segments())
        self.assertEqual(units[5].text, TEXT[4])
        matches = analyze_recording(1, 'sample.mp3', segments(), 'Тополиная 5', False,
                                    ReplyClient(), threading.Event())
        self.assertEqual(len(matches), 2)
        self.assertIn('подготовить чертежи', matches[0].text)
        self.assertIn('Согласуем', matches[0].text)
        self.assertNotIn('кровли', ' '.join(m.text for m in matches))
        self.assertNotIn('двадцать пять', ' '.join(m.text for m in matches))
        self.assertIn('завтра', matches[1].summary)
        self.assertEqual((matches[0].start, matches[0].end), (5, 20))

    def test_no_link_between_independent_calls(self):
        class NeverCalled:
            def complete(self, payload):
                raise AssertionError('No explicit object mention in this call')
        self.assertEqual(analyze_recording(2, 'another.mp3', [Segment(0, 5, 'Там надо подготовить проект.')],
                                         'Тополиная 5', False, NeverCalled(), threading.Event()), [])

    def test_false_times_or_invented_numbers_are_rejected(self):
        units = make_units(segments())
        for block in [
            {'first': 1, 'last': 50, 'summary': 'Работы', 'continues': False},
            {'first': 1, 'last': 4, 'summary': 'Стоимость 500000 рублей.', 'continues': False},
            {'first': 1, 'last': 6, 'summary': 'Проект и аварийный ремонт кровли.', 'continues': False},
        ]:
            with self.subTest(block=block), self.assertRaises(ValueError):
                validate_blocks({'blocks': [block]}, units, [(1, 1)], None)

    def test_model_cannot_create_unanchored_discussion(self):
        result = validate_blocks({'blocks': [{'first': 6, 'last': 6, 'summary': 'Ремонт кровли', 'continues': False}]},
                                 make_units(segments()), [(1, 1)], None)
        self.assertEqual(result, [])

    def test_failed_link_keeps_the_explicit_mention_for_review(self):
        class Empty:
            def complete(self, payload):
                return {'blocks': []}
        matches = analyze_recording(1, 'sample.mp3', segments(), 'Тополиная 5', False, Empty(), threading.Event())
        self.assertTrue(matches)
        self.assertTrue(all(m.analysis_state == 'review' for m in matches))

    def test_cache_survives_reopen_and_invalidates_on_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'db.sqlite'
            audio = Path(tmp) / 'sample.mp3'
            audio.write_bytes(b'audio')
            store = Store(db)
            store.add_files([audio])
            rid = store.rows()[0]['id']
            store.save(rid, 'small', 40, segments())
            matches = analyze_recording(rid, str(audio), segments(), 'Тополиная 5', False, ReplyClient(), threading.Event())
            store.save_analysis(rid, 'Тополиная 5', False, segments(), matches)
            store.close()
            store = Store(db)
            self.assertEqual(len(search_store(store, 'Тополиная 5', False, True)), 2)
            self.assertEqual(search_store(store, 'Тополиная 5', False, True)[0].summary, matches[0].summary)
            self.assertIsNone(store.analysis(rid, 'Тополиная 25', False, segments()))
            store.save(rid, 'medium', 5, [Segment(0, 5, 'Новый текст')])
            self.assertIsNone(store.analysis(rid, 'Тополиная 5', False, segments()))
            store.close()


if __name__ == '__main__':
    unittest.main()
