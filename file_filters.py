from i18n import tr
"""Pure file-catalog filtering; dates are Windows file dates, never inferred call dates."""
from dataclasses import dataclass
from datetime import date, datetime
from fnmatch import fnmatchcase
from pathlib import Path


@dataclass
class FileFilter:
    folder: str = ''
    recursive: bool = True
    name: str = ''
    name_mode: str = 'contains'
    date_source: str = 'mtime_ns'
    date_from: date | None = None
    date_to: date | None = None
    size_min: int | None = None
    size_max: int | None = None
    status: str = ''

    def description(self):
        parts = [tr('Папка: {0}', self.folder) if self.folder else tr('Все добавленные папки')]
        if self.name.strip():
            mode = {'contains': tr('Имя содержит'), 'exact': tr('Имя'), 'starts': tr('Имя начинается с'),
                    'wildcard': tr('Шаблон имени')}[self.name_mode]
            parts.append(f'{mode}: «{self.name.strip()}»')
        day = tr('Дата создания') if self.date_source == 'created_ns' else tr('Дата изменения')
        bounds = []
        if self.date_from:
            bounds.append(tr('с ') + self.date_from.strftime('%d.%m.%Y'))
        if self.date_to:
            bounds.append(tr('по ') + self.date_to.strftime('%d.%m.%Y'))
        parts.append(day + ': ' + (' '.join(bounds) if bounds else tr('весь период')))
        if self.size_min is not None:
            parts.append(tr('Размер от ') + display_size(self.size_min))
        if self.size_max is not None:
            parts.append(tr('Размер до ') + display_size(self.size_max))
        if self.status:
            parts.append(tr('Состояние: ') + {'pending':tr('не проверены'),'ready':tr('готовы'),'error':tr('с ошибкой'),'running':tr('обрабатываются')}.get(self.status,self.status))
        return ' · '.join(parts)

    def error(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            return tr('Начало периода позже окончания. Исправьте диапазон дат.')
        if self.size_min is not None and self.size_max is not None and self.size_min > self.size_max:
            return tr('Минимальный размер больше максимального. Исправьте диапазон размеров.')
        return ''

    def includes(self, row):
        if self.error():
            return False
        path = Path(row['path'])
        if self.folder:
            root = Path(self.folder)
            if self.recursive:
                if not path.is_relative_to(root):
                    return False
            elif path.parent != root:
                return False
        needles = [x.strip().casefold() for x in self.name.split(';') if x.strip()]
        if needles:
            name = path.name.casefold()
            predicates = {'contains': lambda needle: needle in name,
                          'exact': lambda needle: name == needle,
                          'starts': lambda needle: name.startswith(needle),
                          'wildcard': lambda needle: fnmatchcase(name, needle)}
            if not any(predicates[self.name_mode](needle) for needle in needles):
                return False
        if self.date_from or self.date_to:
            ns = row[self.date_source]
            if not ns:
                return False
            day = datetime.fromtimestamp(ns / 1e9).date()
            if self.date_from and day < self.date_from:
                return False
            if self.date_to and day > self.date_to:
                return False
        if self.size_min is not None and row['size'] < self.size_min:
            return False
        if self.size_max is not None and row['size'] > self.size_max:
            return False
        if self.status and row['status'] != self.status:
            return False
        return True


def display_size(value):
    if value >= 1024 * 1024:
        return tr('{0:.2f} МБ', value / (1024 * 1024)).replace('.', ',')
    if value >= 1024:
        return tr('{0:.1f} КБ', value / 1024).replace('.', ',')
    return tr('{0} Б', value)


def display_date(ns):
    return datetime.fromtimestamp(ns / 1e9).strftime('%d.%m.%Y %H:%M') if ns else tr('Нет даты')
