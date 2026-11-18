"""Writable files live next to the portable executable, outside bundled resources."""
from pathlib import Path
import sys

def application_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent

def worker_command(model, analysis_only=False):
    base = application_dir()
    if getattr(sys, 'frozen', False):
        gpu = base / 'gpu' / 'AudioDetectWorker.exe'
        worker = gpu if model == 'gigaam-v3-ctc' and not analysis_only and gpu.is_file() else base / 'AudioDetectWorker.exe'
        return [str(worker)]
    gpu = base / '.venv-dml' / 'Scripts' / 'python.exe'
    python = gpu if model == 'gigaam-v3-ctc' and not analysis_only and gpu.is_file() else Path(sys.executable)
    if python.name.lower() == 'pythonw.exe':
        python = python.with_name('python.exe')
    return [str(python), '-u', str(base / 'pipeline_worker.py')]
