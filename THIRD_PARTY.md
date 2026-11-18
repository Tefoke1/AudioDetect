# Third-party components

AudioDetect's application code is GPL-3.0-only. This does not replace the licenses of its dependencies or model weights. Preserve their notices when redistributing builds.

| Component | License / source |
|---|---|
| PySide6 / Qt Essentials | LGPLv3 / GPLv3 options; [Qt for Python](https://code.qt.io/cgit/pyside/pyside-setup.git/) and [Qt source](https://download.qt.io/archive/qt/) |
| Python | PSF license; [source](https://www.python.org/downloads/source/) |
| PyInstaller | GPLv2 with bootloader exception; [source and exception](https://github.com/pyinstaller/pyinstaller) |
| faster-whisper / CTranslate2 | MIT; [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2) |
| ONNX Runtime / onnx-asr | MIT; [runtime](https://github.com/microsoft/onnxruntime), [onnx-asr](https://github.com/istupakov/onnx-asr) |
| GigaAM v3 weights | MIT; [pinned ONNX conversion](https://huggingface.co/istupakov/gigaam-v3-onnx/tree/322c3b29492673eb7d0b434bfa9dfb8653e34d02), [upstream](https://github.com/salute-developers/GigaAM) |
| PyAV / bundled FFmpeg | BSD-3-Clause / LGPL; [PyAV sources and build recipes](https://github.com/PyAV-Org/PyAV) |
| NumPy / psutil | BSD-3-Clause; [NumPy](https://github.com/numpy/numpy), [psutil](https://github.com/giampaolo/psutil) |
| llama.cpp / Qwen3-4B | MIT / Apache-2.0; [engine](https://github.com/ggml-org/llama.cpp), [model](https://huggingface.co/Qwen/Qwen3-4B-GGUF) |
| Vosk Android 0.3.75 | Apache-2.0; [Vosk source](https://github.com/alphacep/vosk-api) |
| Vosk small Russian 0.22 / English US 0.15 | Apache-2.0; [model catalogue](https://alphacephei.com/vosk/models) |
| JNA 5.18.1 | LGPL-2.1-or-later or Apache-2.0; [JNA source](https://github.com/java-native-access/jna) |

Exact Python versions are recorded in `requirements-lock.txt` and `requirements-gpu-lock.txt`; Android dependencies are fixed in `android/app/build.gradle`. Portable Windows packages include dependency license files in `licenses/`. The Android package includes notices and Apache-2.0 license text in its assets. Optional downloaded engines and models retain their upstream license files.
