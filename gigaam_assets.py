from i18n import tr
"""Pinned, resumable downloads for local Russian recognition."""
from pathlib import Path
import threading
from semantic_assets import download

REVISION = '322c3b29492673eb7d0b434bfa9dfb8653e34d02'
BASE = 'https://huggingface.co/istupakov/gigaam-v3-onnx/resolve/' + REVISION + '/'
FILES = {
    'v3_ctc.onnx': (885264128, '1fb978d4f41e1334003fae9d29f2d9844d4132315a90553a4b986839051ba9d3'),
    'v3_ctc.int8.onnx': (224721181, 'ceb61454e2e1a2dec5872cbac1de0fe0a4271d1148f6b26b5bda53ff30a12acd'),
    'v3_vocab.txt': (198, 'a9143c30844d3c0bee3e9e927e4084774eb1b9eeaafc473b2c4521e4911a7c07'),
    'config.json': (135, '0641fcf73f4af791c73f05083e38a658ff5dcbee3534a0c61396c10f4b97f0fe'),
    'LICENSE.txt': (1070, 'f00de6715714c7a63d08639cdbfaa40224eefc407302614bd19f1a8b98c875aa'),
}


def ensure_fast_assets(model_dir, gpu=True, stop=None, progress=lambda _: None):
    folder = Path(model_dir) / 'gigaam-v3'
    folder.mkdir(parents=True, exist_ok=True)
    stop = stop or threading.Event()
    selected = ['config.json', 'v3_vocab.txt', 'LICENSE.txt', 'v3_ctc.onnx' if gpu else 'v3_ctc.int8.onnx']
    for name in selected:
        size, digest = FILES[name]
        path = folder / name
        if not path.is_file() or path.stat().st_size != size:
            progress(tr('Загрузка быстрого распознавания: ') + name)
            download(BASE + name, path, digest, stop, progress)
    return folder


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    root = Path(__file__).resolve().parent
    for gpu in (True, False):
        ensure_fast_assets(root/'data/models', gpu, progress=lambda x: print(x, flush=True))
    print('FAST_MODELS_READY', flush=True)
