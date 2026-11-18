from __future__ import annotations
from i18n import tr

import argparse
import html
import json
import logging
import os
import queue
from pathlib import Path
import subprocess
import sys
import threading
import uuid

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QLockFile
from PySide6.QtGui import QDesktopServices, QFont, QTextCursor, QIcon, QPainter, QPixmap, QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QProgressBar, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QSplitter, QVBoxLayout,
    QHBoxLayout, QFileDialog, QMessageBox, QHeaderView, QAbstractItemView)

from core import (Store, search_store, export_csv, transcript_text,
                  load_settings, save_settings, timecode, copy_recordings)
from engine import transcribe_batch, make_preview
from semantic import analyze_batch
from semantic_assets import Cancelled
from catalog import FileCatalog
from file_filters import display_size
from performance import background_priority
from process_control import stop_process_tree

from runtime_paths import application_dir, worker_command
BASE = application_dir()
STATES = {'pending': tr('Не проверен'), 'ready': tr('Готово'), 'running': tr('Распознаётся'), 'error': tr('Ошибка')}
from desktop_theme import STYLE, apply_palette, lift



class Worker(QThread):
    progress = Signal(int, int, str, int)
    changed = Signal()
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, db, models, model, query, fuzzy, analysis_only=False, recording_ids=None, search_mode='phrase', keyword_rule='all'):
        super().__init__()
        self.db, self.models, self.model = db, models, model
        self.query, self.fuzzy, self.analysis_only = query, fuzzy, analysis_only
        self.search_mode, self.keyword_rule = search_mode, keyword_rule
        self.recording_ids = None if recording_ids is None else tuple(sorted(recording_ids))
        self.cancelled = threading.Event()
        self.process = None

    def run(self):
        events = queue.Queue()
        complete = False
        log_path = Path(self.db).parent / 'processing.log'
        try:
            with log_path.open('w', encoding='utf-8') as log:
                self.process = subprocess.Popen(worker_command(self.model, self.analysis_only),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                    text=True, encoding='utf-8', bufsize=1,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                config = dict(db=str(self.db), models=str(self.models), model=self.model,
                    query=self.query, fuzzy=self.fuzzy, analysis_only=self.analysis_only,
                    recording_ids=self.recording_ids, search_mode=self.search_mode, keyword_rule=self.keyword_rule)
                self.process.stdin.write(json.dumps(config, ensure_ascii=True) + '\n')
                self.process.stdin.close()
                def read_events():
                    for line in self.process.stdout:
                        try:
                            events.put(json.loads(line))
                        except ValueError:
                            logging.warning('Unexpected processing output: %s', line.strip())
                    events.put(None)
                threading.Thread(target=read_events, daemon=True).start()
                while True:
                    if self.cancelled.is_set():
                        stop_process_tree(self.process)
                        store = Store(Path(self.db))
                        try:
                            for row in store.rows(self.recording_ids):
                                if row['status'] == 'running':
                                    store.state(row['id'], 'pending')
                        finally:
                            store.close()
                        self.completed.emit({'stopped': True, 'analyzed': 0, 'analysis_failed': 0})
                        complete = True
                        break
                    try:
                        event = events.get(timeout=.05)
                    except queue.Empty:
                        continue
                    if event is None:
                        break
                    kind = event.get('event')
                    if kind == 'progress':
                        self.progress.emit(event['index'], event['total'], event['message'], event['percent'])
                    elif kind == 'changed':
                        self.changed.emit()
                    elif kind == 'completed':
                        self.completed.emit(event['result'])
                        complete = True
                    elif kind == 'failed':
                        self.failed.emit(event['message'])
                        complete = True
                if not complete:
                    self.failed.emit(tr('Обработка неожиданно завершилась. Подробности сохранены в processing.log.'))
        except Exception as exc:
            logging.exception('Processing worker error')
            self.failed.emit(str(exc))
        finally:
            stop_process_tree(self.process)
            store = Store(Path(self.db))
            try:
                for row in store.rows(self.recording_ids):
                    if row['status'] == 'running':
                        store.state(row['id'], 'pending')
            finally:
                store.close()

    def run_pipeline(self):
        try:
            result = {'ok': 0, 'failed': 0, 'stopped': False}
            if not self.analysis_only:
                result = transcribe_batch(self.db, self.models, self.model, self.cancelled,
                                          self.progress.emit, self.changed.emit, recording_ids=self.recording_ids)
            if self.analysis_only and not self.cancelled.is_set():
                result.update(analyze_batch(self.db, Path(self.models).parent / 'analysis-model',
                    self.query, self.fuzzy, self.cancelled, self.progress.emit, self.changed.emit,
                    recording_ids=self.recording_ids, search_mode=self.search_mode, keyword_rule=self.keyword_rule))
            result['stopped'] = self.cancelled.is_set()
            self.completed.emit(result)
        except Cancelled:
            self.completed.emit({'stopped': True, 'analyzed': 0, 'analysis_failed': 0})
        except Exception as exc:
            logging.exception('Transcription error')
            self.failed.emit(str(exc))


class PreviewWorker(QThread):
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, source, start, end, destination):
        super().__init__()
        self.args = source, start, end, destination

    def run(self):
        try:
            self.ready.emit(str(make_preview(*self.args)))
        except Exception as exc:
            self.failed.emit(str(exc))


