"""Decode locally to mono float32, with no PyTorch or transcription model imports."""
import av
import numpy as np


def decode_audio(path, sample_rate=16000):
    frames = []
    resampler = av.AudioResampler(format='fltp', layout='mono', rate=sample_rate)
    with av.open(str(path), metadata_errors='ignore') as source:
        for frame in source.decode(audio=0):
            for out in resampler.resample(frame):
                frames.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            frames.append(out.to_ndarray().reshape(-1))
    return np.concatenate(frames).astype(np.float32, copy=False) if frames else np.zeros(0, np.float32)


def audio_chunks(audio, seconds=20, overlap=1):
    """Overlap allows speech crossing a cut to be recovered, without dropping quiet speech."""
    size, stride = int(seconds*16000), int((seconds-overlap)*16000)
    for start in range(0, len(audio), stride):
        chunk = audio[start:start+size]
        yield start/16000, chunk
        if start + size >= len(audio):
            break
