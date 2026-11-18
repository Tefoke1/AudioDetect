from i18n import tr
"""Extractive briefs: topic labels and an exact excerpt, never invented facts."""
import re

TOPICS = [
    (tr('ХВС'), r'\bхвс\b|холодн\w* вод'),
    (tr('ГВС'), r'\bгвс\b|горяч\w* вод'),
    (tr('ИТП'), r'\bитп\b'),
    (tr('Земляные работы'), r'землян|раскоп|транше|выкоп'),
    (tr('Смета'), r'смет'),
    (tr('Проект'), r'проект'),
    (tr('Правки'), r'поправ|исправ|коррект'),
    (tr('Фото/видео'), r'фото|видео'),
    (tr('Пересорт'), r'пересорт'),
    (tr('Подписи'), r'подпис'),
    (tr('Договор'), r'договор'),
    (tr('Оплата'), r'оплат|платеж|платёж'),
    (tr('Сроки'), r'срок'),
    (tr('Отопление'), r'отоплен'),
    (tr('Кровля'), r'кровл'),
]
ACTION = re.compile(r'учтен|учтён|включ|исключ|поправ|исправ|отправ|вышл|высл|переда|подпис|нет', re.I)
RUDE = re.compile(r'\b(?:бля(?:ть|дь)?|хуй\w*|еба\w*|ёба\w*|пизд\w*|нахуй)\b', re.I)


def source_brief(units):
    texts = [u.text.strip() for u in units if u.text.strip()]
    if not texts:
        return tr('Нет текста для краткого описания.')
    source = ' '.join(texts)
    labels = [tr(name) for name, pattern in TOPICS if re.search(pattern, source, re.I)][:3]
    def score(text):
        return 3 * bool(ACTION.search(text)) + sum(bool(re.search(p, text, re.I)) for _, p in TOPICS)
    # Prefer a complete clean utterance; never delete a negation or rewrite a quoted word.
    quote = max([text for text in texts if not RUDE.search(text)] or texts, key=score)
    if len(quote) > 180:
        # Keep negations and qualifications together; quote a contiguous source prefix.
        quote = quote[:177].rsplit(' ', 1)[0] + '…'
    return (', '.join(labels) + ': ' if labels else '') + '«' + quote + '»'
