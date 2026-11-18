"""Local transcript storage, Russian address search, and exports."""
from __future__ import annotations
from i18n import tr
import i18n

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import shutil
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache

SUPPORTED = {'.mp3', '.wav', '.m4a', '.ogg', '.flac', '.mp4', '.wma', '.aac'}


@dataclass
class Segment:
    start: float
    end: float
    text: str
    uncertain: bool = False


@dataclass
class Match:
    recording_id: int
    path: str
    start: float
    end: float
    text: str
    context: str
    kind: str
    uncertain: bool
    first_segment: int
    last_segment: int
    summary: str = ''
    analysis_state: str = 'pending'


ANALYSIS_VERSION = 'qwen3-grounded-discussion-v8-general'


def analysis_key(query, fuzzy, search_mode='phrase', keyword_rule='all'):
    key = [ANALYSIS_VERSION, query.strip().casefold().replace('ё', 'е'), bool(fuzzy)]
    if search_mode == 'keywords':
        key += [search_mode, keyword_rule]
    key += [i18n.LANGUAGE]
    return json.dumps(key, ensure_ascii=False)


def transcript_hash(segments):
    data = [[float(s.start), float(s.end), s.text, bool(s.uncertain)] for s in segments]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode('utf-8')).hexdigest()


def timecode(seconds: float, millis: bool = False) -> str:
    value = max(0, round(seconds * 1000))
    hours, value = divmod(value, 3600000)
    minutes, value = divmod(value, 60000)
    secs, ms = divmod(value, 1000)
    base = f'{hours:02}:{minutes:02}:{secs:02}' if hours else f'{minutes:02}:{secs:02}'
    return f'{base}.{ms:03}' if millis else base


