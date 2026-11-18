"""UI translations; transcript text is never translated or rewritten."""
import json
import os
from pathlib import Path
LANGUAGE = os.environ.get('AUDIODETECT_LANGUAGE', 'ru')
MESSAGES = json.loads((Path(__file__).parent / 'translations.json').read_text(encoding='utf-8'))
def set_language(language):
    global LANGUAGE
    LANGUAGE = language if language in ('ru', 'en') else 'ru'
    os.environ['AUDIODETECT_LANGUAGE'] = LANGUAGE
def tr(message, *args):
    text = MESSAGES.get(message, message) if LANGUAGE == 'en' else message
    return text.format(*args) if args else text
