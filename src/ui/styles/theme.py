"""
Simple, flat light theme for the desktop application.
"""

MODERN_DARK_THEME = """
/* Global Styles */
QMainWindow, QWidget {
    background-color: #F4F5F7;
    color: #20242A;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}

/* Group Boxes / Cards */
QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #DDE1E7;
    border-radius: 6px;
    margin-top: 12px;
    padding: 14px;
    font-weight: 600;
    font-size: 12px;
    color: #4B5563;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background-color: #FFFFFF;
}

/* Push Buttons */
QPushButton {
    background-color: #FFFFFF;
    color: #252A31;
    border: 1px solid #CBD1D9;
    border-radius: 5px;
    padding: 7px 14px;
    font-weight: 600;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #F8F9FA;
    border-color: #9CA3AF;
}

QPushButton:pressed {
    background-color: #EDF0F3;
}

QPushButton:disabled {
    background-color: #F1F2F4;
    color: #A1A7AF;
    border-color: #E2E5E9;
}

/* Primary Record Button */
QPushButton#record_btn {
    background-color: #D92D20;
    color: #FFFFFF;
    border: 1px solid #D92D20;
    border-radius: 5px;
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
    background-color: #374151;
    color: #FFFFFF;
    border: 1px solid #374151;
    border-radius: 5px;
    font-size: 14px;
    font-weight: bold;
    padding: 10px 20px;
}

QPushButton#stop_btn:hover {
    background-color: #4B5563;
}

/* Pause Button */
QPushButton#pause_btn {
    background-color: #FFFFFF;
    color: #8A5A00;
    border: 1px solid #CBD1D9;
    border-radius: 5px;
}

/* Combo Boxes & Inputs */
QComboBox, QLineEdit, QSpinBox {
    background-color: #FFFFFF;
    color: #20242A;
    border: 1px solid #CBD1D9;
    border-radius: 5px;
    padding: 6px 10px;
    selection-background-color: #2563EB;
}

QComboBox:hover, QLineEdit:hover {
    border-color: #9CA3AF;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #CBD1D9;
    selection-background-color: #DBEAFE;
    color: #20242A;
    padding: 4px;
}

/* Checkboxes */
QCheckBox {
    color: #4B5563;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #A5ABB5;
    border-radius: 3px;
    background-color: #FFFFFF;
}

QCheckBox::indicator:checked {
    background-color: #2563EB;
    border-color: #2563EB;
}

/* List Widget / Tables */
QListWidget, QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #DDE1E7;
    border-radius: 5px;
    color: #20242A;
    padding: 4px;
}

QListWidget::item {
    padding: 7px;
    border-bottom: 1px solid #EDF0F3;
    border-radius: 3px;
}

QListWidget::item:hover {
    background-color: #F5F7FA;
}

QListWidget::item:selected {
    background-color: #EAF2FF;
    border: 1px solid #93C5FD;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #F4F5F7;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #CBD1D9;
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
