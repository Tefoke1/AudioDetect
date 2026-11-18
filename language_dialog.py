"""Choose the interface language on each launch; remember the last choice."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from core import load_settings, save_settings

def choose_language(data_dir):
    preferences = data_dir / 'language.json'
    saved = load_settings(preferences).get('language', 'ru')
    dialog = QDialog()
    dialog.setWindowTitle('AudioDetect')
    dialog.setMinimumWidth(420)
    dialog.setStyleSheet('QDialog {background:#174b58;color:white} QLabel {color:white;font-size:18px} QPushButton {padding:16px;font-size:16px;background:#f4f7f9;border:0;border-radius:5px}')
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.addWidget(QLabel('AudioDetect'))
    layout.addWidget(QLabel('Выберите язык / Choose your language'))
    buttons = QHBoxLayout()
    result = []
    def select(code):
        result.append(code)
        save_settings(preferences, {'language': code})
        dialog.accept()
    for code, text in [('ru', 'Русский'), ('en', 'English')]:
        button = QPushButton(text)
        button.clicked.connect(lambda checked=False, code=code: select(code))
        button.setDefault(code == saved)
        buttons.addWidget(button)
    layout.addLayout(buttons)
    dialog.exec()
    return result[0] if result else None
