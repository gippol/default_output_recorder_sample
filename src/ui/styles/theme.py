"""
High-contrast dark theme for the desktop application.
"""

MODERN_DARK_THEME = """
/* Global Styles */
QMainWindow, QWidget {
    background-color: #090B0F;
    color: #FFFFFF;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}

/* Group Boxes / Cards */
QGroupBox {
    background-color: #151921;
    border: 2px solid #343B47;
    border-radius: 4px;
    margin-top: 12px;
    padding: 14px;
    font-weight: 600;
    font-size: 12px;
    color: #E6EDF7;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background-color: #151921;
}

/* Push Buttons */
QPushButton {
    background-color: #202631;
    color: #FFFFFF;
    border: 2px solid #566176;
    border-radius: 4px;
    padding: 7px 14px;
    font-weight: 600;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #2C3545;
    border-color: #AEB8C8;
}

QPushButton:pressed {
    background-color: #11151C;
}

QPushButton:disabled {
    background-color: #12151A;
    color: #707989;
    border-color: #303640;
}

/* Primary Record Button */
QPushButton#record_btn {
    background-color: #D92D20;
    color: #FFFFFF;
    border: 2px solid #FF6B60;
    border-radius: 4px;
    font-size: 15px;
    font-weight: bold;
    padding: 10px 24px;
}

QPushButton#record_btn:hover {
    background-color: #C6281D;
    border-color: #C6281D;
}

QPushButton#record_btn:pressed {
    background-color: #B42318;
}

/* Stop Button */
QPushButton#stop_btn {
    background-color: #252B36;
    color: #FFFFFF;
    border: 2px solid #AEB8C8;
    border-radius: 4px;
    font-size: 14px;
    font-weight: bold;
    padding: 10px 20px;
}

QPushButton#stop_btn:hover {
    background-color: #3A4352;
    color: #FFFFFF;
}

/* Pause Button */
QPushButton#pause_btn {
    background-color: #202631;
    color: #FFD166;
    border: 2px solid #FFD166;
    border-radius: 4px;
}

/* Combo Boxes & Inputs */
QComboBox, QLineEdit, QSpinBox {
    background-color: #0E1117;
    color: #FFFFFF;
    border: 2px solid #566176;
    border-radius: 4px;
    padding: 6px 10px;
    selection-background-color: #2563EB;
}

QComboBox:hover, QLineEdit:hover {
    border-color: #FFFFFF;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #151921;
    border: 2px solid #566176;
    selection-background-color: #2563EB;
    color: #FFFFFF;
    padding: 4px;
}

/* Checkboxes */
QCheckBox {
    color: #E6EDF7;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #AEB8C8;
    border-radius: 3px;
    background-color: #0E1117;
}

QCheckBox::indicator:checked {
    background-color: #2563EB;
    border-color: #2563EB;
}

/* List Widget / Tables */
QListWidget, QTableWidget {
    background-color: #0E1117;
    border: 2px solid #343B47;
    border-radius: 4px;
    color: #FFFFFF;
    padding: 4px;
}

QListWidget::item {
    padding: 7px;
    border-bottom: 1px solid #343B47;
    border-radius: 3px;
}

QListWidget::item:hover {
    background-color: #202631;
}

QListWidget::item:selected {
    background-color: #173E75;
    border: 2px solid #60A5FA;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #090B0F;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #566176;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""
