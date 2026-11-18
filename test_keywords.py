import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from core import Segment, Store, search_segments, search_store
from semantic import analyze_recording

QUERY = 'тополиная проект хвс'
PARTS = [Segment(0, 5, 'ХВС уже есть в смете.'),
         Segment(60, 65, 'Нужны правки проекта.'),
         Segment(180, 185, 'Это по Тополиной.')]


class KeywordTests(unittest.TestCase):
    def test_all_words_can_be_far_apart_and_in_reverse_order(self):
        found = search_segments(1, 'call.mp3', PARTS, QUERY, False, 'keywords', 'all')
        self.assertEqual([m.start for m in found], [0, 60, 180])
        self.assertEqual(search_segments(1, 'call.mp3', PARTS, QUERY, False), [])

    def test_any_rule_does_not_require_every_word(self):
        parts = [Segment(0, 5, 'Правки проекта отправлены.')]
        self.assertEqual(search_segments(1, 'x', parts, QUERY, False, 'keywords', 'all'), [])
        self.assertEqual(len(search_segments(1, 'x', parts, QUERY, False, 'keywords', 'any')), 1)

    def test_cases_adjectives_and_short_words_without_fuzzy_spelling(self):
        for phrase, query in [('Нет проекта', 'проект'), ('Проектные работы', 'проект'),
                              ('Около дома', 'дом'), ('Чертежи переданы', 'чертёж')]:
            with self.subTest(phrase=phrase):
                self.assertTrue(search_segments(1, 'x', [Segment(0, 1, phrase)], query, False, 'keywords'))
        self.assertFalse(search_segments(1, 'x', [Segment(0, 1, 'Проектор')], 'проект', False, 'keywords'))

    def test_house_numbers_remain_exact(self):
        parts = [Segment(0, 5, 'Тополиная двадцать пять проект хвс')]
        self.assertEqual(search_segments(1, 'x', parts, 'тополиная 5', True, 'keywords'), [])

    def test_all_rule_never_combines_different_recordings_and_cache_modes_do_not_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = [root/'a.mp3', root/'b.mp3']
            for f in files: f.write_bytes(b'audio')
            s = Store(root/'calls.sqlite')
            try:
                s.add_files(files)
                a, b = [r['id'] for r in s.rows()]
                s.save(a, 'test', 5, [PARTS[0]])
                s.save(b, 'test', 185, PARTS[1:])
                self.assertEqual(search_store(s, QUERY, False, search_mode='keywords'), [])
                self.assertEqual(len(search_store(s, QUERY, False, search_mode='keywords', keyword_rule='any')), 3)
                s.save(a, 'test', 185, PARTS)
                found = search_store(s, QUERY, False, True, {a}, 'keywords', 'all')
                found[0].summary = 'Проверенное описание'; found[0].analysis_state = 'complete'
                s.save_analysis(a, QUERY, False, PARTS, found, search_mode='keywords', keyword_rule='all')
                self.assertEqual(search_store(s, QUERY, False, True, {a}), [])
                self.assertEqual(search_store(s, QUERY, False, True, {a}, 'keywords', 'all')[0].summary, 'Проверенное описание')
                self.assertIsNone(s.analysis(a, QUERY, False, PARTS, 'keywords', 'any'))
            finally:
                s.close()

    def test_selected_details_receive_keyword_mode_and_keep_source_times(self):
        payloads = []
        class Client:
            def complete(self, payload):
                payloads.append(payload)
                rows = payload['реплики']
                return {'blocks': [{'first': rows[0]['id'], 'last': rows[-1]['id'], 'continues': False}]}
        found = analyze_recording(1, 'x', PARTS, QUERY, False, Client(), threading.Event(), 'keywords', 'all')
        self.assertEqual(payloads[0]['режим_поиска'], 'keywords')
        self.assertEqual((found[0].start, found[0].end), (0, 185))
        self.assertEqual(found[0].analysis_state, 'complete')


class KeywordGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt = QApplication.instance() or QApplication([])

    def test_modes_and_visible_date_filter_explain_excluded_november_call(self):
        from app import Window
        from PySide6.QtCore import QDate
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            w = Window(root/'data')
            files = [root/'Демо-июнь.mp3', root/'Демо-ноябрь.mp3']
            for f in files: f.write_bytes(b'audio')
            w.store.add_files(files)
            for r in w.store.rows():
                november = 'ноябрь' in r['path']
                date = datetime(2026, 11, 18) if november else datetime(2026, 6, 1)
                with w.store.conn:
                    w.store.conn.execute('UPDATE recordings SET mtime_ns=? WHERE id=?', (int(date.timestamp()*1e9), r['id']))
                w.store.save(r['id'], 'test', 185, PARTS if november else [PARTS[1]])
            w.selector.show_all()
            c = w.selector
            c.date_from.setDate(QDate(2026, 2, 2)); c.date_to.setDate(QDate(2026, 7, 1))
            c.from_on.setChecked(True); c.to_on.setChecked(True)
            w.query.setText(QUERY); w.search_mode.setCurrentIndex(w.search_mode.findData('keywords'))
            w.search_timer.stop()
            self.assertEqual(w.matches, [])
            self.assertIn('02.02.2026', w.result_scope_note.text())
            self.assertIn('01.07.2026', w.result_scope_note.text())
            self.assertIn('Дата изменения', w.result_scope_note.text())
            w.keyword_rule.setCurrentIndex(w.keyword_rule.findData('any'))
            self.assertEqual(len(w.matches), 1)
            w.keyword_rule.setCurrentIndex(w.keyword_rule.findData('all'))
            c.date_to.setDate(QDate(2026, 11, 18))
            self.assertEqual(len(w.matches), 3)
            self.assertEqual(len({m.recording_id for m in w.matches}), 1)
            w.close()
            restored = Window(root/'data')
            self.assertEqual(restored.search_mode.currentData(), 'keywords')
            self.assertEqual(restored.keyword_rule.currentData(), 'all')
            restored.close()


if __name__ == '__main__': unittest.main()
