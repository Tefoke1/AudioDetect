# Build with the isolated onnxruntime-directml environment.
from PyInstaller.utils.hooks import collect_all, copy_metadata
asr_data, asr_bins, asr_hidden = collect_all('onnx_asr')
a = Analysis(['pipeline_worker.py'], pathex=['.'], binaries=asr_bins,
    datas=asr_data + [('translations.json', '.')] + copy_metadata('onnx-asr'),
    hiddenimports=asr_hidden + ['onnxruntime.capi.onnxruntime_pybind11_state'],
    excludes=['faster_whisper', 'PySide6', 'tkinter', 'torch'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AudioDetectWorker', console=True, upx=False, icon='assets/icon.ico')
coll = COLLECT(exe, a.binaries, a.datas, name='AudioDetectGPU', upx=False)
