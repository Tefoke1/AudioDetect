# Build from the repository root: python -m PyInstaller --noconfirm AudioDetect.spec
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata
asr_data, asr_bins, asr_hidden = collect_all('onnx_asr')
a = Analysis(['launcher.py'], pathex=['.'], binaries=asr_bins,
    datas=asr_data + [('translations.json', '.')] + collect_data_files('faster_whisper') + copy_metadata('onnx-asr'),
    hiddenimports=asr_hidden + ['pipeline_worker', 'app', 'language_dialog', 'onnxruntime.capi.onnxruntime_pybind11_state'],
    excludes=['tkinter', 'matplotlib', 'scipy', 'IPython', 'pytest', 'torch'], noarchive=False)
# Qt uses the Windows ICU API. A similarly named third-party DLL on the
# build machine's PATH has incompatible, version-suffixed exports.
# Never shadow the operating system ICU library with that unrelated build.
from pathlib import Path
import PySide6
import re
qt_dir = Path(PySide6.__file__).parent
runtime_names = {'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'}
a.binaries = [entry for entry in a.binaries
    if Path(entry[0]).name.lower() != 'icuuc.dll'
    and not re.fullmatch(r'icudt\d+\.dll', Path(entry[0]).name.lower())
    and not (Path(entry[0]).parent == Path('.') and Path(entry[0]).name.lower() in runtime_names)]
for name in runtime_names:
    source = next((p for p in qt_dir.glob('*.dll') if p.name.lower() == name), None)
    if source:
        a.binaries.append((name, str(source), 'BINARY'))
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AudioDetect', console=False, upx=False, icon='assets/icon.ico')
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AudioDetectWorker', console=True, upx=False, icon='assets/icon.ico')
coll = COLLECT(gui, worker, a.binaries, a.datas, name='AudioDetect', upx=False)
