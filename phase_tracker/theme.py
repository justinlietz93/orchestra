APP_STYLE = """
QWidget {
    background: #11161d;
    color: #dce7ef;
    font-family: "Inter", "DejaVu Sans", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog { background: #0c1117; }
QFrame#panel {
    background: #151c24;
    border: 1px solid #273442;
    border-radius: 10px;
}
QFrame#agentCard {
    background: #111820;
    border: 1px solid #30404f;
    border-radius: 8px;
}
QFrame#agentCard[active="true"] {
    background: #13222a;
    border: 2px solid #39c6db;
}
QFrame#dropZone {
    background: #0f151c;
    border: 2px dashed #3c5263;
    border-radius: 10px;
}
QFrame#dropZone[dragActive="true"] {
    background: #10252c;
    border: 2px dashed #46d4e8;
}
QLabel#eyebrow {
    color: #8294a5;
    font-size: 11px;
    font-weight: 700;
}
QLabel#title {
    color: #f4f8fb;
    font-size: 19px;
    font-weight: 700;
}
QLabel#muted { color: #8ea1b2; }
QLabel#activeText { color: #58d7e7; font-weight: 700; }
QLineEdit, QPlainTextEdit, QComboBox, QTreeView, QTreeWidget, QListWidget {
    background: #0d131a;
    border: 1px solid #2b3947;
    border-radius: 6px;
    padding: 6px;
    selection-background-color: #165c68;
    selection-color: #f7fdff;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #39c6db;
}
QPushButton {
    background: #202c37;
    border: 1px solid #344657;
    border-radius: 6px;
    padding: 7px 12px;
    font-weight: 600;
}
QPushButton:hover { background: #293847; border-color: #4c667b; }
QPushButton:pressed { background: #17212a; }
QPushButton:disabled { color: #5d6b77; background: #171e25; border-color: #242e37; }
QPushButton#primary {
    background: #14788a;
    border-color: #239aae;
    color: white;
}
QPushButton#primary:hover { background: #178da1; }
QPushButton#branch { border-color: #8b6fc4; }
QPushButton#phase { border-color: #c48655; }
QHeaderView::section {
    background: #18212a;
    color: #90a4b5;
    border: 0;
    border-bottom: 1px solid #2a3743;
    padding: 6px;
}
QTabWidget::pane { border: 1px solid #283642; border-radius: 6px; }
QTabBar::tab { background: #151d25; padding: 8px 16px; }
QTabBar::tab:selected { color: #55d5e5; border-bottom: 2px solid #43ccdf; }
QSplitter::handle { background: #25313c; width: 2px; }
QScrollBar:vertical { background: #11171e; width: 10px; }
QScrollBar::handle:vertical { background: #354554; border-radius: 5px; min-height: 24px; }
QToolTip { background: #202b35; color: white; border: 1px solid #466073; }
"""

