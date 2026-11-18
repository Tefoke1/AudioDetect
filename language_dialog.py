"""Choose the interface language on each launch; remember the last choice."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from core import load_settings, save_settings

def choose_language(data_dir):
    preferences = data_dir / 'language.json'
    saved = load_settings(preferences).get('language', 'ru')
    dialog = QDialog()
    dialog.setWindowTitle('AudioDetect')
    dialog.setMinimumWidth(420)
    from desktop_theme import STYLE, apply_palette
    from PySide6.QtWidgets import QApplication
    apply_palette(QApplication.instance())
    dialog.setStyleSheet(STYLE)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(28, 24, 28, 24)
    title = QLabel('AudioDetect')
    title.setObjectName('title')
    layout.addWidget(title)
    layout.addWidget(QLabel('Выберите язык / Choose your language'))
    buttons = QHBoxLayout()
    result = []
    def select(code):
        result.append(code)
        save_settings(preferences, {'language': code})
        dialog.accept()
    for code, text in [('ru', 'Русский'), ('en', 'English')]:
        button = QPushButton(text)
        button.setMinimumHeight(52)
        if code == saved:
            button.setObjectName("primary")
        button.clicked.connect(lambda checked=False, code=code: select(code))
        button.setDefault(code == saved)
        buttons.addWidget(button)
    layout.addLayout(buttons)
    dialog.exec()
    return result[0] if result else None
