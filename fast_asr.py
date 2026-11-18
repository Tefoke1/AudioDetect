from i18n import tr
"""Russian CTC recognition on DirectML/CPU with bounded, overlapping audio windows."""
from pathlib import Path
import re
from types import SimpleNamespace
import numpy as np
import onnx_asr
import onnxruntime as ort

from audio_io import decode_audio, audio_chunks
from gigaam_assets import ensure_fast_assets
from performance import cpu_threads


def timestamped_words(result, offset, duration):
    chars, times, probabilities = [], [], []
    for token, stamp, probability in zip(result.tokens or [], result.timestamps or [], result.logprobs or []):
        token = token.replace('▁', ' ')
        chars.extend(token)
        times.extend([min(duration, max(0, offset + stamp))] * len(token))
        probabilities.extend([float(probability)] * len(token))
    text = ''.join(chars)
    words = []
    for match in re.finditer(r'\S+', text):
        start, last = times[match.start()], times[match.end()-1]
        if start >= duration:
            continue
        words.append(SimpleNamespace(word=match.group(), start=start, end=min(duration, last+.04),
            uncertain=min(probabilities[match.start():match.end()]) < -2.5))
    return words


def words_to_parts(words):
    group = []
    def make_part(items):
        # Punctuation is only used to separate readable units; the spoken words stay intact.
        text = ' '.join(w.word for w in items)
        text = text[:1].upper() + text[1:]
        uncertain = any(w.uncertain for w in items)
        return SimpleNamespace(start=items[0].start, end=items[-1].end, text=text,
            avg_logprob=-1.0 if uncertain else -0.2, no_speech_prob=0.0, words=None)
    for index, word in enumerate(words):
        phrase = ' '.join(w.word.casefold() for w in words[index:index+3])
        topic_change = phrase in ('в одном доме', 'в другом доме', 'теперь другой объект')
        if group and (topic_change or word.start-group[-1].end > .6 or word.end-group[0].start > 8 or len(group) >= 30):
            yield make_part(group)
            group=[]
        group.append(word)
    if group:
        yield make_part(group)


class FastRussianModel:
    def __init__(self, model_dir):
        options = ort.SessionOptions()
        options.intra_op_num_threads = cpu_threads()
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        gpu = 'DmlExecutionProvider' in ort.get_available_providers()
        providers = ['CPUExecutionProvider']
        if gpu:
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            providers = [('DmlExecutionProvider', {'device_id': 0}), 'CPUExecutionProvider']
            options.intra_op_num_threads = 4
        self.backend = tr('Radeon / DirectML + процессор') if gpu else tr('Процессор · GigaAM int8')
        folder = ensure_fast_assets(model_dir, gpu)
        try:
            self.model = onnx_asr.load_model('gigaam-v3-ctc', path=folder,
                quantization=None if gpu else 'int8', sess_options=options, providers=providers).with_timestamps()
        except Exception:
            if not gpu:
                raise
            # A missing/unsupported graphics driver must not prevent local recognition.
            folder = ensure_fast_assets(model_dir, False)
            options = ort.SessionOptions()
            options.intra_op_num_threads = cpu_threads()
            options.inter_op_num_threads = 1
            options.log_severity_level = 3
            self.model = onnx_asr.load_model('gigaam-v3-ctc', path=folder,
                quantization='int8', sess_options=options, providers=['CPUExecutionProvider']).with_timestamps()
            self.backend = tr('Процессор · GigaAM int8 (ускорение видеокартой недоступно)')

    def transcribe(self, path, **kwargs):
        audio = decode_audio(path)
        duration = len(audio)/16000
        def generate():
            windows = list(audio_chunks(audio, seconds=20, overlap=2))
            pending = []
            for index, (offset, chunk) in enumerate(windows):
                # A fixed shape reuses GPU kernels; padding is excluded from timestamps and results.
                samples = np.pad(chunk, (0, 320000-len(chunk)))
                result = self.model.recognize(samples, sample_rate=16000)
                lo = offset + (1 if index else 0)
                hi = offset + 19 if index < len(windows)-1 else duration + .001
                words = [w for w in timestamped_words(result, offset, duration)
                         if lo <= (w.start+w.end)/2 < hi]
                # Protect the cut against small timestamp differences in the overlapping context.
                for word in words:
                    if pending and offset > 0 and word.start < offset+2 and word.word.casefold() == pending[-1].word.casefold() and word.start < pending[-1].end:
                        continue
                    pending.append(word)
                # Keep a final short unit so an address split across windows stays together.
                parts = list(words_to_parts(pending))
                if index < len(windows)-1 and parts:
                    for part in parts[:-1]:
                        yield part
                    pending = [w for w in pending if w.start >= parts[-1].start]
                else:
                    yield from parts
                    pending=[]
        return generate(), SimpleNamespace(duration=duration)
