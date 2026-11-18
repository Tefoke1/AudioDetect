from i18n import tr
"""File picker with combined filters, persistent checkboxes, and an explicit work set."""
from pathlib import Path
import threading

from PySide6.QtCore import Qt, Signal, QThread, QDate
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QDateEdit, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QMessageBox)

from core import Store, scan_folder
from file_filters import FileFilter, display_size, display_date

STATES = {'pending': tr('Не проверен'), 'ready': tr('Готово'), 'running': tr('Распознаётся'), 'error': tr('Ошибка')}


class SortItem(QTableWidgetItem):
    def __init__(self, text, value):
        super().__init__(text)
        self.sort_value = value

    def __lt__(self, other):
        return self.sort_value < other.sort_value


class CatalogTable(QTableWidget):
    toggleRows = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggleRows.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class ScanWorker(QThread):
    completed = Signal(dict)

    def __init__(self, db, folder, recursive):
        super().__init__()
        self.db, self.folder, self.recursive = db, folder, recursive
        self.cancelled = threading.Event()

    def run(self):
        store = None
        try:
            paths, errors = scan_folder(self.folder, self.recursive, self.cancelled)
            if self.cancelled.is_set():
                self.completed.emit({'cancelled': True})
                return
            store = Store(self.db)
            added, changed, failed = store.add_files(paths)
            self.completed.emit({'folder': self.folder, 'added': added, 'changed': changed,
                                 'errors': errors + failed})
        except Exception as exc:
            self.completed.emit({'errors': [str(exc)]})
        finally:
            if store:
                store.close()


