# Build AudioDetect

## Windows

Use Windows x64 and Python 3.12. From the repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt pyinstaller==6.19.0
.venv\Scripts\python -m unittest discover
.venv\Scripts\python app.py
```

Keep DirectML in a separate environment: its ONNX Runtime package shares module names with the CPU package.

```powershell
py -3.12 -m venv .venv-dml
.venv-dml\Scripts\python -m pip install -r requirements-gpu-lock.txt pyinstaller==6.19.0
.venv\Scripts\python -m PyInstaller --noconfirm AudioDetect.spec
.venv-dml\Scripts\python -m PyInstaller --noconfirm AudioDetectGPU.spec
.venv\Scripts\python tools/package_windows.py
```

The packaging script downloads hash-checked Russian models unless `--model-source` points to an existing model directory. It copies only named model files, never a working `data/` directory. Output: `.release/AudioDetect-windows-x64.zip`. Keep `AudioDetect.exe`, its worker and `_internal/` together. The GPU worker has its own isolated runtime.

For source development, `--data-dir` selects a private data location and `--language ru|en` bypasses the startup language dialog. Detailed analysis downloads its optional model on first use.

## Android

Use JDK 17, Android SDK platform 35 / build tools 35.0.0, and the included Gradle wrapper. Set `ANDROID_HOME` to your SDK, or create a local, ignored `android/local.properties`. The APK supports Android 8+ (API 26), ARM64, ARMv7 and x86_64.

```powershell
python tools/prepare_android_models.py
cd android
.\gradlew.bat testDebugUnitTest assembleDebug assembleRelease
```

`app/build/outputs/apk/debug/` contains a locally signed development APK. Release builds are unsigned until signed using your own **private** key:

```text
zipalign -p -f 4 app-release-unsigned.apk app-aligned.apk
apksigner sign --ks YOUR_PRIVATE_KEYSTORE --out AudioDetect-android.apk app-aligned.apk
apksigner verify --verbose AudioDetect-android.apk
```

Never commit signing keys, passwords, SDK paths or the model ZIPs. Model downloads are pinned by URL and SHA-256 in the preparation script. Models are bundled into the APK; the installed app makes no network requests.

## Validation scope

Python tests cover phrase/keyword matching, number boundaries, selected-file scope, cache invalidation, filters and discussion validation. Android unit tests cover its independent matching implementation. Before distributing binaries, also run actual recognition, cancellation, playback and export tests on the packaged applications. Synthetic speech does not establish real-call recognition accuracy. Test device performance separately.

The optional Android integration runner uses locally generated speech fixtures. On Windows, run `tools/generate_test_audio.ps1` with English and Russian SAPI voices installed, then build `assembleDebugAndroidTest`. Install the debug and test APKs on an emulator and run `adb -s YOUR_EMULATOR_SERIAL shell am instrument -w -e language en org.audiodetect.app.benchmark.test/org.audiodetect.app.SmokeInstrumentation` (repeat with `-e language ru`). This checks actual offline recognition, positive/negative queries, UI results, Stop and cache retention. Generated WAV files are ignored by Git and are never included in the release APK.

Debug builds use the separate `org.audiodetect.app.benchmark` package so they cannot replace an installed release. Always target the intended emulator explicitly. Grant its notification permission to keep permission dialogs out of UI captures.

For the decoder comparison, run `python tools/generate_benchmark_audio.py` after generating SAPI fixtures, rebuild/install the test APK, run both language integration checks to unpack the bundled models, then run the instrumentation with `-e benchmark true`. It compares the preserved 0.1.0 decoder against the current single-file and two-file paths, three times each. Results are printed as JSON. The baseline and speech fixtures are test-only.
