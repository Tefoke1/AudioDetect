"""Fetch only the two public, pinned speech models used by the offline APK."""
from pathlib import Path
import hashlib
import urllib.request

MODELS = {
    'ru': ('vosk-model-small-ru-0.22', '961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4'),
    'en': ('vosk-model-small-en-us-0.15', '30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498'),
}
def prepare():
    folder = Path(__file__).resolve().parents[1] / 'android/app/src/main/assets'
    folder.mkdir(parents=True, exist_ok=True)
    for language, (name, expected) in MODELS.items():
        output = folder / ('vosk-' + language + '.zip')
        if output.is_file() and hashlib.file_digest(output.open('rb'), 'sha256').hexdigest() == expected:
            continue
        temporary = output.with_suffix('.part')
        with urllib.request.urlopen('https://alphacephei.com/vosk/models/' + name + '.zip', timeout=60) as response, temporary.open('wb') as target:
            while block := response.read(1024 * 1024):
                target.write(block)
        with temporary.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                temporary.unlink()
                raise RuntimeError('Model checksum mismatch: ' + name)
        temporary.replace(output)
        print('Ready:', name)
if __name__ == '__main__':
    prepare()