def label(text, name=None):
    w = QLabel(text)
    w.setWordWrap(True)
    if name:
        w.setObjectName(name)
    return w


def button(text, callback, primary=False):
    w = QPushButton(text)
    w.clicked.connect(callback)
    if primary:
        w.setObjectName('primary')
    return w


class Window(QMainWindow):
    def __init__(self, data_dir=None):
        super().__init__()
        self.data = Path(data_dir or BASE / 'data')
        self.data.mkdir(parents=True, exist_ok=True)
        self.db = self.data / 'recordings.sqlite3'
        self.store = Store(self.db)
        self.store.recover()
        self.settings_path = self.data / 'settings.json'
        self.settings = load_settings(self.settings_path)
        self.worker = self.preview_worker = None
        self.matches = []
        self.selected_rid = None
        self.selected_match = None
        self.preview_paths = []
        self.play_request_active = False
        self.result_ids = None
        self.result_filter_description = None
        self._refreshing_catalog = False
        self.setWindowTitle('AudioDetect')
        self.resize(1280, 850)
        self.setMinimumSize(980, 720)
        self.setStyleSheet(STYLE)
        apply_palette(QApplication.instance())
        pixmap = QPixmap(48, 48)
        pixmap.fill(QColor('#203d3f'))
        painter = QPainter(pixmap)
        painter.setPen(QColor('#ff9f8f'))
        for x, height in [(12, 12), (20, 26), (28, 34), (36, 18)]:
            painter.drawLine(x, 24 - height // 2, x, 24 + height // 2)
        painter.end()
        self.setWindowIcon(QIcon(pixmap))
        root = QWidget()
        root.setObjectName('workspace')
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget()
        header.setObjectName('header')
        h = QHBoxLayout(header)
        h.setContentsMargins(28, 20, 28, 20)
        titles = QVBoxLayout()
        titles.addWidget(label('AudioDetect', 'title'))
        titles.addWidget(label(tr('Поиск слов, фраз и обсуждений в телефонных записях'), 'subtitle'))
        h.addLayout(titles, 1)
        h.addWidget(label(tr('Распознавание на вашем ПК\nЗаписи не отправляются в интернет'), 'subtitle'))
        outer.addWidget(header)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.selector = FileCatalog(self.store, self.db, self.settings.get('catalog', {'folder': self.settings.get('folder', '')}))
        self.tabs.addTab(self.selector, tr('1. Записи'))
        right = QWidget()
        main = QVBoxLayout(right)
        main.setContentsMargins(24, 16, 24, 18)
        main.setSpacing(10)
        scope_line = QHBoxLayout()
        self.selection_info = label('', 'muted')
        scope_line.addWidget(self.selection_info, 1)
        scope_line.addWidget(button(tr('Изменить выбор файлов'), lambda: self.tabs.setCurrentIndex(0)))
        scope_line.addWidget(label(tr('Распознавание:'), 'muted'))
        self.model = QComboBox()
        self.model.addItem(tr('Русская речь · быстро'), 'gigaam-v3-ctc')
        self.model.addItem(tr('Другие языки · стандарт'), 'small')
        self.model.addItem(tr('Другие языки · точнее, медленнее'), 'medium')
        self.model.addItem(tr('Другие языки · быстрее'), 'base')
        selected_model = self.settings.get('model', 'gigaam-v3-ctc') if self.settings.get('engine_version', 0) >= 3 else 'gigaam-v3-ctc'
        self.model.setCurrentIndex(max(0, self.model.findData(selected_model)))
        scope_line.addWidget(self.model)
        main.addLayout(scope_line)
        main.addWidget(label(tr('Найдите нужный разговор'), 'pageTitle'))
        main.addWidget(label(tr('Введите тему, слова из разговора или адрес. Мы покажем записи и точное место, где встретился запрос.'), 'heroText'))
        main.addSpacing(16)
        main.addWidget(label(tr('Что найти в разговорах?'), 'section'))
        query_row = QHBoxLayout()
        self.query = QLineEdit(self.settings.get('query', ''))
        self.query.setPlaceholderText(tr('Например: перенос сроков'))
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.start)
        query_row.addWidget(self.query, 1)
        self.start_button = button(tr('Проверить выбранные'), self.start, True)
        self.start_button.setMinimumHeight(48)
        lift(self.start_button, True)
        main.addLayout(query_row)
        options = QHBoxLayout()
        self.search_mode = QComboBox()
        self.search_mode.addItem(tr('Фраза'), 'phrase')
        self.search_mode.addItem(tr('Ключевые слова'), 'keywords')
        self.search_mode.setToolTip(tr('Фраза: связанные слова рядом, в том числе адрес с номером дома. Ключевые слова: отдельные совпадения в пределах всей записи.'))
        self.search_mode.setCurrentIndex(max(0, self.search_mode.findData(self.settings.get('search_mode', 'phrase'))))
        self.keyword_rule = QComboBox()
        self.keyword_rule.addItem(tr('Все слова (И)'), 'all')
        self.keyword_rule.addItem(tr('Любое слово (ИЛИ)'), 'any')
        self.keyword_rule.setCurrentIndex(max(0, self.keyword_rule.findData(self.settings.get('keyword_rule', 'all'))))
        self.keyword_rule.setVisible(self.search_mode.currentData() == 'keywords')
        options.addWidget(self.search_mode)
        options.addWidget(self.keyword_rule)
        self.fuzzy = QCheckBox(tr('Искать похожие написания'))
        self.fuzzy.setChecked(bool(self.settings.get('fuzzy', True)) if self.settings.get('engine_version', 0) >= 3 else True)
        self.fuzzy.setToolTip(tr('Допускает небольшие ошибки в словах. Числа сравниваются точно. Похожие совпадения будут помечены.'))
        self.fuzzy.toggled.connect(self.search)
        options.addWidget(self.fuzzy)
        options.addStretch()
        self.search_button = button(tr('Подробности выбранных записей'), self.start_details)

        main.addLayout(options)
        self.query_hint = label('', 'muted')
        main.addWidget(self.query_hint)

        main.addSpacing(16)
        example_panel = QWidget()
        example_panel.setObjectName('panel')
        examples = QVBoxLayout(example_panel)
        examples.setContentsMargins(22, 18, 22, 18)
        examples.addWidget(label(tr('Как сформулировать запрос'), 'section'))
        examples.addWidget(label(tr('«договор оплата» — найдёт разговор с обоими словами. «согласование сметы» — найдёт фразу целиком.'), 'muted'))
        example_actions = QHBoxLayout()
        example_actions.addWidget(button(tr('Пример: ключевые слова'), lambda: self.use_example(True)))
        example_actions.addWidget(button(tr('Пример: фраза'), lambda: self.use_example(False)))
        example_actions.addStretch()
        examples.addLayout(example_actions)
        main.addWidget(example_panel)
        main.addStretch(1)
        main.addWidget(label(tr('Новые записи распознаются один раз. Повторный поиск использует готовый текст. Всё хранится на вашем компьютере.'), 'muted'))
        query_footer = QHBoxLayout()
        query_footer.addWidget(button(tr('Назад к записям'), lambda: self.tabs.setCurrentIndex(0)))
        query_footer.addStretch()
        query_footer.addWidget(self.start_button)
        main.addLayout(query_footer)
        self.tabs.addTab(right, tr('2. Запрос'))
        result_page = QWidget()
        main = QVBoxLayout(result_page)
        main.setContentsMargins(24, 16, 24, 18)
        main.setSpacing(10)
        status_row = QHBoxLayout()
        self.status = label(tr('Выберите файлы на первой вкладке, введите запрос и нажмите «Проверить выбранные».'), 'muted')
        status_row.addWidget(self.status, 1)
        self.stop_button = button(tr('Остановить'), self.stop)
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.stop_button.setObjectName('danger')
        status_row.addWidget(self.stop_button)
        main.addLayout(status_row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        main.addWidget(self.progress_bar)
        self.result_title = label(tr('Найденные записи'), 'section')
        result_heading = QHBoxLayout()
        result_heading.addWidget(self.result_title, 1)
        self.show_text_button = QPushButton(tr('Текст и прослушивание ▾'))
        self.show_text_button.setCheckable(True)
        result_heading.addWidget(self.show_text_button)
        main.addLayout(result_heading)
        self.results_note = label(tr('Здесь будут только записи, в которых найден ваш запрос.'), 'muted')
        main.addWidget(self.results_note)
        self.result_scope_note = label('', 'muted')
        self.result_scope_note.setTextFormat(Qt.TextFormat.PlainText)
        self.result_scope_note.setStyleSheet('color:#b8c9c1;background:#203d3f;padding:8px;border-radius:6px;')
        main.addWidget(self.result_scope_note)
        self.vertical = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 4)
        self.table.setMinimumHeight(132)
        self.table.setHorizontalHeaderLabels([tr('Файл'), tr('Время в записи'), tr('Фрагмент разговора'), tr('Кратко, что обсуждали')])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 250)
        self.table.setColumnWidth(1, 125)
        self.table.itemSelectionChanged.connect(self.select_match)
        self.table.cellDoubleClicked.connect(lambda *_: (self.show_text_button.setChecked(True), self.play()))
        self.table.setAlternatingRowColors(True)
        self.vertical.addWidget(self.table)
        details = QWidget()
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(0, 9, 0, 0)
        self.detail_title = label(tr('Текст разговора'), 'section')
        detail_layout.addWidget(self.detail_title)
        self.detail_summary = label('', 'muted')
        self.detail_summary.hide()
        detail_layout.addWidget(self.detail_summary)
        self.transcript = QTextBrowser()
        self.transcript.setMinimumHeight(60)
        self.transcript.setOpenLinks(False)
        self.transcript.anchorClicked.connect(self.jump_audio)
        self.transcript.setHtml(tr('<p style="color:#b8c9c1">Выберите найденный фрагмент: здесь откроется разговор целиком. Нажмите время в тексте, чтобы прослушать это место.</p>'))
        detail_layout.addWidget(self.transcript, 1)
        actions = QHBoxLayout()
        self.play_button = button(tr('Слушать фрагмент'), self.play)
        self.stop_audio_button = button(tr('Стоп'), self.stop_audio)
        self.original_button = button(tr('Открыть запись'), self.open_original)
        self.text_button = button(tr('Сохранить текст'), self.export_text)
        for w in [self.play_button, self.stop_audio_button, self.original_button, self.text_button]:
            actions.addWidget(w)
        detail_layout.addLayout(actions)
        self.vertical.addWidget(details)
        self.vertical.setSizes([300, 220])
        self.vertical.setStretchFactor(0, 2)
        self.vertical.setStretchFactor(1, 1)
        details.hide()
        self.show_text_button.toggled.connect(details.setVisible)
        self.show_text_button.toggled.connect(lambda visible: self.table.setVisible(not visible))
        self.show_text_button.toggled.connect(lambda visible: self.show_text_button.setText(
            tr('К списку результатов') if visible else tr('Текст и прослушивание ▾')))
        self.empty_state = QWidget()
        self.empty_state.setObjectName('panel')
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(32, 30, 32, 30)
        empty_layout.addStretch()
        empty_layout.addWidget(label(tr('Здесь появится нужный разговор'), 'pageTitle'))
        self.empty_text = label(tr('Выберите записи, задайте запрос и начните поиск. Каждый результат можно открыть и прослушать с нужной секунды.'), 'heroText')
        empty_layout.addWidget(self.empty_text)
        self.empty_action = button(tr('Перейти к запросу'), lambda: self.tabs.setCurrentIndex(1), True)
        empty_layout.addWidget(self.empty_action, 0, Qt.AlignmentFlag.AlignLeft)
        empty_layout.addStretch()
        main.addWidget(self.empty_state, 1)
        main.addWidget(self.vertical, 1)
        export_row = QHBoxLayout()
        self.copy_button = button(tr('Скопировать найденные записи…'), self.copy_matches)
        self.csv_button = button(tr('Сохранить таблицу CSV…'), self.export_matches)
        export_row.addWidget(button(tr('Изменить запрос'), lambda: self.tabs.setCurrentIndex(1)))
        export_row.addWidget(self.search_button)
        export_row.addStretch()
        export_row.addWidget(self.copy_button)
        export_row.addWidget(self.csv_button)
        main.addLayout(export_row)
        main.addWidget(label(tr('Описание и границы обсуждения определяются автоматически. Проверьте важные выводы по тексту или записи.'), 'muted'))
        self.tabs.addTab(result_page, tr('3. Результаты'))
        self.selector.selectionChanged.connect(self.selection_changed)
        self.selector.openRecording.connect(self.open_catalog_recording)
        self.selector.continueRequested.connect(lambda: self.tabs.setCurrentIndex(1))
        self.selector.loadingChanged.connect(self.catalog_loading)
        self.update_selection_info()
        self.set_detail_enabled(False)
        self.search(quiet=True)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(350)
        self.search_timer.timeout.connect(self.search)
        self.query.textChanged.connect(self.query_changed)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self.flush_changes)
        self.search_mode.currentIndexChanged.connect(self.search_options_changed)
        self.keyword_rule.currentIndexChanged.connect(self.search_options_changed)
        self.update_search_hint()

    def use_example(self, keywords):
        self.search_mode.setCurrentIndex(1 if keywords else 0)
        self.query.setText(tr('договор оплата') if keywords else tr('согласование сметы'))
        self.query.setFocus()

    def update_search_hint(self):
        keywords = self.search_mode.currentData() == 'keywords'
        self.keyword_rule.setVisible(keywords)
        if keywords:
            rule = tr('Все слова должны встретиться') if self.keyword_rule.currentData() == 'all' else tr('Достаточно любого слова')
            self.query_hint.setText(rule + tr(' в одной записи, в любом порядке и в разных репликах. Это отбор по всему разговору; связь тем проверяется в подробностях.'))
            self.query.setPlaceholderText(tr('Например: договор сроки оплата'))
        else:
            self.query_hint.setText(tr('Поиск близко расположенных слов фразы. Варианты разделяйте точкой с запятой: согласование сметы; перенос сроков.'))
            self.query.setPlaceholderText(tr('Например: перенос сроков'))

    def search_options_changed(self, *_):
        self.update_search_hint()
        self.search_timer.stop()
        self.search()

    def query_changed(self):
        self.copy_button.setEnabled(False)
        self.csv_button.setEnabled(False)
        self.start_button.setEnabled(bool(self.query.text().strip()) and bool(self.selector.active_ids()))
        self.search_timer.start()

    def remember(self):
        self.settings.update(engine_version=3, query=self.query.text(), model=self.model.currentData(), fuzzy=self.fuzzy.isChecked(),
                             search_mode=self.search_mode.currentData(), keyword_rule=self.keyword_rule.currentData())
        self.settings['catalog'] = self.selector.settings()
        save_settings(self.settings_path, self.settings)

    def refresh_library(self):
        self._refreshing_catalog = True
        try:
            self.selector.refresh()
        finally:
            self._refreshing_catalog = False
        self.update_selection_info()

    def current_ids(self):
        return self.result_ids if self.result_ids is not None else self.selector.active_ids()

    def update_selection_info(self):
        rows = self.store.rows(self.selector.active_ids())
        self.selection_info.setText(tr('Файлов к следующей проверке: {0} · {1}', len(rows), display_size(sum((r['size'] for r in rows)))))
        self.start_button.setText(tr('Начать поиск ({0})', len(rows)))
        self.start_button.setEnabled(bool(rows) and bool(self.query.text().strip()) and not (self.worker and self.worker.isRunning()))

    def selection_changed(self):
        self.update_selection_info()
        if self._refreshing_catalog:
            return
        self.result_ids = None
        self.result_filter_description = None
        if self.selected_rid is not None and self.store.row(self.selected_rid) is None:
            self.selected_rid = self.selected_match = None
            self.transcript.clear()
            self.detail_summary.hide()
            self.set_detail_enabled(False)
        self.search(quiet=True)
        self.remember()

    def catalog_loading(self, active):
        self.busy(active)
        if not active:
            self.selector.refresh()

    def open_catalog_recording(self, rid):
        self.tabs.setCurrentIndex(2)
        self.empty_state.hide()
        self.vertical.show()
        self.show_transcript(rid)
        self.show_text_button.setChecked(True)

    def add_paths(self, paths, errors=None):
        added, changed, failed = self.store.add_files(paths)
        self.selector.show_all()
        self.status.setText(tr('Добавлено: {0}. Изменённых записей: {1}. Выберите файлы, введите запрос и нажмите «Проверить выбранные».', added, changed))
        self.remember()
        if (errors or []) + failed:
            QMessageBox.warning(self, tr('Некоторые файлы недоступны'), '\n'.join(((errors or []) + failed)[:15]))

    def busy(self, active):
        for w in [self.selector, self.model, self.start_button,
                  self.search_button, self.query, self.fuzzy, self.search_mode, self.keyword_rule]:
            w.setEnabled(not active)
        self.stop_button.setEnabled(active)
        self.stop_button.setVisible(active)
        self.empty_action.setVisible(not active)
        self.search_button.setEnabled(not active and bool(self.matches))
        self.start_button.setEnabled(not active and bool(self.query.text().strip()) and bool(self.selector.active_ids()))

    def start_details(self):
        indexes = self.table.selectionModel().selectedRows()
        ids = {self.matches[index.row()].recording_id for index in indexes if index.row() < len(self.matches)}
        if not ids:
            self.status.setText(tr('Выделите найденные записи в таблице: Shift — диапазон, Ctrl — несколько групп.'))
            return
        self.start(analysis_only=True, work_ids=ids)

    def start(self, checked=False, analysis_only=False, work_ids=None):
        if self.selector.is_scanning():
            self.status.setText(tr('Дождитесь загрузки списка файлов.'))
            return
        if self.worker and self.worker.isRunning():
            self.search()
            return
        if not self.query.text().strip():
            self.query.setFocus()
            self.status.setText(tr('Введите слова или фразу для поиска.'))
            return
        selected_ids = frozenset(work_ids) if work_ids is not None else self.selector.active_ids()
        if not selected_ids:
            self.status.setText(tr('Во вкладке «Выбор записей» отметьте файлы, подходящие под фильтры.'))
            self.tabs.setCurrentIndex(0)
            return
        if work_ids is None or self.result_filter_description is None:
            self.result_filter_description = self.selector.criteria().description()
        self.result_ids = frozenset(self.current_ids() if work_ids is not None else selected_ids)
        self.tabs.setCurrentIndex(2)
        self.remember()
        self.busy(True)
        self.progress_bar.setRange(0, 0)
        self.empty_text.setText(tr('Идёт проверка. Найденные фрагменты будут появляться здесь. Можно остановить работу и продолжить позже.'))
        self.empty_action.setVisible(False)
        self.status.setText(tr('Подготовка распознавания…'))
        self.worker = Worker(self.db, self.data / 'models', self.model.currentData(),
                             self.query.text().strip(), self.fuzzy.isChecked(), analysis_only,
                             recording_ids=selected_ids, search_mode=self.search_mode.currentData(),
                             keyword_rule=self.keyword_rule.currentData())
        self.worker.progress.connect(self.on_progress)
        self.worker.changed.connect(self.on_changed)
        self.worker.completed.connect(self.on_complete)
        self.worker.failed.connect(self.on_failure)
        self.worker.finished.connect(lambda: self.busy(False))
        self.worker.start()

    def stop(self):
        if self.selector.is_scanning():
            self.selector.scan_worker.cancelled.set()
            return
        if self.worker:
            self.worker.cancelled.set()
            self.stop_button.setEnabled(False)
            self.status.setText(tr('Останавливаем вычисления. Готовые результаты сохраняются; текущий файл можно проверить заново.'))

    def on_progress(self, index, total, message, percent):
        if self.worker and self.worker.cancelled.is_set():
            return
        if message.startswith((tr('Подготовка'), tr('Загрузка'))):
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(round(1000 * (index + percent / 100) / max(total, 1)))
        self.status.setText(message)

    def on_changed(self):
        if not self.refresh_timer.isActive():
            self.refresh_timer.start()

    def flush_changes(self):
        self.refresh_library()
        self.search(quiet=True)

    def on_complete(self, result):
        self.refresh_timer.stop()
        self.flush_changes()
        self.progress_bar.setRange(0, 1000)
        if not result['stopped']:
            self.progress_bar.setValue(1000)
        prefix = tr('Остановлено') if result['stopped'] else tr('Проверка завершена')
        errors = sum(r['status'] == 'error' for r in self.store.rows(self.current_ids())) + result.get('analysis_failed', 0)
        self.status.setText(tr('{0}. Найдено записей: {1}. Ошибок: {2}.', prefix, len({m.recording_id for m in self.matches}), errors) +
                            (tr(' Непроверенные записи можно обработать следующим запуском.') if result['stopped'] else ''))

    def on_failure(self, message):
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.on_changed()
        self.status.setText(tr('Проверка не завершена. Готовые расшифровки и описания сохранены.'))
        QMessageBox.warning(self, tr('Проверка не завершена'), message)

    def search(self, checked=False, quiet=False):
        # Keep the displayed transcript and its highlight consistent with a refreshed result list.
        previous = self.selected_match
        self.matches = search_store(self.store, self.query.text(), self.fuzzy.isChecked(),
                                    discussions=True, recording_ids=self.current_ids(),
                                    search_mode=self.search_mode.currentData(), keyword_rule=self.keyword_rule.currentData())
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.matches))
        for i, m in enumerate(self.matches):
            summary = m.summary or ((m.kind + tr('. Подробности ещё не разобраны.')) if tr('ключевые слова') in m.kind.casefold() else tr('Ожидает анализа обсуждения'))
            if m.analysis_state == 'review':
                summary = tr('[Проверить связь] ') + summary
            values = [Path(m.path).name, timecode(m.start) + '–' + timecode(m.end), m.text, summary]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(m.path if j == 0 else (m.kind + '\n' + value) if j == 3 else value)
                self.table.setItem(i, j, item)
        self.table.clearSelection()
        self.table.blockSignals(False)
        self.selected_match = None
        if previous:
            self.show_transcript(previous.recording_id)
        count = len({m.recording_id for m in self.matches})
        rows = self.store.rows(self.current_ids())
        ready = sum(r['status'] == 'ready' for r in rows)
        self.result_title.setText(tr('Найдено записей: {0}  /  фрагментов: {1}', count, len(self.matches)))
        scope_title = tr('В последней проверке') if self.result_ids is not None else tr('В текущем выборе')
        self.result_scope_note.setText(self.result_filter_description or self.selector.criteria().description())
        if self.matches:
            result_message = tr('Выберите фрагмент или скопируйте найденные файлы.')
        elif not rows:
            result_message = tr('Выберите записи на первой вкладке.')
        elif ready < len(rows):
            result_message = tr('Среди готовых расшифровок совпадений нет. Ещё не распознано: {0}.', len(rows) - ready)
        else:
            result_message = tr('Совпадений по запросу в выбранных записях нет.')
        self.results_note.setText(tr('{0}: {1} файлов; распознано: {2}. ', scope_title, len(rows), ready) + result_message)
        self.empty_state.setVisible(not self.matches)
        self.vertical.setVisible(bool(self.matches))
        if not self.matches:
            self.empty_text.setText(result_message)
        active = bool(self.worker and self.worker.isRunning())
        self.empty_action.setVisible(not active)
        self.show_text_button.setEnabled(bool(self.matches))
        self.search_button.setEnabled(bool(self.matches) and not active)
        self.copy_button.setEnabled(bool(self.matches))
        pending = any(m.analysis_state == 'pending' for m in self.matches)
        self.csv_button.setEnabled(bool(self.matches))
        if pending:
            self.results_note.setText(tr('Быстрый отбор: найдены упоминания. Выделите строки через Shift/Ctrl и нажмите «Подробности выбранных записей».'))
        if not quiet:
            self.remember()
            if not (self.worker and self.worker.isRunning()):
                self.status.setText(tr('Поиск выполнен по {0} готовым записям. Найдено файлов: {1}.', ready, count))

    def set_detail_enabled(self, active):
        for w in [self.play_button, self.original_button, self.text_button]:
            w.setEnabled(active)

    def select_match(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.matches):
            m = self.matches[index]
            self.show_transcript(m.recording_id, m)

    def show_transcript(self, rid, match=None):
        row = self.store.row(rid)
        if row is None:
            return
        self.selected_rid, self.selected_match = rid, match
        self.detail_summary.setText(match.summary if match else '')
        self.detail_summary.setVisible(bool(match and match.summary))
        self.detail_title.setText(Path(row['path']).name)
        self.detail_title.setToolTip(row['path'])
        ready = row['status'] == 'ready'
        self.set_detail_enabled(ready)
        if not ready:
            self.transcript.setPlainText(row['error'] or tr('Эта запись ещё не проверена. Отметьте её на первой вкладке, введите запрос и нажмите «Проверить выбранные».'))
            return
        chunks = []
        for i, s in enumerate(self.store.segments(rid)):
            highlight = match and match.first_segment <= i <= match.last_segment
            text = html.escape(s.text)
            marker = '<span style="color:#f2c88c">[?] </span>' if s.uncertain else ''
            bg = 'background-color:#466563;' if highlight else ''
            chunks.append(f'<p id="s{i}" style="{bg}margin:8px 0;padding:5px;">'
                          f'<a href="seek:{s.start}" style="color:#ffb4a4;text-decoration:none;">{timecode(s.start)}</a>'
                          f' &nbsp; {marker}{text}</p>')
        excerpt = (tr('<p><b>Выбранное обсуждение:</b> ') + html.escape(match.text) + '</p><hr>') if match else ''
        self.transcript.setHtml('<body style="font-family:Segoe UI;font-size:15px;color:#f1f2e0;">' + excerpt +
                                (''.join(chunks) or tr('<p>Речь не обнаружена.</p>')) + '</body>')
        self.transcript.moveCursor(QTextCursor.MoveOperation.Start)

    def jump_audio(self, url):
        if url.scheme() == 'seek':
            try:
                start = float(url.path())
                self.play_range(max(0, start - 2), start + 25)
            except ValueError:
                pass

    def play(self):
        m = self.selected_match
        self.play_range(max(0, m.start - 3) if m else 0, m.end + 5 if m else 35)

    def play_range(self, start, end):
        if not self.selected_rid or (self.preview_worker and self.preview_worker.isRunning()):
            return
        row = self.store.row(self.selected_rid)
        if not row:
            return
        self.stop_audio()
        self.play_request_active = True
        destination = self.data / ('preview-' + uuid.uuid4().hex + '.wav')
        self.preview_paths.append(destination)
        self.preview_worker = PreviewWorker(row['path'], start, end, destination)
        self.preview_worker.ready.connect(self.play_ready)
        self.preview_worker.failed.connect(lambda message: QMessageBox.warning(self, tr('Не удалось открыть звук'), message))
        self.preview_worker.start()

    def play_ready(self, path):
        if not self.play_request_active:
            return
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception as exc:
            QMessageBox.warning(self, tr('Не удалось воспроизвести'), str(exc))

    def stop_audio(self):
        self.play_request_active = False
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except (ImportError, RuntimeError):
            pass

    def open_original(self):
        row = self.store.row(self.selected_rid)
        if row and Path(row['path']).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(row['path']))
        else:
            QMessageBox.warning(self, tr('Файл не найден'), tr('Исходная запись перемещена или удалена.'))

    def export_text(self):
        row = self.store.row(self.selected_rid)
        if row is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr('Сохранить расшифровку'), Path(row['path']).stem + '.txt', tr('Текст (*.txt)'))
        if path:
            try:
                Path(path).write_text(transcript_text(row, self.store.segments(row['id'])), encoding='utf-8-sig')
                self.status.setText(tr('Расшифровка сохранена: ') + path)
            except OSError as exc:
                QMessageBox.warning(self, tr('Не удалось сохранить'), str(exc))

    def export_matches(self):
        path, _ = QFileDialog.getSaveFileName(self, tr('Сохранить найденные фрагменты'), tr('Найденные разговоры.csv'), tr('Таблица CSV (*.csv)'))
        if path:
            try:
                export_csv(path, self.matches)
                self.status.setText(tr('Список сохранён: ') + path)
            except OSError as exc:
                QMessageBox.warning(self, tr('Не удалось сохранить'), str(exc))

    def copy_matches(self):
        destination = QFileDialog.getExistingDirectory(self, tr('Папка, куда скопировать найденные записи'))
        if not destination:
            return
        copied, failed = copy_recordings(self.matches, destination)
        self.status.setText(tr('Скопировано записей: {0}. Папка: {1}', len(copied), destination))
        if failed:
            QMessageBox.warning(self, tr('Некоторые записи не скопированы'), '\n'.join(failed[:15]))

    def closeEvent(self, event):
        if self.selector.is_scanning():
            self.selector.scan_worker.cancelled.set()
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.stop()
            self.status.setText(tr('Идёт остановка. Готовые результаты сохранятся. Закройте окно после завершения остановки.'))
            event.ignore()
            return
        if self.preview_worker and self.preview_worker.isRunning():
            event.ignore()
            return
        self.stop_audio()
        self.search_timer.stop()
        self.refresh_timer.stop()
        self.remember()
        for path in self.preview_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self.store.close()
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=BASE / 'data')
    parser.add_argument('--language', choices=['ru', 'en'])
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=args.data_dir / 'app.log', encoding='utf-8', level=logging.WARNING)
    app = QApplication(sys.argv[:1])
    app.setFont(QFont('Segoe UI', 10))
    from language_dialog import choose_language
    from i18n import set_language
    choice = args.language or choose_language(args.data_dir)
    if choice is None:
        return 0
    set_language(choice)
    import catalog
    for states in (STATES, catalog.STATES):
        for key, value in list(states.items()):
            states[key] = tr(value)

    lock = QLockFile(str(args.data_dir / 'app.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, 'AudioDetect', tr('Программа уже открыта. Найдите её окно на панели задач.'))
        return 0
    window = Window(args.data_dir)
    window.show()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == '__main__':
    sys.exit(main())