class Store:
    def __init__(self, db: Path):
        db.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self._search_cache = {}
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
                size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', model TEXT NOT NULL DEFAULT '',
                duration REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS segments (
                recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
                text TEXT NOT NULL, uncertain INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (recording_id, position));
            CREATE TABLE IF NOT EXISTS analysis_results (
                recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                query_key TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (recording_id, query_key));
        ''')
        columns = {r['name'] for r in self.conn.execute('PRAGMA table_info(recordings)')}
        with self.conn:
            if 'created_ns' not in columns:
                self.conn.execute('ALTER TABLE recordings ADD COLUMN created_ns INTEGER NOT NULL DEFAULT 0')
            if 'selected' not in columns:
                self.conn.execute('ALTER TABLE recordings ADD COLUMN selected INTEGER NOT NULL DEFAULT 1')
            if 'revision' not in columns:
                self.conn.execute('ALTER TABLE recordings ADD COLUMN revision INTEGER NOT NULL DEFAULT 0')

    def close(self):
        self.conn.close()

    def recover(self):
        with self.conn:
            self.conn.execute("UPDATE recordings SET status='pending' WHERE status='running'")

    def add_files(self, paths):
        added = changed = 0
        errors = []
        with self.conn:
            for raw in paths:
                path = Path(raw).resolve()
                if path.suffix.lower() not in SUPPORTED:
                    continue
                try:
                    stat = path.stat()
                    if not path.is_file():
                        continue
                except OSError as exc:
                    errors.append(f'{path.name}: {exc}')
                    continue
                old = self.conn.execute('SELECT * FROM recordings WHERE path=?', (str(path),)).fetchone()
                created_ns = getattr(stat, 'st_birthtime_ns', stat.st_ctime_ns)
                if old is None:
                    self.conn.execute('INSERT INTO recordings(path,size,mtime_ns,created_ns) VALUES (?,?,?,?)',
                                      (str(path), stat.st_size, stat.st_mtime_ns, created_ns))
                    added += 1
                elif (old['size'], old['mtime_ns']) != (stat.st_size, stat.st_mtime_ns):
                    self.conn.execute("UPDATE recordings SET size=?,mtime_ns=?,status='pending',error='',model='' WHERE id=?",
                                      (stat.st_size, stat.st_mtime_ns, old['id']))
                    self.conn.execute('DELETE FROM segments WHERE recording_id=?', (old['id'],))
                    self.conn.execute('DELETE FROM analysis_results WHERE recording_id=?', (old['id'],))
                    changed += 1
                if old is not None and old['created_ns'] != created_ns:
                    self.conn.execute('UPDATE recordings SET created_ns=? WHERE id=?', (created_ns, old['id']))
        return added, changed, errors

    def rows(self, recording_ids=None):
        if recording_ids is not None:
            ids = tuple(set(recording_ids))
            if not ids:
                return []
            placeholders = ','.join('?' for _ in ids)
            return list(self.conn.execute(f'SELECT * FROM recordings WHERE id IN ({placeholders}) ORDER BY path COLLATE NOCASE', ids))
        return list(self.conn.execute('SELECT * FROM recordings ORDER BY path COLLATE NOCASE'))

    def set_selected(self, ids, selected):
        with self.conn:
            self.conn.executemany('UPDATE recordings SET selected=? WHERE id=?', [(int(selected), rid) for rid in ids])

    def row(self, rid):
        return self.conn.execute('SELECT * FROM recordings WHERE id=?', (rid,)).fetchone()

    def segments(self, rid):
        return [Segment(r['start'], r['end'], r['text'], bool(r['uncertain'])) for r in
                self.conn.execute('SELECT * FROM segments WHERE recording_id=? ORDER BY position', (rid,))]

    def state(self, rid, status, error=''):
        with self.conn:
            self.conn.execute('UPDATE recordings SET status=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                              (status, error, rid))

    def save(self, rid, model, duration, segments):
        # Replace only after the entire recording has been decoded successfully.
        with self.conn:
            self.conn.execute('DELETE FROM segments WHERE recording_id=?', (rid,))
            self.conn.execute('DELETE FROM analysis_results WHERE recording_id=?', (rid,))
            self.conn.executemany('INSERT INTO segments VALUES (?,?,?,?,?,?)',
                                 [(rid, i, s.start, s.end, s.text, int(s.uncertain)) for i, s in enumerate(segments)])
            self.conn.execute("UPDATE recordings SET status='ready',model=?,duration=?,error='',updated_at=CURRENT_TIMESTAMP,revision=revision+1 WHERE id=?",
                              (model, duration, rid))

    def pending(self, model, recording_ids=None):
        return [r for r in self.rows(recording_ids) if r['status'] != 'ready' or r['model'] != model]

    def analysis(self, rid, query, fuzzy, segments, search_mode='phrase', keyword_rule='all'):
        row = self.conn.execute('SELECT payload FROM analysis_results WHERE recording_id=? AND query_key=? AND fingerprint=?',
                                (rid, analysis_key(query, fuzzy, search_mode, keyword_rule), transcript_hash(segments))).fetchone()
        return json.loads(row['payload']) if row else None

    def save_analysis(self, rid, query, fuzzy, segments, matches, error='', search_mode='phrase', keyword_rule='all'):
        from dataclasses import asdict
        payload = {'matches': [asdict(m) for m in matches], 'error': error}
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO analysis_results VALUES (?,?,?,?)',
                              (rid, analysis_key(query, fuzzy, search_mode, keyword_rule), transcript_hash(segments),
                               json.dumps(payload, ensure_ascii=False)))
            self.conn.execute('UPDATE recordings SET revision=revision+1 WHERE id=?', (rid,))

    def remove(self, ids):
        with self.conn:
            self.conn.executemany('DELETE FROM recordings WHERE id=?', [(i,) for i in ids])


def scan_folder(folder, recursive=True, cancelled=None):
    files, errors = [], []
    def onerror(exc):
        errors.append(str(exc))
    for parent, dirs, names in os.walk(folder, followlinks=False, onerror=onerror):
        if cancelled is not None and cancelled.is_set():
            break
        dirs[:] = [d for d in dirs if not Path(parent, d).is_symlink()]
        if not recursive:
            dirs.clear()
        for name in names:
            p = Path(parent, name)
            if p.suffix.lower() in SUPPORTED and not p.is_symlink():
                files.append(p)
    return sorted(files), errors


NUMBERS = dict(zip(
    'ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать'.split(),
    range(20)))
NUMBERS.update({'одна': 1, 'одно': 1, 'две': 2, 'двадцать': 20, 'тридцать': 30, 'сорок': 40,
                'пятьдесят': 50, 'шестьдесят': 60, 'семьдесят': 70, 'восемьдесят': 80, 'девяносто': 90,
                'сто': 100, 'двести': 200, 'триста': 300, 'четыреста': 400, 'пятьсот': 500,
                'шестьсот': 600, 'семьсот': 700, 'восемьсот': 800, 'девятьсот': 900})
ORDINALS = {'первый': 1, 'первом': 1, 'первого': 1, 'второй': 2, 'втором': 2, 'второго': 2,
            'третий': 3, 'третьем': 3, 'третьего': 3, 'четвертый': 4, 'четвертом': 4,
            'пятый': 5, 'пятом': 5, 'пятого': 5, 'шестой': 6, 'шестом': 6,
            'седьмой': 7, 'седьмом': 7, 'восьмой': 8, 'восьмом': 8,
            'девятый': 9, 'девятом': 9, 'десятый': 10, 'десятом': 10}
STOP = {'на', tr('по'), 'в', 'во', tr('с'), 'со', 'к', 'ко', 'и', 'а', 'это', 'у', 'из', tr('от'),
        'улица', 'улице', 'улицы', 'улицу', 'ул', 'дом', 'дома', 'доме', 'д', 'номер', 'номера', 'адрес', 'адресу'}
SUFFIXES = ('ского', 'скому', 'скими', 'скими', 'ской', 'ская', 'ское', 'ский', 'ском', 'скую',
            'ого', 'ому', 'ыми', 'ими', 'ая', 'ой', 'ые', 'ый', 'ое', 'ую', 'ий', 'ом', 'им', 'ым')


def tokens(text: str, keep_stop=False) -> list[str]:
    text = text.casefold().replace('ё', 'е')
    # Preserve numeric boundaries: 5 must not become a match for 25, 5А, or 5/1.
    raw = re.findall(r'\d+(?:[/\-]\d+)*(?:-?[а-яa-z](?![а-яa-z]))?|[а-яa-z]+', text)
    raw = [re.sub(r'(?<=\d)-(?=[а-яa-z]$)', '', t) for t in raw]
    result = []
    i = 0
    while i < len(raw):
        token = raw[i]
        if token in NUMBERS:
            value = NUMBERS[token]
            last = value
            i += 1
            while i < len(raw) and raw[i] in NUMBERS:
                nxt = NUMBERS[raw[i]]
                if (last >= 100 and 0 < nxt < 100) or (20 <= last < 100 and last % 10 == 0 and 0 < nxt < 10):
                    value += nxt
                    last = nxt
                    i += 1
                else:
                    break
            result.append(str(value))
            continue
        if token in ORDINALS:
            token = str(ORDINALS[token])
        if keep_stop or token not in STOP:
            result.append(token)
        i += 1
    # Spoken letter suffix: "дом пять а". Do not join common conjunctions globally.
    return result


@lru_cache(maxsize=32768)
def stem(token):
    if any(c.isdigit() for c in token):
        return token
    for suffix in SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    return token


@lru_cache(maxsize=65536)
def token_equal(a, b, fuzzy=False):
    if a == b or stem(a) == stem(b):
        return True, False
    # Never use approximate matching for a house number.
    if fuzzy and not any(c.isdigit() for c in a + b) and min(len(a), len(b)) >= 5:
        if SequenceMatcher(None, stem(a), stem(b)).ratio() >= 0.80:
            return True, True
        # Unstressed vowels are a common ASR spelling error in long Russian street names.
        if min(len(a), len(b)) >= 8:
            sound = str.maketrans({'о': 'а', 'е': 'и', 'ё': 'и', 'ы': 'и'})
            if stem(a).translate(sound) == stem(b).translate(sound):
                return True, True
    return False, False


def match_tokens(needles, haystack, fuzzy=False):
    """Ordered terms within a short phrase, with at most 3 intervening tokens each."""
    for start in range(len(haystack)):
        ok, approximate = token_equal(needles[0], haystack[start], fuzzy)
        if not ok:
            continue
        pos = start
        for needle in needles[1:]:
            found = False
            for nextpos in range(pos + 1, min(len(haystack), pos + 5)):
                ok, approx = token_equal(needle, haystack[nextpos], fuzzy)
                if ok:
                    pos = nextpos
                    approximate |= approx
                    found = True
                    break
                # Do not skip a different house number to reach a later apartment/quantity.
                if any(c.isdigit() for c in needle) and any(c.isdigit() for c in haystack[nextpos]):
                    break
            if not found:
                break
        else:
            return True, approximate
    return False, False


# Case endings for keyword matching. This does not claim full semantic synonym matching.
KEYWORD_ENDINGS = tuple(sorted(set(SUFFIXES + (
    'иями', 'ами', 'ями', 'его', 'ему', 'ией', 'иям', 'иях', 'ия', 'ие',
    'ов', 'ев', 'ей', 'ах', 'ях', 'ам', 'ям', 'ем', 'ою', 'ею',
    'а', 'я', 'у', 'ю', 'ы', 'и', 'е', 'о')), key=lambda x: -len(x)))


@lru_cache(maxsize=32768)
def keyword_stem(word):
    if any(c.isdigit() for c in word):
        return word
    for ending in KEYWORD_ENDINGS:
        if word.endswith(ending) and len(word)-len(ending) >= 3:
            return word[:-len(ending)]
    return word


@lru_cache(maxsize=65536)
def keyword_equal(query, word, fuzzy=False):
    if any(c.isdigit() for c in query+word):
        return (query == word, False)
    a, b = keyword_stem(query), keyword_stem(word)
    if a == b or (min(len(a), len(b)) >= 5 and (a+'н' == b or b+'н' == a)):
        return True, False
    return token_equal(query, word, fuzzy)


def search_keywords(rid, path, segments, query, fuzzy=True, rule='all'):
    """AND/OR across one entire recording; return only source-backed occurrence spans."""
    if rule not in ('all', 'any'):
        raise ValueError('Неизвестное правило поиска ключевых слов.')
    needles = list(dict.fromkeys(tokens(query, keep_stop=True)))
    if not needles:
        return []
    occurrences, present = [], set()
    for i, segment in enumerate(segments):
        words = set(tokens(segment.text, keep_stop=True))
        local, approximate = [], False
        for needle in needles:
            comparisons = [keyword_equal(needle, word, fuzzy) for word in words]
            if any(ok for ok, _ in comparisons):
                local.append(needle)
                approximate |= not any(ok and not approx for ok, approx in comparisons)
        if local:
            present.update(local)
            occurrences.append((i, local, approximate))
    if not present or (rule == 'all' and len(present) != len(needles)):
        return []
    found = []
    for i, local, approximate in occurrences:
        segment = segments[i]
        lo, hi = max(0, i-1), min(len(segments), i+2)
        found.append(Match(rid, str(path), segment.start, segment.end, segment.text,
            ' '.join(s.text for s in segments[lo:hi]),
            (tr('Похожие ключевые слова: ') if approximate else tr('Ключевые слова: ')) + ', '.join(local),
            segment.uncertain, i, i))
    return found


def search_segments(rid, path, segments, query, fuzzy=True, search_mode='phrase', keyword_rule='all'):
    """Search alternatives separated by ';' over up to 3 nearby speech segments."""
    if search_mode == 'keywords':
        return search_keywords(rid, path, segments, query, fuzzy, keyword_rule)
    alternatives = [tokens(q) for q in query.split(';') if tokens(q)]
    # In a spoken address the house number may precede the street name.
    alternatives += [list(reversed(q)) for q in alternatives[:]
                     if len(q) == 2 and sum(any(c.isdigit() for c in t) for t in q) == 1]
    if not alternatives:
        return []
    found = []
    for i in range(len(segments)):
        for j in range(i, min(i + 3, len(segments))):
            if j > i and (segments[j].start - segments[j - 1].end > 8 or segments[j].end - segments[i].start > 45):
                break
            excerpt = ' '.join(s.text.strip() for s in segments[i:j + 1])
            matches = [match_tokens(q, tokens(excerpt), fuzzy) for q in alternatives]
            exact = any(ok and not approx for ok, approx in matches)
            if not any(ok for ok, _ in matches):
                continue
            # Prefer the tightest window; a later one-segment hit replaces its wider parent.
            if found and found[-1].last_segment >= i:
                if j == found[-1].last_segment and i > found[-1].first_segment:
                    found.pop()
                else:
                    break
            lo, hi = max(0, i - 1), min(len(segments), j + 2)
            found.append(Match(rid, str(path), segments[i].start, segments[j].end, excerpt,
                               ' '.join(s.text.strip() for s in segments[lo:hi]),
                               tr('По словам') if exact else tr('Похожее написание'),
                               any(s.uncertain for s in segments[i:j + 1]), i, j))
            break
    return found


def search_store(store, query, fuzzy=True, discussions=False, recording_ids=None, search_mode='phrase', keyword_rule='all'):
    matches = []
    for r in store.rows(recording_ids):
        if r['status'] == 'ready':
            key = (r['id'], r['path'], r['revision'], r['model'], r['size'], r['mtime_ns'], query, fuzzy, discussions, ANALYSIS_VERSION, search_mode, keyword_rule, i18n.LANGUAGE)
            if key in store._search_cache:
                matches.extend(store._search_cache[key])
                continue
            segments = store.segments(r['id'])
            cached = store.analysis(r['id'], query, fuzzy, segments, search_mode, keyword_rule) if discussions else None
            if cached is not None:
                found = [Match(**m) for m in cached['matches']]
            else:
                found = search_segments(r['id'], r['path'], segments, query, fuzzy, search_mode, keyword_rule)
            store._search_cache[key] = found
            if len(store._search_cache) > 2048:
                store._search_cache.pop(next(iter(store._search_cache)))
            matches.extend(found)
    return matches


def spreadsheet_safe(text):
    text = str(text)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


def export_csv(path, matches):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([tr('Файл'), tr('Время в записи'), tr('Фрагмент разговора'), tr('Кратко, что обсуждали')])
        for m in matches:
            summary = m.summary or tr('Продолжение и краткое описание ещё не проанализированы.')
            if m.analysis_state == 'review':
                summary = tr('[Проверить связь с запросом] ') + summary
            writer.writerow([spreadsheet_safe(v) for v in [m.path,
                            timecode(m.start, True) + ' — ' + timecode(m.end, True), m.text, summary]])


def copy_recordings(matches, destination):
    copied, failed = [], []
    for source in dict.fromkeys(m.path for m in matches):
        path = Path(source)
        target = Path(destination) / path.name
        number = 2
        while target.exists():
            target = Path(destination) / f'{path.stem} ({number}){path.suffix}'
            number += 1
        created = False
        try:
            with path.open('rb') as src, target.open('xb') as dst:
                created = True
                shutil.copyfileobj(src, dst)
            copied.append(target)
        except OSError as exc:
            if created:
                try:
                    target.unlink()
                except OSError:
                    pass
            failed.append(f'{path.name}: {exc}')
    return copied, failed


def transcript_text(row, segments):
    lines = [Path(row['path']).name, row['path'], f"Модель: {row['model']}",
             'Автоматическая расшифровка. Знак [?] означает: стоит проверить на слух.', '']
    lines += [f'[{timecode(s.start, True)} — {timecode(s.end, True)}] {"[?] " if s.uncertain else ""}{s.text.strip()}' for s in segments]
    if not segments:
        lines.append('Речь не обнаружена.')
    return '\n'.join(lines)


def load_settings(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_settings(path, data):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
