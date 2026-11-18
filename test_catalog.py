import csv
from datetime import date, datetime
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import Store, Segment, scan_folder, search_store, export_csv
from engine import transcribe_batch
from semantic import analyze_batch
from file_filters import FileFilter


def ns(day, hour=12):
    return int(datetime(day.year, day.month, day.day, hour, 0).timestamp() * 1e9)


class FilterTests(unittest.TestCase):
    def row(self, name='Звонок_Иванов.mp3', created=date(2026, 11, 19), size=1536000, modified=date(2026, 11, 18)):
        return {'path': str(Path('test-catalog').resolve() / name), 'created_ns': ns(created),
                'mtime_ns': ns(modified), 'size': size, 'status': 'pending'}

    def test_combined_filters_are_an_intersection(self):
        filter_ = FileFilter(name='иванов', date_from=date(2026, 11, 18), date_to=date(2026, 11, 18),
                             size_min=20 * 1024, size_max=int(1.5 * 1024 ** 2))
        self.assertTrue(filter_.includes(self.row()))
        self.assertFalse(filter_.includes(self.row('Звонок_Петров.mp3')))
        self.assertFalse(filter_.includes(self.row(modified=date(2026, 11, 17))))
        self.assertFalse(filter_.includes(self.row(size=2 * 1024 ** 2)))
        self.assertFalse(filter_.includes(self.row(size=10 * 1024)))

    def test_modification_date_is_default_and_end_date_is_inclusive(self):
        f = FileFilter(date_from=date(2026, 11, 18), date_to=date(2026, 11, 18))
        row = self.row()
        row['mtime_ns'] = ns(date(2026, 11, 18), 23)
        self.assertTrue(f.includes(row))
        f.date_source = 'created_ns'
        self.assertFalse(f.includes(row))
        row['created_ns'] = 0
        self.assertFalse(f.includes(row))

    def test_filename_modes_and_alternatives(self):
        row = self.row()
        self.assertTrue(FileFilter(name='звонок_иванов.mp3', name_mode='exact').includes(row))
        self.assertFalse(FileFilter(name='Иванов.mp3', name_mode='exact').includes(row))
        self.assertTrue(FileFilter(name='ЗВОН', name_mode='starts').includes(row))
        self.assertTrue(FileFilter(name='*Иванов*.mp?', name_mode='wildcard').includes(row))
        self.assertTrue(FileFilter(name='петров; иванов').includes(row))

    def test_folder_boundary_and_recursion(self):
        base = Path('test-catalog').resolve()
        f = FileFilter(folder=str(base), recursive=False)
        self.assertTrue(f.includes(self.row()))
        sub = self.row(str(Path('inside') / 'call.mp3'))
        self.assertFalse(f.includes(sub))
        f.recursive = True
        self.assertTrue(f.includes(sub))
        row = self.row()
        row['path'] = str(base.with_name('test-catalog-other') / 'call.mp3')
        self.assertFalse(f.includes(row))

    def test_invalid_ranges_select_nothing(self):
        for f in [FileFilter(date_from=date(2026, 11, 20), date_to=date(2026, 11, 18)),
                  FileFilter(size_min=2000, size_max=1000)]:
            self.assertTrue(f.error())
            self.assertFalse(f.includes(self.row()))


class SelectionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'db.sqlite3'
        self.store = Store(self.db)
        self.paths = [self.root / f'call-{i}.mp3' for i in range(3)]
        for i, path in enumerate(self.paths):
            path.write_bytes(b'x' * (100 + i))
        self.store.add_files(self.paths)
        self.ids = [r['id'] for r in self.store.rows()]

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_creation_metadata_and_checks_survive_reimport(self):
        stat = self.paths[0].stat()
        self.assertEqual(self.store.row(self.ids[0])['created_ns'], getattr(stat, 'st_birthtime_ns', stat.st_ctime_ns))
        self.store.set_selected([self.ids[0]], False)
        self.store.add_files(self.paths)
        self.assertEqual(self.store.row(self.ids[0])['selected'], 0)
        self.assertEqual(self.store.row(self.ids[1])['selected'], 1)
        self.paths[0].write_bytes(b'changed recording')
        self.store.add_files([self.paths[0]])
        self.assertEqual(self.store.row(self.ids[0])['selected'], 0)

    def test_upgrade_preserves_existing_transcripts(self):
        old_path = self.root / 'legacy.sqlite'
        old = sqlite3.connect(old_path)
        old.executescript('''
            CREATE TABLE recordings(id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', model TEXT NOT NULL DEFAULT '',
                duration REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE segments(recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL, text TEXT NOT NULL,
                uncertain INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(recording_id,position));
            INSERT INTO recordings(id,path,size,mtime_ns,status) VALUES (1,'old-call.mp3',123,1,'ready');
            INSERT INTO segments VALUES (1,0,0,3,'Existing transcript',0);
        ''')
        old.close()
        upgraded = Store(old_path)
        try:
            self.assertEqual(upgraded.row(1)['selected'], 1)
            self.assertEqual(upgraded.row(1)['created_ns'], 0)
            self.assertEqual(upgraded.segments(1)[0].text, 'Existing transcript')
        finally:
            upgraded.close()

    def test_only_requested_files_reach_asr_and_missing_unselected_file_is_untouched(self):
        seen = []
        class Model:
            def transcribe(_, path, **kwargs):
                seen.append(Path(path).name)
                part = SimpleNamespace(start=0, end=3, text='Тополиная пять.', avg_logprob=0, no_speech_prob=0)
                return iter([part]), SimpleNamespace(duration=3)
        self.paths[2].unlink()
        result = transcribe_batch(self.db, self.root, 'small', threading.Event(), lambda *a: None, lambda: None,
                                  lambda *a: Model(), recording_ids={self.ids[1]})
        self.assertEqual(result['ok'], 1)
        self.assertEqual(seen, ['call-1.mp3'])
        self.assertEqual(self.store.row(self.ids[0])['status'], 'pending')
        self.assertEqual(self.store.row(self.ids[2])['status'], 'pending')

    def test_only_requested_files_reach_analysis_search_and_export(self):
        for rid in self.ids:
            self.store.save(rid, 'small', 3, [Segment(0, 3, 'Тополиная пять.')])
        class Client:
            calls = 0
            def __init__(self, *a): pass
            def complete(self, payload):
                Client.calls += 1
                return {'blocks': [{'first': 0, 'last': 0, 'summary': 'Упоминание адреса.', 'continues': False}]}
            def close(self): pass
        result = analyze_batch(self.db, self.root, 'Тополиная 5', False, threading.Event(), lambda *a: None,
                                lambda: None, Client, recording_ids={self.ids[1]})
        self.assertEqual((result['analyzed'], Client.calls), (1, 1))
        self.assertIsNone(self.store.analysis(self.ids[0], 'Тополиная 5', False, self.store.segments(self.ids[0])))
        found = search_store(self.store, 'Тополиная 5', False, True, {self.ids[1]})
        self.assertEqual([m.recording_id for m in found], [self.ids[1]])
        target = self.root / 'result.csv'
        export_csv(target, found)
        with target.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f, delimiter=';'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(Path(rows[1][0]).name, 'call-1.mp3')

    def test_empty_scope_never_loads_a_model(self):
        def forbidden(*a):
            raise AssertionError('Must not load a model for an empty selection')
        transcribe_batch(self.db, self.root, 'small', threading.Event(), lambda *a: None, lambda: None,
                         forbidden, recording_ids=[])
        for rid in self.ids:
            self.store.save(rid, 'small', 3, [Segment(0, 3, 'Тополиная пять.')])
        analyze_batch(self.db, self.root, 'Тополиная 5', False, threading.Event(), lambda *a: None,
                      lambda: None, forbidden, recording_ids=[])
        self.assertEqual(search_store(self.store, 'Тополиная 5', recording_ids=[]), [])

    def test_nonrecursive_scan(self):
        sub = self.root / 'inside'
        sub.mkdir()
        (sub / 'extra.mp3').write_bytes(b'hello')
        (sub / 'ignore.txt').write_text('ignore')
        self.assertEqual(len(scan_folder(self.root, recursive=False)[0]), 3)
        self.assertEqual(len(scan_folder(self.root, recursive=True)[0]), 4)


class CatalogGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = Window(self.root / 'data')
        self.window.show()
        self.paths = [self.root / name for name in ['Иванов_проект.mp3', 'Иванов_смета.mp3', 'Петров.mp3']]
        for path, size in zip(self.paths, [30 * 1024, 1500 * 1024, 300 * 1024]):
            path.write_bytes(b'x' * size)
        self.window.add_paths(self.paths)
        self.catalog = self.window.selector
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_filter_check_sort_and_bulk_selection(self):
        from PySide6.QtCore import Qt
        c = self.catalog
        self.assertEqual(len(c.active_ids()), 3)
        c.name_edit.setText('иванов')
        c.max_on.setChecked(True)
        c.size_max.setValue(100)
        self.assertEqual(len(c.active_ids()), 1)
        self.assertEqual(Path(c.visible_rows[0]['path']).name, 'Иванов_проект.mp3')
        c.set_visible_checked(False)
        self.assertEqual(c.active_ids(), frozenset())
        self.assertEqual(sum(r['selected'] for r in self.window.store.rows()), 2)
        c.reset_filters()
        c.table.sortItems(3, Qt.SortOrder.DescendingOrder)
        largest = c.table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        self.assertEqual(Path(self.window.store.row(largest)['path']).name, 'Иванов_смета.mp3')
        c.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(self.window.store.row(largest)['selected'])
        self.assertEqual(len(c.active_ids()), 1)
        self.assertTrue(next(iter(c.active_ids())) != largest)

    def test_creation_date_filter_and_invalid_dates(self):
        from PySide6.QtCore import QDate
        c = self.catalog
        self.assertEqual(c.date_source.currentData(), 'mtime_ns')
        c.from_on.setChecked(True)
        c.to_on.setChecked(True)
        c.date_from.setDate(QDate.currentDate())
        c.date_to.setDate(QDate.currentDate())
        self.assertEqual(len(c.active_ids()), 3)
        c.date_from.setDate(QDate.currentDate().addDays(1))
        self.assertEqual(c.active_ids(), frozenset())
        self.assertIn('позже', c.message.text())

    def test_changed_unloaded_folder_blocks_work_and_results_follow_selection(self):
        c = self.catalog
        for row in self.window.store.rows():
            self.window.store.save(row['id'], 'small', 3, [Segment(0, 3, 'Тополиная пять.')])
        self.window.query.setText('Тополиная 5')
        self.window.search()
        self.assertEqual(len(self.window.matches), 3)
        c.name_edit.setText('Петров')
        self.assertEqual(len(self.window.matches), 1)
        c.path_edit.setText(str(self.root / 'new-folder'))
        self.assertEqual(c.active_ids(), frozenset())
        self.assertEqual(self.window.matches, [])
        self.window.start()
        self.assertIsNone(self.window.worker)

    def test_run_scope_is_frozen_when_status_filter_changes_during_work(self):
        c = self.catalog
        c.state_filter.setCurrentIndex(c.state_filter.findData('pending'))
        ids = c.active_ids()
        self.window.result_ids = frozenset(ids)
        for row in self.window.store.rows(ids):
            self.window.store.save(row['id'], 'small', 3, [Segment(0, 3, 'Тополиная пять.')])
        self.window.query.setText('Тополиная 5')
        self.window.flush_changes()
        self.assertEqual(c.active_ids(), frozenset())
        self.assertEqual(len(self.window.matches), 3)
        c.reset_filters()
        c.set_visible_checked(False)
        self.assertEqual(self.window.matches, [])


if __name__ == '__main__':
    unittest.main()
