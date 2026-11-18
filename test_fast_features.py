from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from core import Segment, Store, search_store, search_segments, token_equal
from briefs import source_brief
from fast_asr import timestamped_words, words_to_parts
from semantic import discussion_windows, make_units, analyze_recording


class FastSpeechTests(unittest.TestCase):
    def test_brief_preserves_negation_and_cannot_add_unsaid_work(self):
        parts = [Segment(0, 3, 'Сиреневая восемь'),
                 Segment(3, 8, 'ИТП нет в документах нужно поправить три позиции')]
        brief = source_brief(parts)
        quote = brief.split('«', 1)[1].rstrip('»')
        self.assertIn(quote, ' '.join(p.text for p in parts))
        self.assertIn('нет', quote)
        self.assertNotIn('фасад', brief)
        self.assertNotIn('пятниц', brief)

    def test_brief_prefers_whole_clean_utterance_without_editing_quotes(self):
        parts = [Segment(0, 4, 'Работы в смете не учтены'),
                 Segment(4, 8, 'Блять надо поправить смету и отправить фото')]
        brief = source_brief(parts)
        self.assertIn('«Работы в смете не учтены»', brief)
        self.assertNotIn('Блять', brief)

    def test_ui_search_cache_sees_worker_commits_on_another_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            audio = folder/'call.mp3'; audio.write_bytes(b'audio')
            ui, worker = Store(folder/'calls.sqlite'), Store(folder/'calls.sqlite')
            try:
                ui.add_files([audio]); rid = ui.rows()[0]['id']
                parts = [Segment(0, 5, 'Тополиная пять нужен проект')]
                worker.save(rid, 'gigaam-v3-ctc', 5, parts)
                query = 'Тополиная 5'
                self.assertEqual(search_store(ui, query, True, True)[0].analysis_state, 'pending')
                matches = search_segments(rid, str(audio), parts, query, True)
                matches[0].analysis_state = 'complete'; matches[0].summary = source_brief(parts)
                worker.save_analysis(rid, query, True, parts, matches)
                self.assertEqual(search_store(ui, query, True, True)[0].analysis_state, 'complete')
                worker.save(rid, 'gigaam-v3-ctc', 5, [Segment(0, 5, 'Другой адрес')])
                self.assertEqual(search_store(ui, query, True, True), [])
            finally:
                ui.close(); worker.close()

    def test_token_times_keep_source_offsets_and_exclude_padding(self):
        result=SimpleNamespace(tokens=['дом',' ','пять',' ','шум'],timestamps=[.2,.5,.6,1.1,3],logprobs=[-.1]*5)
        words=timestamped_words(result, 10, 12)
        self.assertEqual([w.word for w in words], ['дом','пять'])
        self.assertEqual(words[0].start,10.2)
        self.assertAlmostEqual(words[1].end,10.64)

    def test_long_units_and_pauses_keep_words_and_time_order(self):
        words=[SimpleNamespace(word=str(i),start=i,end=i+.2,uncertain=False) for i in range(20)]
        parts=list(words_to_parts(words))
        self.assertEqual(' '.join(p.text for p in parts),' '.join(str(i) for i in range(20)))
        self.assertTrue(all(p.end-p.start <= 8 for p in parts))

    def test_vowel_errors_are_marked_approximate_without_changing_house_numbers(self):
        self.assertEqual(token_equal('тополиная','тапалиной',True),(True,True))
        self.assertEqual(token_equal('5','25',True),(False,False))
        self.assertEqual(len(search_segments(1,'x',[Segment(0,4,'По Тапалиной пять ХВС')],'Тополиная 5',True)),1)
        self.assertEqual(search_segments(1,'x',[Segment(0,4,'По Тапалиной двадцать пять')],'Тополиная 5',True),[])

    def test_context_starts_at_mention_and_stops_at_another_building(self):
        units=make_units([Segment(0,3,'Советская убрать манометр'),Segment(3,6,'Сиреневая восемь есть ИТП'),
                          Segment(6,9,'Его нет в документах'),Segment(9,12,'В одном доме квартиру сделали жильцы'),
                          Segment(12,15,'Позже вернемся к другому вопросу')])
        windows=list(discussion_windows(units,[(1,1)],'Сиреневая 8'))
        self.assertEqual([u.id for batch,_ in windows for u in batch],[1,2])

    def test_query_alternatives_are_analyzed_independently(self):
        import threading
        calls=[]
        class Client:
            def complete(self,payload):
                calls.append(payload['объект_или_запрос'])
                rows=payload['реплики']
                return {'blocks':[{'first':rows[0]['id'],'last':rows[-1]['id'],'summary':'Обсуждают работы.','continues':False}]}
        result=analyze_recording(1,'x',[Segment(0,3,'Сиреневая восемь нужен проект')],
            'Тополиная 5; Сиреневая 8',True,Client(),threading.Event())
        self.assertEqual(calls,['Сиреневая 8'])
        self.assertEqual(len(result),1)


class GroupSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.window=Window(self.root/'data')
        paths=[]
        for name in ['A01','A02','A03','A04','B05']:
            p=self.root/(name+'.mp3'); p.write_bytes(b'test'); paths.append(p)
        self.window.store.add_files(paths)
        self.window.selector.show_all()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()

    def test_shift_ctrl_and_group_buttons_within_filtered_list(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        c=self.window.selector
        c.name_edit.setText('A0')
        c.set_visible_checked(False)
        self.app.processEvents()
        def click(row, modifier=Qt.KeyboardModifier.NoModifier):
            QTest.mouseClick(c.table.viewport(),Qt.MouseButton.LeftButton,modifier,
                             c.table.visualItemRect(c.table.item(row,1)).center())
        click(0)
        click(2,Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(len(c.highlighted_ids()),3)
        click(3,Qt.KeyboardModifier.ControlModifier)
        click(1,Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(c.highlighted_ids()),3)
        selected=set(c.highlighted_ids())
        c.check_highlighted.click()
        self.assertEqual(set(c.active_ids()),selected)
        c.uncheck_highlighted.click()
        self.assertEqual(len(c.active_ids()),0)
        c.set_visible_checked(True)
        c.only_highlighted.click()
        self.assertEqual(set(c.active_ids()),selected)
        hidden=[r for r in self.window.store.rows() if Path(r['path']).name=='B05.mp3'][0]
        self.assertTrue(hidden['selected'])
        self.assertNotIn(hidden['id'],c.active_ids())

    def test_existing_creation_preference_migrates_once(self):
        c=self.window.selector
        c.restore({'date_source':'created_ns'})
        self.assertEqual(c.date_source.currentData(),'mtime_ns')
        c.restore({'date_source':'created_ns','date_preference_version':2})
        self.assertEqual(c.date_source.currentData(),'created_ns')


if __name__=='__main__':unittest.main()