class FileCatalog(QWidget):
    selectionChanged = Signal()
    openRecording = Signal(int)
    continueRequested = Signal()
    loadingChanged = Signal(bool)

    def __init__(self, store, db, settings):
        super().__init__()
        self.store, self.db = store, db
        self.scan_worker = None
        self.visible_rows = []
        self.root_path = settings.get('folder', '')
        self._restoring = True
        main = QVBoxLayout(self)
        main.setContentsMargins(24, 18, 24, 18)
        main.setSpacing(12)
        folder_line = QHBoxLayout()
        self.path_edit = QLineEdit(self.root_path)
        self.path_edit.setPlaceholderText(tr('Путь к папке с записями — вставьте сюда или выберите справа'))
        self.path_edit.returnPressed.connect(self.load_folder)
        self.folder_button = QPushButton(tr('Выбрать папку…'))
        self.folder_button.clicked.connect(self.browse_folder)
        self.refresh_button = QPushButton(tr('Показать / обновить'))
        self.refresh_button.clicked.connect(self.load_folder)
        folder_line.addWidget(self.path_edit, 1)
        folder_line.addWidget(self.folder_button)
        folder_line.addWidget(self.refresh_button)
        main.addLayout(folder_line)
        source_line = QHBoxLayout()
        self.recursive = QCheckBox(tr('Включая вложенные папки'))
        self.recursive.setChecked(settings.get('recursive', True))
        source_line.addWidget(self.recursive)
        self.files_button = QPushButton(tr('Добавить отдельные файлы…'))
        self.files_button.clicked.connect(self.add_files)
        source_line.addWidget(self.files_button)
        self.all_button = QPushButton(tr('Все добавленные папки'))
        self.all_button.clicked.connect(self.show_all)
        source_line.addWidget(self.all_button)
        source_line.addStretch()
        main.addLayout(source_line)

        filters = QGridLayout()
        filters.setHorizontalSpacing(10)
        filters.setVerticalSpacing(10)
        filters.addWidget(QLabel(tr('Название')), 0, 0)
        self.name_mode = QComboBox()
        for title, value in [(tr('Содержит'), 'contains'), (tr('Точное имя'), 'exact'), (tr('Начинается с'), 'starts'), (tr('Шаблон (*, ?)'), 'wildcard')]:
            self.name_mode.addItem(title, value)
        filters.addWidget(self.name_mode, 0, 1)
        self.name_edit = QLineEdit()
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.setPlaceholderText(tr('Имя или часть имени; несколько вариантов разделяйте ;'))
        self.name_edit.setToolTip(tr('Регистр букв не важен. Варианты через ; означают «любой из них». Точное имя включает расширение.'))
        filters.addWidget(self.name_edit, 0, 2, 1, 5)
        filters.addWidget(QLabel(tr('Дата')), 1, 0)
        self.date_source = QComboBox()
        self.date_source.addItem(tr('Дата изменения файла'), 'mtime_ns')
        self.date_source.addItem(tr('Дата создания файла'), 'created_ns')
        filters.addWidget(self.date_source, 1, 1)
        self.from_on, self.to_on = QCheckBox(tr('с')), QCheckBox(tr('по'))
        self.date_from, self.date_to = QDateEdit(), QDateEdit()
        for widget in [self.date_from, self.date_to]:
            widget.setCalendarPopup(True)
            widget.setDisplayFormat('dd.MM.yyyy')
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.date_to.setDate(QDate.currentDate())
        filters.addWidget(self.from_on, 1, 2)
        filters.addWidget(self.date_from, 1, 3)
        filters.addWidget(self.to_on, 1, 4)
        filters.addWidget(self.date_to, 1, 5, 1, 2)
        filters.addWidget(QLabel(tr('Размер')), 2, 0)
        self.size_unit = QComboBox()
        self.size_unit.addItem(tr('КБ (1024 байта)'), 1024)
        self.size_unit.addItem(tr('МБ (1024 КБ)'), 1048576)
        filters.addWidget(self.size_unit, 2, 1)
        self.min_on, self.max_on = QCheckBox(tr('от')), QCheckBox(tr('до'))
        self.size_min, self.size_max = QDoubleSpinBox(), QDoubleSpinBox()
        for widget in [self.size_min, self.size_max]:
            widget.setRange(0, 1000000000)
            widget.setDecimals(3)
            widget.setGroupSeparatorShown(True)
        self.size_max.setValue(1536)
        filters.addWidget(self.min_on, 2, 2)
        filters.addWidget(self.size_min, 2, 3)
        filters.addWidget(self.max_on, 2, 4)
        filters.addWidget(self.size_max, 2, 5)
        self.state_filter = QComboBox()
        for title, state in [(tr('Любое состояние'), ''), (tr('Не проверены'), 'pending'), (tr('Готовы'), 'ready'), (tr('С ошибкой'), 'error')]:
            self.state_filter.addItem(title, state)
        filters.addWidget(self.state_filter, 2, 6)
        filters.setColumnStretch(3, 1)
        filters.setColumnStretch(5, 1)
        filters.setColumnStretch(6, 2)
        main.addLayout(filters)
        hint = QLabel(tr('Все включённые фильтры применяются одновременно. Даты включают весь выбранный день.'))
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        main.addWidget(hint)

        tools = QHBoxLayout()
        self.check_visible = QPushButton(tr('Отметить все по фильтру'))
        self.check_visible.clicked.connect(lambda: self.set_visible_checked(True))
        self.uncheck_visible = QPushButton(tr('Снять отметки по фильтру'))
        self.uncheck_visible.clicked.connect(lambda: self.set_visible_checked(False))
        self.reset_button = QPushButton(tr('Сбросить фильтры'))
        self.reset_button.clicked.connect(self.reset_filters)
        tools.addWidget(self.check_visible)
        tools.addWidget(self.uncheck_visible)
        tools.addWidget(self.reset_button)
        tools.addStretch()
        self.remove_button = QPushButton(tr('Убрать выделенные из списка'))
        self.remove_button.clicked.connect(self.remove_highlighted)
        tools.addWidget(self.remove_button)
        main.addLayout(tools)
        group_tools = QHBoxLayout()
        self.check_highlighted = QPushButton(tr('Отметить выделенные'))
        self.check_highlighted.clicked.connect(lambda: self.set_highlighted_checked(True))
        self.uncheck_highlighted = QPushButton(tr('Снять с выделенных'))
        self.uncheck_highlighted.clicked.connect(lambda: self.set_highlighted_checked(False))
        self.only_highlighted = QPushButton(tr('В работу — только выделенные'))
        self.only_highlighted.clicked.connect(self.use_only_highlighted)
        for control in [self.check_highlighted, self.uncheck_highlighted, self.only_highlighted]:
            group_tools.addWidget(control)
        self.highlight_count = QLabel()
        group_tools.addWidget(self.highlight_count, 1)
        main.addLayout(group_tools)
        self.message = QLabel('')
        self.message.setObjectName('muted')
        self.message.setWordWrap(True)
        main.addWidget(self.message)

        self.table = CatalogTable(0, 6)
        self.table.setHorizontalHeaderLabels([tr('В работу'), tr('Название файла'), tr('Дата изменения'), tr('Размер'), tr('Состояние'), tr('Папка')])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setWordWrap(False)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 105)
        self.table.setColumnWidth(4, 130)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        self.table.sortItems(1, Qt.SortOrder.AscendingOrder)
        self.table.itemChanged.connect(self.check_changed)
        self.table.cellDoubleClicked.connect(self.open_item)
        self.table.toggleRows.connect(self.toggle_highlighted)
        self.table.itemSelectionChanged.connect(self.update_highlighted)
        main.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        self.count = QLabel()
        self.count.setWordWrap(True)
        self.count.setObjectName('section')
        bottom.addWidget(self.count, 1)
        self.next_button = QPushButton(tr('К поиску и результатам'))
        self.next_button.setObjectName('primary')
        self.next_button.clicked.connect(self.continueRequested.emit)
        bottom.addWidget(self.next_button)
        main.addLayout(bottom)
        self.scope_note = QLabel()
        self.scope_note.setObjectName('muted')
        self.scope_note.setWordWrap(True)
        main.addWidget(self.scope_note)

        self.restore(settings)
        for field in [self.name_edit, self.path_edit]:
            field.textChanged.connect(self.refresh)
        for combo in [self.name_mode, self.date_source, self.size_unit, self.state_filter]:
            combo.currentIndexChanged.connect(self.refresh)
        for field in [self.date_from, self.date_to]:
            field.dateChanged.connect(self.refresh)
        for field in [self.size_min, self.size_max]:
            field.valueChanged.connect(self.refresh)
        for check in [self.from_on, self.to_on, self.min_on, self.max_on]:
            check.toggled.connect(self.refresh)
        self.recursive.toggled.connect(self.recursion_changed)
        self._restoring = False
        # Upgrade metadata for catalogs created by the earlier app version.
        old = [r['path'] for r in self.store.rows() if not r['created_ns'] and Path(r['path']).is_file()]
        if old:
            self.store.add_files(old)
        self.refresh()

    def restore(self, settings):
        settings = dict(settings)
        # One-time migration of the earlier creation-date default. Later explicit choices persist.
        if settings.get('date_preference_version', 0) < 2:
            settings['date_source'] = 'mtime_ns'
        for name in ['name', 'name_mode', 'date_source', 'state']:
            widget = {'name': self.name_edit, 'name_mode': self.name_mode,
                      'date_source': self.date_source, 'state': self.state_filter}[name]
            if name in settings:
                if isinstance(widget, QLineEdit):
                    widget.setText(settings[name])
                else:
                    widget.setCurrentIndex(max(0, widget.findData(settings[name])))
        for key, widget in [('date_from', self.date_from), ('date_to', self.date_to)]:
            day = QDate.fromString(settings.get(key, ''), 'yyyy-MM-dd')
            if day.isValid():
                widget.setDate(day)
        for key, widget in [('from_on', self.from_on), ('to_on', self.to_on), ('min_on', self.min_on), ('max_on', self.max_on)]:
            widget.setChecked(settings.get(key, False))
        self.size_unit.setCurrentIndex(max(0, self.size_unit.findData(settings.get('unit', 1024))))
        self.size_min.setValue(settings.get('min', 0))
        self.size_max.setValue(settings.get('max', 1536))

    def settings(self):
        return {'date_preference_version': 2, 'folder': self.root_path, 'recursive': self.recursive.isChecked(), 'name': self.name_edit.text(),
                'name_mode': self.name_mode.currentData(), 'date_source': self.date_source.currentData(),
                'state': self.state_filter.currentData(), 'date_from': self.date_from.date().toString('yyyy-MM-dd'),
                'date_to': self.date_to.date().toString('yyyy-MM-dd'), 'from_on': self.from_on.isChecked(),
                'to_on': self.to_on.isChecked(), 'min_on': self.min_on.isChecked(), 'max_on': self.max_on.isChecked(),
                'unit': self.size_unit.currentData(), 'min': self.size_min.value(), 'max': self.size_max.value()}

    def criteria(self):
        unit = self.size_unit.currentData()
        return FileFilter(folder=self.root_path, recursive=self.recursive.isChecked(), name=self.name_edit.text(),
            name_mode=self.name_mode.currentData(), date_source=self.date_source.currentData(),
            date_from=self.date_from.date().toPython() if self.from_on.isChecked() else None,
            date_to=self.date_to.date().toPython() if self.to_on.isChecked() else None,
            size_min=round(self.size_min.value() * unit) if self.min_on.isChecked() else None,
            size_max=round(self.size_max.value() * unit) if self.max_on.isChecked() else None,
            status=self.state_filter.currentData())

    def folder_pending(self):
        text = self.path_edit.text().strip().strip('"')
        return Path(text or '.') != Path(self.root_path or '.')

    def active_ids(self):
        if self.folder_pending() or self.criteria().error():
            return frozenset()
        return frozenset(r['id'] for r in self.visible_rows if r['selected'])

    def refresh(self, *_):
        if self._restoring:
            return
        for check, field in [(self.from_on, self.date_from), (self.to_on, self.date_to),
                             (self.min_on, self.size_min), (self.max_on, self.size_max)]:
            field.setEnabled(check.isChecked())
        criteria = self.criteria()
        all_rows = self.store.rows()
        self.visible_rows = [r for r in all_rows if criteria.includes(r)]
        highlighted = set(self.highlighted_ids())
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.visible_rows))
        self.table.horizontalHeaderItem(2).setText(tr('Дата создания') if criteria.date_source == 'created_ns' else tr('Дата изменения'))
        for index, row in enumerate(self.visible_rows):
            check = SortItem('', int(row['selected']))
            check.setData(Qt.ItemDataRole.UserRole, row['id'])
            check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if row['selected'] else Qt.CheckState.Unchecked)
            self.table.setItem(index, 0, check)
            path = Path(row['path'])
            cells = [(path.name, path.name.casefold()), (display_date(row[criteria.date_source]), row[criteria.date_source]),
                     (display_size(row['size']), row['size']), (STATES.get(row['status'], row['status']), row['status']),
                     (str(path.parent), str(path.parent).casefold())]
            for column, (text, value) in enumerate(cells, 1):
                item = SortItem(text, value)
                item.setToolTip(str(path) + (('\n' + row['error']) if row['error'] else '') +
                                (tr('\nТочный размер: {0} байт', row['size']) if column == 3 else ''))
                self.table.setItem(index, column, item)
                if row['id'] in highlighted:
                    item.setSelected(True)
            if row['id'] in highlighted:
                check.setSelected(True)
        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)
        ids = self.active_ids()
        size = sum(r['size'] for r in self.visible_rows if r['id'] in ids)
        self.count.setText(tr('Файлов к проверке: {0} · {1}\nПоказано по фильтру: {2} из {3}', len(ids), display_size(size), len(self.visible_rows), len(all_rows)))
        visible_ids = {r['id'] for r in self.visible_rows}
        hidden_checked = sum(bool(r['selected']) and r['id'] not in visible_ids for r in all_rows)
        self.scope_note.setText(tr('В работу попадут только отмеченные файлы, показанные по текущим фильтрам.') +
                               (tr(' Скрытых отмеченных файлов: {0}; они не будут обработаны.', hidden_checked) if hidden_checked else ''))
        error = criteria.error()
        self.message.setText(error or (tr('Папка изменена. Нажмите «Показать / обновить», чтобы загрузить её файлы.') if self.folder_pending() else
            tr('Shift + щелчок — диапазон; Ctrl + щелчок — отдельные строки; Ctrl + A — весь список. Затем нажмите кнопку над списком или пробел.')))
        self.next_button.setEnabled(bool(ids))
        self.check_visible.setEnabled(bool(self.visible_rows) and not self.folder_pending())
        self.uncheck_visible.setEnabled(bool(self.visible_rows) and not self.folder_pending())
        self.update_highlighted()
        self.selectionChanged.emit()

    def update_highlighted(self):
        count = len(self.highlighted_ids())
        for control in [self.check_highlighted, self.uncheck_highlighted, self.only_highlighted]:
            control.setEnabled(bool(count) and not self.folder_pending())
        self.highlight_count.setText(tr('Выделено строк: {0}', count))

    def set_highlighted_checked(self, checked):
        self.store.set_selected(self.highlighted_ids(), checked)
        self.refresh()

    def use_only_highlighted(self):
        ids = self.highlighted_ids()
        if not ids:
            return
        self.store.set_selected([r['id'] for r in self.visible_rows], False)
        self.store.set_selected(ids, True)
        self.refresh()

    def highlighted_ids(self):
        return [self.table.item(i.row(), 0).data(Qt.ItemDataRole.UserRole)
                for i in self.table.selectionModel().selectedRows() if self.table.item(i.row(), 0)]

    def check_changed(self, item):
        if item.column() != 0:
            return
        self.store.set_selected([item.data(Qt.ItemDataRole.UserRole)], item.checkState() == Qt.CheckState.Checked)
        self.refresh()

    def set_visible_checked(self, checked):
        self.store.set_selected([r['id'] for r in self.visible_rows], checked)
        self.refresh()

    def toggle_highlighted(self):
        ids = self.highlighted_ids()
        rows = self.store.rows(ids)
        self.store.set_selected(ids, not all(r['selected'] for r in rows))
        self.refresh()

    def open_item(self, row, column):
        if column:
            self.openRecording.emit(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))

    def remove_highlighted(self):
        self.store.remove(self.highlighted_ids())
        self.refresh()

    def reset_filters(self):
        self._restoring = True
        self.name_edit.clear()
        self.name_mode.setCurrentIndex(0)
        self.date_source.setCurrentIndex(0)
        self.state_filter.setCurrentIndex(0)
        for check in [self.from_on, self.to_on, self.min_on, self.max_on]:
            check.setChecked(False)
        self._restoring = False
        self.refresh()

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr('Папка с записями'), self.root_path)
        if folder:
            self.path_edit.setText(folder)
            self.load_folder()

    def is_scanning(self):
        return self.scan_worker is not None and self.scan_worker.isRunning()

    def recursion_changed(self):
        if self.root_path and not self.folder_pending():
            self.load_folder()
        else:
            self.refresh()

    def load_folder(self):
        if self.is_scanning():
            return
        path = Path(self.path_edit.text().strip().strip('"')).expanduser()
        if not self.path_edit.text().strip() or not path.is_dir():
            self.message.setText(tr('Папка не найдена. Выберите существующую папку или исправьте путь.'))
            return
        folder = str(path.resolve())
        self.path_edit.setText(folder)
        self.message.setText(tr('Загружаем список файлов…'))
        self.scan_worker = ScanWorker(self.db, folder, self.recursive.isChecked())
        self.scan_worker.completed.connect(self.scan_complete)
        self.scan_worker.finished.connect(lambda: self.loadingChanged.emit(False))
        self.loadingChanged.emit(True)
        self.scan_worker.start()

    def scan_complete(self, result):
        if result.get('folder'):
            self.root_path = result['folder']
            self.refresh()
            self.message.setText(tr('Список обновлён. Новых файлов: {0}; изменённых: {1}.', result['added'], result['changed']))
        if result.get('errors'):
            QMessageBox.warning(self, tr('Некоторые файлы недоступны'), '\n'.join(result['errors'][:12]))

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr('Записи для проверки'), self.root_path,
                    tr('Аудиозаписи (*.mp3 *.wav *.m4a *.ogg *.flac *.mp4 *.wma *.aac)'))
        if paths:
            self.store.add_files(paths)
            self.show_all()

    def show_all(self):
        self.root_path = ''
        self.path_edit.clear()
        self.refresh()
