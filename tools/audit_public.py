"""Fail closed on obvious private artifacts in Git's proposed public file set.
This complements a private denylist and manual binary review; it is not a secret detector.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {'data', 'test-output', 'maintenance', '.build-tools', '.venv', '.venv-dml', 'build', 'dist', '.release', '.gradle'}
FORBIDDEN_SUFFIXES = {'.mp3', '.wav', '.m4a', '.sqlite', '.sqlite3', '.db', '.log', '.keystore', '.jks', '.lnk'}
def audit():
    result = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT, capture_output=True, check=True)
    files = [Path(p) for p in result.stdout.decode('utf-8').split('\0') if p]
    errors = []
    for relative in files:
        if FORBIDDEN_PARTS.intersection(relative.parts) or relative.suffix.lower() in FORBIDDEN_SUFFIXES or relative.name in {'local.properties', 'settings.json', '.env'}:
            errors.append(str(relative) + ': private/build artifact')
        path = ROOT / relative
        if not path.is_file() or path.suffix in {'.jar', '.png', '.ico'}:
            continue
        raw = path.read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            errors.append(str(relative) + ': unexpected large source file')
            continue
        text = raw.decode('utf-8', errors='replace')
        if re.search(r'(?i)[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\s\"<>]+', text):
            errors.append(str(relative) + ': absolute personal path')
        if re.search(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)', text):
            errors.append(str(relative) + ': possible credential')
    if errors:
        print('\n'.join(errors))
        return 1
    print('Public source audit passed:', len(files), 'files')
    return 0
if __name__ == '__main__':
    raise SystemExit(audit())
