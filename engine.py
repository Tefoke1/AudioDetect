"""Local-only audio processing. Network is used only to download model weights."""
from __future__ import annotations
from i18n import tr
import os
from pathlib import Path
import threading
import wave

os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')

from core import Segment, Store
from performance import cpu_threads


def speech_segments(part):
    uncertain = part.avg_logprob < -0.8 or part.no_speech_prob > 0.6
    words = getattr(part, 'words', None)
    if not words:
        return [Segment(float(part.start), float(part.end), part.text.strip(), uncertain)] if part.text.strip() else []
    result, current = [], []
    for word in words:
        current.append(word)
        if word.word.rstrip().endswith(('.', '!', '?', ';')):
            result.append(Segment(float(current[0].start), float(current[-1].end),
                                  ''.join(w.word for w in current).strip(), uncertain))
            current = []
    if current:
        result.append(Segment(float(current[0].start), float(current[-1].end),
                              ''.join(w.word for w in current).strip(), uncertain))
    return result


def load_model(name, model_dir):
    if name == 'gigaam-v3-ctc':
        from fast_asr import FastRussianModel
        return FastRussianModel(model_dir)
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    from huggingface_hub.errors import LocalEntryNotFoundError
    try:
        model_path = download_model(name, cache_dir=str(model_dir), local_files_only=True)
    except LocalEntryNotFoundError:
        model_path = download_model(name, cache_dir=str(model_dir))
    if not all((Path(model_path) / part).is_file() for part in ['model.bin', 'config.json', 'tokenizer.json']):
        # A previous download may have stopped after metadata but before the weights.
        model_path = download_model(name, cache_dir=str(model_dir))
    return WhisperModel(model_path, device='cpu', compute_type='int8',
                        cpu_threads=cpu_threads(), num_workers=1,
                        local_files_only=True)


def transcribe_batch(db, model_dir, model_name, cancelled, progress, file_done, model_factory=load_model, recording_ids=None):
    store = Store(Path(db))
    active = None
    ok = failed = 0
    try:
        # Recheck modified and removed inputs before using cached transcripts.
        rows = store.rows(recording_ids)
        store.add_files([r['path'] for r in rows if Path(r['path']).is_file()])
        for r in rows:
            if not Path(r['path']).is_file():
                store.state(r['id'], 'error', tr('Исходный файл не найден. Верните его на место или добавьте заново.'))
        jobs = store.pending(model_name, recording_ids)
        total = len(jobs)
        if not jobs:
            return {'ok': 0, 'failed': 0, 'stopped': False}
        progress(0, total, tr('Подготовка распознавания. При первом запуске скачивается модель…'), 0)
        model = model_factory(model_name, Path(model_dir))
        if getattr(model, 'backend', None):
            progress(0, total, tr('Распознавание: {0}', model.backend), 0)
        for index, row in enumerate(jobs):
            if cancelled.is_set():
                break
            active = row['id']
            store.state(active, 'running')
            name = Path(row['path']).name
            progress(index, total, tr('Обработка: {0}', name), 0)
            try:
                before = Path(row['path']).stat()
                parts, info = model.transcribe(row['path'], language=None, beam_size=5,
                                              vad_filter=True, condition_on_previous_text=False,
                                              word_timestamps=True)
                segments = []
                for part in parts:
                    if cancelled.is_set():
                        break
                    segments.extend(speech_segments(part))
                    progress(index, total, tr('Обработка: {0}', name),
                             min(99, round(100 * part.end / max(info.duration, 1))))
                if cancelled.is_set():
                    store.state(active, 'pending')
                    break
                after = Path(row['path']).stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError(tr('Файл изменился во время обработки. Запустите проверку снова.'))
                store.save(active, model_name, float(info.duration), segments)
                ok += 1
            except Exception as exc:
                store.state(active, 'error', str(exc))
                failed += 1
            active = None
            file_done()
            progress(index + 1, total, tr('Проверено {0} из {1}', index + 1, total), 0)
        return {'ok': ok, 'failed': failed, 'stopped': cancelled.is_set()}
    finally:
        if active is not None:
            store.state(active, 'pending')
        store.close()


def make_preview(source, start, end, destination):
    from faster_whisper.audio import decode_audio
    import numpy as np
    audio = decode_audio(str(source), sampling_rate=16000)
    lo = max(0, int(start * 16000))
    hi = min(len(audio), int(end * 16000))
    if hi <= lo:
        raise ValueError(tr('В этом месте записи нет звука.'))
    samples = (np.clip(audio[lo:hi], -1, 1) * 32767).astype('<i2')
    with wave.open(str(destination), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(samples.tobytes())
    return Path(destination)
