"""Shared coral / deep-green visual language for the native desktop app."""
from pathlib import Path
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QGraphicsDropShadowEffect

COLORS = dict(background='#142c2f', surface='#203d3f', raised='#2b4949',
              line='#54716e', text='#f1f2e0', muted='#b8c9c1', accent='#ff9f8f', ink='#2a2b26')

STYLE = '''
QMainWindow, QDialog { background: #142c2f; }
QWidget { color: #f1f2e0; font-family: "Segoe UI"; font-size: 14px; }
QWidget#workspace { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #49453a,stop:.28 #234042,stop:1 #142c2f); }
QWidget#header { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #6d5146,stop:.38 #2b4949,stop:1 #183438); border-bottom: 1px solid #54716e; }
QLabel { background: transparent; }
QLabel#title { font-size: 28px; font-weight: 650; color: #ffb4a4; }
QLabel#subtitle, QLabel#muted { color: #b8c9c1; font-size: 13px; }
QLabel#section { font-size: 19px; font-weight: 600; }
QLabel#pageTitle { font-size: 29px; font-weight: 650; }
QLabel#accent { color: #ffb4a4; font-size: 15px; }
QLabel#heroText { font-size: 16px; color: #d3ded3; }
QWidget#panel { background:#203d3f; border:1px solid #54716e; border-radius:12px; }
QWidget#panel QLabel { border:0; background:transparent; }
QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox { background:#142c2f; border:1px solid #54716e; border-radius:8px; padding:10px 12px; selection-background-color:#ff9f8f; selection-color:#2a2b26; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus { border:2px solid #ff9f8f; padding:9px 11px; }
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QDoubleSpinBox:disabled {color:#899e96;background:#263f3f;border-color:#344e4e;}
QComboBox::drop-down {border:0;width:24px;}
QComboBox::down-arrow {image:url(__ASSETS__/caret.svg);width:16px;height:16px;}
QComboBox QAbstractItemView {background:#203d3f;color:#f1f2e0;selection-background-color:#3b6060;selection-color:#fff4e5;outline:0;}
QPushButton { background:#203d3f; border:1px solid #54716e; border-radius:8px; padding:11px 16px; }
QPushButton:hover {background:#345352;border-color:#ffb4a4;}
QPushButton:pressed {background:#172e31;}
QPushButton:focus {border:2px solid #ffb4a4;padding:10px 15px;}
QPushButton:disabled {color:#91a69e;background:#314744;border-color:#425a54;}
QPushButton#primary {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffb4a4,stop:1 #ff9586);color:#2a2b26;border:1px solid #ffc7b9;font-weight:650;}
QPushButton#primary:hover {background:#ffc0af;}
QPushButton#primary:pressed {background:#ed8d7e;}
QPushButton#primary:disabled {background:#6b7970;color:#d1d9cb;border-color:#6b7970;}
QPushButton#quiet {border:0;background:transparent;color:#c6d8ce;padding:8px;}
QPushButton#quiet:hover {color:#ffb4a4;background:#2b4949;}
QPushButton#danger {border-color:#be8276;color:#ffb4a4;}
QTableWidget, QTextBrowser {background:#193638;alternate-background-color:#203d3f;color:#f1f2e0;border:1px solid #54716e;border-radius:9px;}
QTableWidget::item:selected {background:#466563;color:#fff1df;}
QTableWidget::item {padding:7px;border-bottom:1px solid #2c4d4e;}
QHeaderView {background:transparent;}
QHeaderView::section {background:#2b4949;color:#e4e9d7;padding:10px;border:0;border-bottom:1px solid #77918a;font-weight:600;}
QTableWidget {gridline-color:#29494a;}
QProgressBar {border:1px solid #486461;border-radius:5px;background:#142c2f;min-height:9px;max-height:9px;}
QProgressBar::chunk {background:#ff9f8f;border-radius:4px;}
QCheckBox {spacing:8px;background:transparent;padding:5px 0;}
QCheckBox::indicator {width:17px;height:17px;border:1px solid #819a91;border-radius:4px;background:#142c2f;}
QCheckBox::indicator:checked {background:#ff9f8f;border:2px solid #ffcfbd;image:url(__ASSETS__/check.svg);}
QCheckBox::indicator:disabled {background:#425a54;border-color:#425a54;}
QSplitter::handle {background:#345453;}
QToolTip {background:#2b4949;color:#fff1df;padding:8px;border:1px solid #ff9f8f;}
QTabWidget::pane {border:0;background:transparent;}
QTabBar::tab {background:#203d3f;color:#bdcec3;padding:15px 30px;margin:8px 3px;border:1px solid #54716e;border-radius:8px;}
QTabBar::tab:selected {background:#ff9f8f;color:#2a2b26;border-color:#ffcab9;font-weight:650;}
QTabBar::tab:hover:!selected {background:#345352;color:#fff1df;}
QScrollBar:vertical {background:#173335;width:10px;border:0;}
QScrollBar::handle:vertical {background:#54716e;border-radius:5px;min-height:24px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QCalendarWidget QWidget {background:#203d3f;color:#f1f2e0;}
QCalendarWidget QAbstractItemView {selection-background-color:#ff9f8f;selection-color:#2a2b26;}
QMenu {background:#203d3f;border:1px solid #54716e;}
QMenu::item:selected {background:#466563;}
'''

STYLE = STYLE.replace('__ASSETS__', (Path(__file__).parent / 'assets').as_posix())

def apply_palette(app):
    palette = QPalette()
    for role, color in [('Window','#142c2f'),('WindowText','#f1f2e0'),('Base','#193638'),
                        ('AlternateBase','#203d3f'),('Text','#f1f2e0'),('Button','#203d3f'),
                        ('ButtonText','#f1f2e0'),('Highlight','#ff9f8f'),('HighlightedText','#2a2b26'),
                        ('ToolTipBase','#2b4949'),('ToolTipText','#f1f2e0'),('PlaceholderText','#b8c9c1')]:
        palette.setColor(getattr(QPalette.ColorRole,role),QColor(color))
    app.setPalette(palette)

def lift(widget, accent=False):
    effect=QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(22 if accent else 14)
    effect.setOffset(0,4)
    effect.setColor(QColor(255,159,143,45) if accent else QColor(0,15,18,100))
    widget.setGraphicsEffect(effect)
