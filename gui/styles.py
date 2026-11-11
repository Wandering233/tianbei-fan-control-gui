"""
Dark engineering QSS theme matching TianBei MACO BIOS Control Center aesthetic.
"""

DARK_THEME = """
QWidget {
    background-color: #0D1117;
    color: #C9D1D9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
    selection-background-color: #1F6FEB;
    selection-color: #FFFFFF;
}

QGroupBox {
    border: 1px solid #30363D;
    border-radius: 10px;
    margin-top: 12px;
    padding: 14px 12px 10px 12px;
    background-color: #161B22;
    font-weight: 600;
    font-size: 13px;
    color: #F0F6FC;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    background-color: #161B22;
    color: #58A6FF;
}

QLabel {
    background-color: transparent;
    color: #C9D1D9;
}

QLabel#HeaderTitle {
    font-size: 18px;
    font-weight: 700;
    color: #F0F6FC;
    letter-spacing: -0.2px;
}

QLabel#HeaderSubtitle {
    font-size: 12px;
    color: #8B949E;
}

QLabel#BadgeSafe {
    background-color: rgba(56, 139, 253, 0.12);
    color: #58A6FF;
    border: 1px solid rgba(56, 139, 253, 0.35);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 600;
}

QLabel#BadgeOk {
    background-color: rgba(63, 185, 80, 0.12);
    color: #3FB950;
    border: 1px solid rgba(63, 185, 80, 0.35);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 600;
}

QLabel#BadgeWarn {
    background-color: rgba(210, 153, 34, 0.14);
    color: #D29922;
    border: 1px solid rgba(210, 153, 34, 0.4);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 600;
}

QLabel#HintBox {
    background-color: rgba(110, 118, 129, 0.1);
    border: 1px solid #30363D;
    border-radius: 8px;
    padding: 9px 12px;
    color: #8B949E;
    font-size: 11.5px;
}

QFrame#MetricCard {
    background-color: #161B22;
    border: 1px solid #30363D;
    border-radius: 10px;
}

QFrame#SurfaceCard {
    background-color: #161B22;
    border: 1px solid #30363D;
    border-radius: 10px;
}

QLabel#MetricTitle {
    font-size: 11.5px;
    font-weight: 600;
    color: #8B949E;
}

QLabel#MetricValue {
    font-size: 20px;
    font-weight: 700;
    color: #F0F6FC;
}

QLabel#MetricSub {
    font-size: 11.5px;
    color: #8B949E;
}

QPushButton#ModeCard {
    background-color: #161B22;
    border: 1.5px solid #30363D;
    border-radius: 10px;
    text-align: left;
    padding: 12px 14px;
}

QPushButton#ModeCard:hover {
    background-color: #1C222B;
    border-color: #484F58;
}

QPushButton#ModeCard[modeRole="auto"]:checked {
    background-color: rgba(56, 139, 253, 0.12);
    border: 1.5px solid #58A6FF;
}

QPushButton#ModeCard[modeRole="full"]:checked {
    background-color: rgba(248, 81, 73, 0.12);
    border: 1.5px solid #F85149;
}

QPushButton#ModeCard[modeRole="curve"]:checked {
    background-color: rgba(63, 185, 80, 0.12);
    border: 1.5px solid #3FB950;
}

QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #21262D;
    color: #F0F6FC;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: 500;
}

QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #58A6FF;
}

QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #58A6FF;
}

QComboBox QAbstractItemView {
    background-color: #161B22;
    color: #C9D1D9;
    selection-background-color: #1F6FEB;
    selection-color: #FFFFFF;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}

QPushButton {
    background-color: #21262D;
    color: #C9D1D9;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
    font-size: 12.5px;
}

QPushButton:hover {
    background-color: #30363D;
    color: #F0F6FC;
    border-color: #8B949E;
}

QPushButton:pressed {
    background-color: #161B22;
    border-color: #58A6FF;
}

QPushButton#PrimaryButton {
    background-color: #238636;
    color: #FFFFFF;
    border: 1px solid rgba(240, 246, 252, 0.12);
    padding: 8px 20px;
    font-size: 13px;
}

QPushButton#PrimaryButton:hover {
    background-color: #2EA043;
}

QPushButton#PrimaryButton:pressed {
    background-color: #196C2E;
}

QPushButton#SecondaryAction {
    background-color: #21262D;
    color: #58A6FF;
    border: 1px solid #30363D;
}

QPushButton#SecondaryAction:hover {
    background-color: rgba(56, 139, 253, 0.15);
    border-color: #58A6FF;
}

QPushButton#DangerButton {
    background-color: rgba(248, 81, 73, 0.1);
    color: #F85149;
    border: 1px solid rgba(248, 81, 73, 0.4);
}

QPushButton#DangerButton:hover {
    background-color: #DA3633;
    color: #FFFFFF;
    border-color: #DA3633;
}

QTableWidget {
    background-color: #0D1117;
    border: 1px solid #30363D;
    border-radius: 8px;
    gridline-color: #21262D;
}

QTableWidget QSpinBox {
    padding: 2px 6px;
    min-height: 22px;
    border-radius: 4px;
}

QTableWidget::item {
    padding: 4px 6px;
    border-bottom: 1px solid #21262D;
}

QTableWidget::item:selected {
    background-color: #161B22;
    color: #58A6FF;
}

QHeaderView::section {
    background-color: #161B22;
    color: #8B949E;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid #30363D;
    font-weight: 600;
    font-size: 11.5px;
}

QScrollBar:vertical {
    border: none;
    background: #0D1117;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #30363D;
    min-height: 24px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #58A6FF;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""
