# Recognition performance · 0.2.0

[Русский](PERFORMANCE.ru.md) · [Build and reproduce](BUILD.md) · [Raw measurements](benchmark-emulator.json)

## Implemented

Android now runs up to two files concurrently, sharing one Vosk model with independent recognizers. New jobs fall back to one worker on low-memory devices, battery saver or significant thermal pressure. Already running files finish; reduced concurrency applies to the next scheduling decision. Economy mode always uses one worker. Shared models across threads are supported by the [Vosk API](https://github.com/alphacep/vosk-api/blob/master/src/vosk_api.h).

MediaCodec input is filled without blocking per input packet; decoded mono PCM is passed in reusable quarter-second batches. Sample rate, decoder parameters and all speech are retained. A valid transcript bypasses model loading entirely. Each completed file is committed independently; Stop terminates only the recognition process. Progress shows elapsed time, processed audio and an estimate based on file bytes and current-file progress. Variable bitrates make that estimate approximate.

## Measured, not projected

API 35 x86_64 emulator, four virtual cores; three iterations per condition. Models: Vosk small RU 0.22 / EN 0.15. Locally generated fictional speech repeated five times with silence, encoded as MP3 at 64 kbit/s. Baseline is the 0.1.0 decoding loop. Times include decoding and recognition, but exclude one-time model extraction and model loading (RU 1.16 s; EN 0.55 s).

| Fixture | Audio length | Old, one file | New, one file | New, two files together | Queue gain¹ |
|---|---:|---:|---:|---:|---:|
| Russian, mono 16 kHz | 67.94 s | 6.62 s | 7.06 s | 7.84 s | 1.69× |
| English, stereo 44.1 kHz | 56.24 s | 7.13 s | 7.66 s | 8.48 s | 1.68× |

Medians. ¹Two times the old single-file median divided by the new pair median. This is a small synthetic decoding benchmark, not a 500-file end-to-end test. **Single-file latency increased by about 7%; concurrency produced the queue improvement.** The fixture's recognized words were unchanged. This does not establish accuracy on real telephone calls, sustained phone throughput or thermal behavior. No physical phone was tested. A time guarantee from file count or megabytes would be misleading.

Integration checks cover Russian/English positive and negative search, all-cache reruns with zero model workers, combined filters, bulk selection scope, stale-job isolation, Stop and retained transcripts. Stop was observed complete within 0.1 s in this emulator run; device behavior may differ.

## Methods reviewed; not yet shipped

| Candidate | Reason to evaluate | Required evidence before changing the default |
|---|---|---|
| [Small Russian Zipformer with sherpa-onnx](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/zipformer-transducer-models.html#sherpa-onnx-small-zipformer-ru-2024-09-18-russian) | Compact int8 encoder, Android-capable runtime | ARM64 sustained speed, RAM and keyword misses against Vosk |
| [T-one](https://github.com/voicekit-team/T-one) | Russian telephony specialization; [8 kHz streaming ONNX export](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-ctc/t-one-ctc-models.html) | Call-quality evaluation, timestamps, memory and quantization cost |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Quantized multilingual models, VAD and Android support | Precision of names/numbers versus latency; quiet speech and boundary recall |
| [ONNX Runtime mobile](https://onnxruntime.ai/docs/tutorials/mobile/) / [QNN](https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html) | CPU/int8 baseline, possible Snapdragon acceleration | Supported operators and shapes, conversion/calibration, device-specific speed; acceleration is not a universal switch |

The current Android build uses CPU Vosk, **not GPU/NPU**. GPU server benchmarks cannot be applied to a phone. Keyword-only recognition grammars are unsuitable as the default for open conversation search: restricting vocabulary can hide context or force unrelated speech into a query. Aggressive silence removal can miss quiet or short words. Any future cascade must measure false negatives, not only average transcription error, and keep a full-recognition path.

## Check on your own device

1. Choose a small set of new recordings with known positive and negative examples. Keep their contents private.
2. Note elapsed time, displayed speed and missed/incorrect matches. `10×` means ten minutes of audio per minute of processing. Repeat on a different uncached set of comparable duration with Economy mode if comparing concurrency; a cached repeat is not an ASR speed test.
3. Change the query on the same files. Results should reuse saved text. Stop a fresh batch and resume; completed files should be reused.

For a 30-minute target the required sustained speed is total audio minutes divided by 30, plus preparation overhead. A ten-hour collection requires over 20×; a one-hour collection only over 2×. Do not infer duration from compressed size.
