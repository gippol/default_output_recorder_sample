"""
Modern, sleek Dark Theme stylesheets (Linear / Apple Dark Mode inspired).
"""

MODERN_DARK_THEME = """
/* Global Styles */
QMainWindow, QWidget {
    background-color: #121316;
    color: #E2E8F0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Roboto', sans-serif;
    font-size: 13px;
}

/* Group Boxes / Cards */
QGroupBox {
    background-color: #1A1C23;
    border: 1px solid #2D3139;
    border-radius: 10px;
    margin-top: 12px;
    padding: 16px;
    font-weight: 600;
    font-size: 13px;
    color: #94A3B8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background-color: #1A1C23;
}

/* Push Buttons */
QPushButton {
    background-color: #242731;
    color: #F8FAFC;
    border: 1px solid #333846;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #2E3240;
    border-color: #475569;
}

QPushButton:pressed {
    background-color: #1E212B;
}

QPushButton:disabled {
    background-color: #16181F;
    color: #475569;
    border-color: #232733;
}

/* Primary Record Button */
QPushButton#record_btn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #EF4444, stop:1 #DC2626);
    color: #FFFFFF;
    border: 1px solid #F87171;
    border-radius: 24px;
    font-size: 15px;
    font-weight: bold;
    padding: 12px 28px;
}

QPushButton#record_btn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F87171, stop:1 #EF4444);
}

QPushButton#record_btn:pressed {
    background-color: #B91C1C;
}

/* Stop Button */
QPushButton#stop_btn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #374151, stop:1 #1F2937);
    color: #F9FAFB;
    border: 1px solid #4B5563;
    border-radius: 24px;
    font-size: 14px;
    font-weight: bold;
    padding: 12px 24px;
}

QPushButton#stop_btn:hover {
    background: #4B5563;
}

/* Pause Button */
QPushButton#pause_btn {
    background: #2D3748;
    color: #FBD38D;
    border: 1px solid #4A5568;
    border-radius: 8px;
}

/* Combo Boxes & Inputs */
QComboBox, QLineEdit, QSpinBox {
    background-color: #181A20;
    color: #F1F5F9;
    border: 1px solid #333846;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #3B82F6;
}

QComboBox:hover, QLineEdit:hover {
    border-color: #3B82F6;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #1E212B;
    border: 1px solid #333846;
    selection-background-color: #2563EB;
    color: #F8FAFC;
    padding: 4px;
}

/* Checkboxes */
QCheckBox {
    color: #CBD5E1;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #475569;
    border-radius: 4px;
    background-color: #1E212B;
}

QCheckBox::indicator:checked {
    background-color: #3B82F6;
    border-color: #60A5FA;
}

/* List Widget / Tables */
QListWidget, QTableWidget {
    background-color: #16181E;
    border: 1px solid #282C37;
    border-radius: 8px;
    color: #E2E8F0;
    padding: 4px;
}

QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #1F222B;
    border-radius: 4px;
}

QListWidget::item:hover {
    background-color: #1E222D;
}

QListWidget::item:selected {
    background-color: #1E293B;
    border: 1px solid #3B82F6;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #121316;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #2D3139;
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
