"""Package only built runtimes, named model weights and public documentation."""
import argparse
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gigaam_assets import FILES, ensure_fast_assets

def package(model_source=None):
    folder = ROOT / 'dist/AudioDetect'
    if not (folder / 'AudioDetect.exe').is_file():
        raise RuntimeError('Build AudioDetect.spec first')
    gpu = ROOT / 'dist/AudioDetectGPU'
    if not (gpu / 'AudioDetectWorker.exe').is_file():
        raise RuntimeError('Build AudioDetectGPU.spec first')
    # Refuse to package any existing user state.
    data = folder / 'data'
    if data.exists():
        unexpected = [p for p in data.rglob('*') if p.is_file() and p.relative_to(data).as_posix() not in {'models/gigaam-v3/' + n for n in FILES}]
        if unexpected:
            raise RuntimeError('User state found in build output; use a fresh build')
    shutil.copytree(gpu, folder / 'gpu', dirs_exist_ok=True)
    source = Path(model_source) if model_source else ROOT / '.release/model-cache/gigaam-v3'
    if model_source is None:
        for use_gpu in (False, True):
            ensure_fast_assets(source.parent, use_gpu, progress=print)
    target = data / 'models/gigaam-v3'
    target.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in FILES.items():
        p = source / name
        with p.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if p.stat().st_size != size or actual != digest:
            raise RuntimeError('Invalid model file: ' + name)
        shutil.copyfile(p, target / name)
    for name in ('README.md', 'README.ru.md', 'LICENSE', 'THIRD_PARTY.md', 'requirements-lock.txt', 'requirements-gpu-lock.txt'):
        shutil.copyfile(ROOT / name, folder / name)
    shutil.copytree(ROOT / 'docs', folder / 'docs', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'assets', folder / 'assets', dirs_exist_ok=True)
    notices = folder / 'licenses'
    notices.mkdir(exist_ok=True)
    for cached in notices.rglob('*.pyc'):
        cached.unlink()
    for cached in notices.rglob('*.pyo'):
        cached.unlink()
    for distribution in importlib.metadata.distributions():
        for item in distribution.files or []:
            name = str(item)
            if '__pycache__' in Path(name).parts or Path(name).suffix in {'.pyc', '.pyo'}:
                continue
            if '.dist-info/' not in name or not any(s in name.lower() for s in ('license', 'copying', 'notice', 'copyright')):
                continue
            path = Path(distribution.locate_file(item))
            if path.is_file():
                destination = notices / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
    release = ROOT / '.release'
    release.mkdir(exist_ok=True)
    output = release / 'AudioDetect-windows-x64.zip'
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                archive.write(path, Path('AudioDetect') / path.relative_to(folder))
    print(output.name, output.stat().st_size)
    return output
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-source', type=Path)
    package(parser.parse_args().model_source)
