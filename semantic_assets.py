from i18n import tr
"""Install the pinned local text-analysis engine and model, with SHA-256 checks."""
from pathlib import Path
import hashlib
import json
import threading
import urllib.request
import zipfile

ENGINE_URL = 'https://github.com/ggml-org/llama.cpp/releases/download/b12359/llama-b12359-bin-win-cpu-x64.zip'
ENGINE_HASH = '837c1655e87df3b66989f4be33a792a1399c785bf259038dc75c900096683e69'
VULKAN_URL = 'https://github.com/ggml-org/llama.cpp/releases/download/b12359/llama-b12359-bin-win-vulkan-x64.zip'
VULKAN_HASH = 'e8d18c6e4210cca87e7307c2ea78363ac8d158e4e1397358ec96ab70b53a0d5e'
MODEL_NAME = 'Qwen3-4B-Q4_K_M.gguf'
MODEL_URL = 'https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/' + MODEL_NAME
MODEL_HASH = '7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'
MODEL_SIZE = 2497280256


class Cancelled(Exception):
    pass


def download(url, path, expected, stop, progress):
    path = Path(path)
    part = path.with_suffix(path.suffix + '.part')
    # Interrupted files are resumed; the entire digest is checked before activation.
    offset = part.stat().st_size if part.exists() else 0
    headers = {'User-Agent': 'Local-Conversation-Search/2'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 206:
            offset = 0
        total = int(response.headers.get('Content-Length', '0')) + offset
        written = offset
        last_percent = -1
        with part.open('ab' if offset else 'wb') as output:
            while True:
                if stop.is_set():
                    raise Cancelled()
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                written += len(chunk)
                percent = int(written * 100 / total) if total else 0
                if percent != last_percent:
                    progress(tr('Загрузка компонентов: {0}% ({1} МБ)', percent, written // 1048576))
                    last_percent = percent
    digest = hashlib.sha256()
    with part.open('rb') as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
            if stop.is_set():
                raise Cancelled()
            digest.update(chunk)
    if digest.hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise RuntimeError(tr('Скачанный компонент повреждён. Повторите загрузку.'))
    part.replace(path)


def ensure_vulkan(folder, stop=None, progress=lambda _: None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / 'llama-vulkan-b12359'
    executable = destination / 'llama-server.exe'
    if executable.is_file():
        return executable
    stop = stop or threading.Event()
    archive = folder / 'llama-vulkan-b12359.zip'
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != VULKAN_HASH:
        download(VULKAN_URL, archive, VULKAN_HASH, stop, progress)
    destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if not (destination/member.filename).resolve().is_relative_to(destination.resolve()):
                raise RuntimeError(tr('Некорректный путь в архиве компонента.'))
        bundle.extractall(destination)
    if not executable.is_file():
        raise RuntimeError(tr('В компоненте анализа не найден исполняемый файл.'))
    return executable


def ensure_assets(folder, stop=None, progress=lambda _: None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stop = stop or threading.Event()
    engine_dir = folder / 'llama-b12359'
    executables = list(engine_dir.rglob('llama-server.exe')) if engine_dir.exists() else []
    if not executables:
        archive = folder / 'llama-b12359.zip'
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != ENGINE_HASH:
            download(ENGINE_URL, archive, ENGINE_HASH, stop, progress)
        engine_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = (engine_dir / member.filename).resolve()
                if not target.is_relative_to(engine_dir.resolve()):
                    raise RuntimeError(tr('Некорректный путь в архиве компонента.'))
            bundle.extractall(engine_dir)
        executables = list(engine_dir.rglob('llama-server.exe'))
    if not executables:
        raise RuntimeError(tr('В компоненте анализа не найден исполняемый файл.'))
    model = folder / MODEL_NAME
    if not model.exists() or model.stat().st_size != MODEL_SIZE:
        download(MODEL_URL, model, MODEL_HASH, stop, progress)
    (folder / 'versions.json').write_text(json.dumps({'engine': ENGINE_URL, 'engine_sha256': ENGINE_HASH,
        'model': MODEL_URL, 'model_sha256': MODEL_HASH,
        'vulkan': VULKAN_URL, 'vulkan_sha256': VULKAN_HASH}, indent=2), encoding='utf-8')
    gpu_executables = list((folder / 'llama-vulkan-b12359').glob('llama-server.exe'))
    if gpu_executables:
        return gpu_executables[0], model
    return executables[0], model


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    if '--vulkan' in sys.argv:
        ensure_vulkan(Path(__file__).parent / 'data' / 'analysis-model', progress=lambda x: print(x, flush=True))
    assets = ensure_assets(Path(__file__).parent / 'data' / 'analysis-model', progress=lambda x: print(x, flush=True))
    print('LOCAL_ANALYSIS_READY', flush=True)
