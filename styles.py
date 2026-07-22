"""iOS 风格样式表"""

STYLESHEET = """
QMainWindow {
    background-color: #f0f4f8;
}

QTabWidget::pane {
    border: none;
    background: transparent;
}

QTabBar::tab {
    padding: 10px 24px;
    font-weight: 600;
    font-size: 14px;
    min-width: 120px;
    color: #718096;
    background: transparent;
    border: none;
    border-bottom: 3px solid transparent;
}

QTabBar::tab:selected {
    color: #4299e1;
    border-bottom: 3px solid #4299e1;
}

QTabBar::tab:hover:!selected {
    color: #2b6cb0;
    border-bottom: 3px solid #bee3f8;
}

QWidget {
    font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    font-size: 14px;
    color: #2d3748;
}

/* 侧边栏卡片 */
QFrame#SidebarCard {
    background-color: rgba(255, 255, 255, 0.85);
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.5);
}

/* 滚动区域透明 */
QScrollArea {
    background-color: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* 自定义滚动条 */
QScrollBar:vertical {
    background: transparent;
    width: 4px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #cbd5e0;
    border-radius: 2px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
    image: none;
}

/* 标题 */
QLabel#HeaderTitle {
    font-size: 22px;
    font-weight: 700;
    color: #1a202c;
    padding-bottom: 8px;
}

QLabel#StepTitle {
    font-size: 15px;
    font-weight: 700;
    color: #2d3748;
    margin-top: 8px;
}

/* 主按钮 - 渐变蓝 */
QPushButton#PrimaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #63b3ed, stop:1 #4299e1);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 14px 20px;
    font-weight: 600;
    font-size: 15px;
    min-height: 20px;
}
QPushButton#PrimaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #4299e1, stop:1 #3182ce);
}
QPushButton#PrimaryBtn:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #3182ce, stop:1 #2b6cb0);
}
QPushButton#PrimaryBtn:disabled {
    background: #a0aec0;
}

/* 次要按钮 - 半透明蓝 */
QPushButton#SecondaryBtn {
    background-color: rgba(66, 153, 225, 0.15);
    color: #2b6cb0;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    font-weight: 500;
    min-height: 16px;
}
QPushButton#SecondaryBtn:hover {
    background-color: rgba(66, 153, 225, 0.25);
    border: none;
}
QPushButton#SecondaryBtn:checked {
    background-color: rgba(66, 153, 225, 0.3);
    border: none;
    color: #2b6cb0;
    font-weight: 600;
}

/* 卡片标题 - 页面大标题 */
QLabel#CardTitle {
    font-size: 22px;
    font-weight: 700;
    color: #1e293b;
}

/* 卡片副标题 */
QLabel#CardSubtitle {
    color: #64748b;
    font-size: 14px;
}

/* 统计面板 */
QFrame#StatCard {
    background: #f1f5f9;
    border-radius: 6px;
    padding: 8px;
}

/* 统计数值文本 */
QLabel#StatValue {
    color: #475569;
    font-size: 13px;
    font-weight: 500;
}

/* 警告框 */
QLabel#WarningBox {
    color: #dc2626;
    font-size: 12px;
    font-weight: 600;
    padding: 6px 10px;
    background: #fef2f2;
    border-radius: 6px;
}

/* 结果卡片（剪切力面板） */
QFrame#ResultCard {
    background: #f8fafc;
    border-radius: 8px;
    padding: 4px;
}

/* 力值 / 结果数值 */
QLabel#ForceValue {
    font-size: 15px;
    font-weight: 600;
    color: #1e293b;
}

/* 徽章 (x1 / x1.25 / x2) */
QLabel#ForceBadge {
    font-weight: 700;
    font-size: 11px;
    padding: 1px 8px;
    border-radius: 4px;
}

/* 面积数值 */
QLabel#AreaValue {
    font-size: 18px;
    font-weight: 700;
    color: #1e293b;
}

/* 错误/警告文字 */
QLabel#ErrorLabel {
    color: #ef4444;
    font-size: 13px;
    font-weight: 500;
}

/* 蓝色提示文字 */
QLabel#BlueLabel {
    color: #4299e1;
    font-size: 13px;
    font-weight: 500;
}

/* 计数大号结果 */
QLabel#CountResult {
    color: #1e293b;
    font-weight: bold;
    font-size: 18px;
}

/* 全局表单输入 */
QLineEdit {
    border: 1.5px solid #cbd5e0;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 14px;
    background: white;
}
QLineEdit:focus {
    border-color: #4299e1;
}

/* 全局表格 */
QTableWidget {
    background-color: white;
    border-radius: 6px;
    border: 1px solid #e2e8f0;
    gridline-color: #f1f5f9;
    alternate-background-color: #f8fafc;
}
QHeaderView::section {
    background-color: #f8fafc;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #e2e8f0;
    font-weight: 600;
    color: #475569;
}

/* 成功按钮 - 绿色 */
QPushButton#SuccessBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #68d391, stop:1 #48bb78);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    font-weight: 600;
    min-height: 16px;
}
QPushButton#SuccessBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #48bb78, stop:1 #38a169);
}

/* 危险按钮 */
QPushButton#DangerBtn {
    background-color: rgba(245, 101, 101, 0.15);
    color: #c53030;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    font-weight: 500;
    min-height: 16px;
}
QPushButton#DangerBtn:hover {
    background-color: rgba(245, 101, 101, 0.25);
    border: none;
}

/* 滑块样式 */
QSlider::groove:horizontal {
    background: #e2e8f0;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #63b3ed, stop:1 #4299e1);
    width: 10px;
    height: 10px;
    margin: -7px 0;
    border-radius: 10px;
    border: 2px solid white;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #bee3f8, stop:1 #90cdf4);
    border-radius: 3px;
}

/* 结果框 */
QLabel#ResultBox {
    background-color: rgba(15, 23, 42, 0.9);
    color: #68d391;
    border-radius: 8px;
    padding: 16px;
    font-family: 'SF Mono', 'Consolas', 'Menlo', monospace;
    font-size: 14px;
    line-height: 1.6;
    min-height: 100px;
}

/* 信息标签 */
QLabel#InfoLabel {
    color: #4a5568;
    font-size: 13px;
    font-weight: 500;
}

QLabel#SuccessLabel {
    color: #38a169;
    font-size: 13px;
    font-weight: 600;
}

/* GroupBox */
QGroupBox {
    background-color: transparent;
    border: 1.5px solid rgba(203, 213, 224, 0.5);
    border-radius: 8px;
    margin-top: 8px;
    padding: 10px;
    font-weight: 600;
    color: #4a5568;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}

/* CheckBox */
QCheckBox {
    spacing: 8px;
    color: #4a5568;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 2px solid #cbd5e0;
    background: white;
}
QCheckBox::indicator:checked {
    background: #4299e1;
    border-color: #4299e1;
}
"""

# 对话框样式
DIALOG_STYLESHEET = """
QDialog {
    background-color: #f0f4f8;
}
"""