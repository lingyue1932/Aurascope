# -*- coding: utf-8 -*-
"""Aurascope 全局样式表（QSS）

设计规范（按 UI 设计系统技能落地 ✗ QSS 不支持变量，这里用**注释为契约**，
所有取值必须从下面这套 token 里来，不允许再随手写颜色 ✗）

■ 中性色（唯一一套灰阶，替代原来 8 种混用的灰 ✗）
    bg          #F4F6FA    页面底
    surface     #FFFFFF    卡片/表格/输入框
    surface-2   #F8FAFC    表头、次级面
    border      #E6EAF0    常规描边
    border-2    #D6DCE6    强描边/悬停
    text        #1B2333    主文字
    text-2      #5A6478    次级文字
    text-3      #8B94A6    弱文字/占位
■ 主色（清透蓝 ✗ 与 INNO LIGHT 品牌一致）
    accent      #2563EB    hover #1D4ED8    active #1E40AF    tint rgba(37,99,235,.10)
■ 语义色
    success #16A34A   danger #DC2626   warning #B45309
■ 字阶（6 级，不再出现 11/12/13/14/15/18/22 一堆 ✗）
    11 caption-2 · 12 caption · 14 body · 15 title-sm · 18 title · 24 page
■ 8pt 间距：4 / 8 / 12 / 16 / 24 (padding 用 6·8·10·12·14·16 ✗ 尽量落在网格上)
■ 圆角：6 小标签 · 8 输入/小件 · 10 按钮 · 12 卡片 · 999 胶囊
■ 交互态：每种控件都要有 default / hover / pressed / checked / disabled / focus
"""

# ─────────────────────────────────────────────────────────── 设计 token（勿散写）
_C = {
    'bg': '#F4F6FA', 'surface': '#FFFFFF', 'surface2': '#F8FAFC',
    'border': '#DCE3EC', 'border2': '#C8D2E0',
    'text': '#1B2333', 'text2': '#4E5A70', 'text3': '#7D879B',
    'accent': '#2563EB', 'accent_h': '#1D4ED8', 'accent_a': '#1E40AF',
    'accent_tint': 'rgba(37, 99, 235, 0.10)',
    'accent_tint2': 'rgba(37, 99, 235, 0.18)',
    'success': '#16A34A', 'success_h': '#15803D', 'success_a': '#166534',
    'danger': '#DC2626', 'danger_h': '#B91C1C',
    'warning': '#B45309',
    'font': "Bahnschrift, 'Segoe UI Variable Display', 'Segoe UI', "
            "'PingFang SC', 'Microsoft YaHei', sans-serif",
    'font_ui': "-apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    'mono': "'Cascadia Mono', Consolas, 'SF Mono', Menlo, monospace",
}


def _sheet() -> str:
    c = _C
    return f"""
/* ══════════════════════════ 基础容器 ══════════════════════════ */
QMainWindow, QDialog {{ background: {c['bg']}; }}
QWidget {{
    font-family: {c['font_ui']};
    font-size: 14px;
    color: {c['text']};
}}
QToolTip {{
    background: {c['text']};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* ══════════════════════════ 顶部标签页 ══════════════════════════ */
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    padding: 10px 20px;
    margin-right: 4px;
    font-size: 14px;
    font-weight: 600;
    min-width: 104px;
    color: {c['text2']};
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover:!selected {{ color: {c['accent']}; }}
QTabBar::tab:selected {{
    color: {c['accent']};
    border-bottom: 2px solid {c['accent']};
}}
QTabBar::tab:disabled {{ color: {c['text3']}; }}

/* ══════════════════════════ 顶部菜单栏（系统细条） ══════════════════════════ */
QMenuBar {{
    background: {c['surface2']};
    border-bottom: 1px solid {c['border']};
    padding: 0 8px;
    min-height: 28px;
}}
QMenuBar::item {{
    background: transparent; color: {c['text2']};
    padding: 6px 10px; border-radius: 4px; font-size: 12px;
}}
QMenuBar::item:selected {{ background: {c['accent_tint']}; color: {c['accent']}; }}
QMenuBar::item:pressed {{ background: {c['accent_tint2']}; color: {c['accent']}; }}

/* ══════════════════════════ 自绘标题栏（替代系统标题栏） ══════════════════════════ */
QFrame#TitleBar {{
    background: {c['surface2']};
    border-bottom: 1px solid {c['border']};
}}
QLabel#TitleBarName {{ font-size: 14px; font-weight: 700; color: {c['text']}; }}
QPushButton#MenuButton {{
    background: transparent; color: {c['text2']};
    border: none; border-radius: 6px;
    padding: 5px 10px; font-size: 14px;
}}
QPushButton#MenuButton:hover {{ background: {c['accent_tint']}; color: {c['accent']}; }}
QPushButton#MenuButton:pressed {{ background: {c['accent_tint2']}; }}
QPushButton#MenuButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#WinBtn {{ background: transparent; border: none; border-radius: 0; }}
QPushButton#WinBtn:hover {{ background: {c['border']}; }}
QPushButton#WinBtn:pressed {{ background: {c['border2']}; }}
QPushButton#WinBtnClose {{ background: transparent; border: none; border-radius: 0; }}
QPushButton#WinBtnClose:hover {{ background: {c['danger']}; }}
QPushButton#WinBtnClose:pressed {{ background: #B91C1C; }}

/* ══════════════════════════ 应用页头（品牌 + 模块导航） ══════════════════════════ */
QFrame#AppHeader {{
    background: {c['surface']};
    border-bottom: 1px solid {c['border']};
}}
QLabel#AppName {{
    font-size: 16px; font-weight: 700; color: {c['text']};
}}
QLabel#AppVersion {{
    font-size: 11px; color: {c['text3']}; padding-top: 2px;
}}
QPushButton#ModuleTab {{
    background: transparent; color: {c['text2']};
    border: none; border-bottom: 2px solid transparent;
    padding: 0 12px; min-height: 54px;
    font-size: 14px; font-weight: 600;
}}
QPushButton#ModuleTab:hover {{
    background: {c['accent_tint']}; color: {c['accent']};
}}
QPushButton#ModuleTab:pressed {{ background: {c['accent_tint2']}; }}
QPushButton#ModuleTab:checked {{
    color: {c['accent']}; border-bottom: 2px solid {c['accent']};
}}
QPushButton#ModuleTab:focus {{ outline: none; }}

/* ══════════════════════════ 卡片 / 面板 ══════════════════════════ */
QFrame#SidebarCard {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 12px;
}}
QFrame#ResultCard {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    padding: 8px;
}}
QFrame#StatCard {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 10px;
}}
/* 代码里用了但原来没给样式 ✗ → 补上（次级内嵌面板） */
QFrame#InnerCard {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 10px;
}}
/* 1px 分割线（替代页面里手写 HLine + 散写颜色） */
QFrame#Divider {{
    background: {c['border']};
    border: none;
    max-height: 1px;
}}

/* ══════════════════════════ 文字层级（6 级） ══════════════════════════ */
QLabel#HeaderTitle {{
    font-size: 24px; font-weight: 700; color: {c['text']}; padding-bottom: 6px;
}}
QLabel#CardTitle {{ font-size: 18px; font-weight: 700; color: {c['text']}; }}
QLabel#CardSubtitle {{ font-size: 12px; color: {c['text2']}; }}
QLabel#StepTitle {{
    font-size: 15px; font-weight: 600; color: {c['text']}; margin-top: 6px;
}}
QLabel#InfoLabel {{ font-size: 12px; color: {c['text2']}; }}
QLabel#BlueLabel {{ font-size: 12px; font-weight: 600; color: {c['accent']}; }}
QLabel#SuccessLabel {{ font-size: 12px; font-weight: 600; color: {c['success']}; }}
QLabel#ErrorLabel {{ font-size: 12px; font-weight: 600; color: {c['danger']}; }}
QLabel#WarningBox {{
    font-size: 12px; font-weight: 600; color: {c['warning']};
    background: #FFFBEB; border: 1px solid #FDE68A;
    border-radius: 8px; padding: 6px 10px;
}}
QLabel#StatValue {{ font-size: 12px; font-weight: 500; color: {c['text2']}; }}
QLabel#ForceValue {{
    font-family: {c['mono']}; font-size: 17px; font-weight: 600; color: {c['text']};
}}
QLabel#SuccessValue {{
    font-family: {c['mono']}; font-size: 17px; font-weight: 600; color: {c['success']};
}}
QLabel#ErrorValue {{
    font-family: {c['mono']}; font-size: 17px; font-weight: 600; color: {c['danger']};
}}
QLabel#ImagePreview {{
    background: {c['surface']}; border: 1px solid {c['border']};
    border-radius: 8px; padding: 4px;
}}
/* 底部轻提示 */
QLabel#Toast {{
    background: rgba(27, 35, 51, 0.92); color: #FFFFFF;
    border-radius: 8px; padding: 8px 14px; font-size: 12px;
}}
/* 空表格引导 */
QLabel#TableEmptyHint {{
    color: {c['text3']}; font-size: 12px; background: transparent;
}}
QLabel#AreaValue, QLabel#CountResult {{
    font-family: {c['mono']}; font-size: 21px; font-weight: 700; color: {c['accent_a']};
}}
QLabel#ForceBadge {{
    font-family: {c['mono']};
    font-size: 11px; font-weight: 700; color: {c['accent']};
    background: {c['accent_tint']}; border-radius: 6px; padding: 1px 8px;
}}
QLabel#ResultBox {{
    background: #0F172A; color: #7EE2A8;
    border: 1px solid #1E293B; border-radius: 10px; padding: 14px;
    font-family: {c['mono']}; font-size: 13px; min-height: 96px;
}}

/* ══════════════════════════ 按钮（扁平 + 全套状态 ✗ 去掉渐变 ✗）══════════════ */
/* 主按钮 */
QPushButton#PrimaryBtn {{
    background: {c['accent']}; color: #FFFFFF;
    border: none; border-radius: 10px;
    padding: 9px 16px; font-size: 14px; font-weight: 600; min-height: 20px;
}}
QPushButton#PrimaryBtn:hover {{ background: {c['accent_h']}; }}
QPushButton#PrimaryBtn:pressed {{ background: {c['accent_a']}; padding-top: 10px; padding-bottom: 8px; }}
QPushButton#PrimaryBtn:disabled {{ background: #C7D2E4; color: #FFFFFF; }}
QPushButton#PrimaryBtn:focus {{ outline: none; border: 2px solid {c['accent_a']}; }}

/* 次要按钮（浅底填充，不是描边 ✗ 保持图标化轻量） */
QPushButton#SecondaryBtn {{
    background: {c['accent_tint']}; color: {c['accent_a']};
    border: 1px solid transparent; border-radius: 10px;
    padding: 9px 16px; font-size: 14px; font-weight: 500; min-height: 20px;
}}
QPushButton#SecondaryBtn:hover {{
    background: {c['accent_tint2']}; border-color: rgba(37, 99, 235, 0.25);
}}
QPushButton#SecondaryBtn:pressed {{ background: rgba(37, 99, 235, 0.28); }}
QPushButton#SecondaryBtn:checked {{
    background: {c['accent']}; color: #FFFFFF; font-weight: 600;
    border-color: {c['accent']};
}}
QPushButton#SecondaryBtn:disabled {{
    background: #F1F3F8; color: {c['text3']}; border-color: transparent;
}}

/* 成功按钮 */
QPushButton#SuccessBtn {{
    background: {c['success']}; color: #FFFFFF;
    border: none; border-radius: 10px;
    padding: 9px 16px; font-size: 14px; font-weight: 600; min-height: 20px;
}}
QPushButton#SuccessBtn:hover {{ background: {c['success_h']}; }}
QPushButton#SuccessBtn:pressed {{ background: {c['success_a']}; }}
QPushButton#SuccessBtn:disabled {{ background: #BEDFC8; color: #FFFFFF; }}

/* 危险按钮 */
QPushButton#DangerBtn {{
    background: rgba(220, 38, 38, 0.10); color: {c['danger']};
    border: 1px solid transparent; border-radius: 10px;
    padding: 9px 16px; font-size: 14px; font-weight: 500; min-height: 20px;
}}
QPushButton#DangerBtn:hover {{
    background: rgba(220, 38, 38, 0.16); border-color: rgba(220, 38, 38, 0.25);
}}
QPushButton#DangerBtn:pressed {{ background: rgba(220, 38, 38, 0.24); }}
QPushButton#DangerBtn:disabled {{ background: #F4F5F8; color: {c['text3']}; }}

/* 步骤导航按钮（左侧竖排步骤条，checked = 当前步骤） */
QPushButton#NavBtn {{
    background: transparent; color: {c['text2']};
    border: 1px solid transparent; border-radius: 10px;
    padding: 7px 10px; font-size: 12px; font-weight: 600;
    text-align: left;
}}
QPushButton#NavBtn:hover {{ background: {c['accent_tint']}; color: {c['accent']}; }}
QPushButton#NavBtn:pressed {{ background: {c['accent_tint2']}; }}
QPushButton#NavBtn:checked {{
    background: {c['accent']}; color: #FFFFFF; border-color: {c['accent']};
}}
QPushButton#NavBtn:focus {{ border: 1px solid {c['accent']}; }}
QPushButton#NavBtn:disabled {{ color: {c['text3']}; }}

/* 结果缩略图（可选中；warn=true 表示该图有警告） */
QToolButton#ThumbBtn {{
    background: {c['surface']}; color: {c['text2']};
    border: 2px solid {c['border']}; border-radius: 8px; padding: 2px;
}}
QToolButton#ThumbBtn:hover {{ border-color: {c['accent']}; }}
QToolButton#ThumbBtn:checked {{
    border-color: {c['accent']}; background: {c['accent_tint']};
}}
QToolButton#ThumbBtn[warn="true"] {{ border-color: {c['warning']}; }}
QToolButton#ThumbBtn[warn="true"]:checked {{ border-color: {c['accent']}; }}

/* ══════════════════════════ 输入类 ══════════════════════════ */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {c['surface']};
    border: 1px solid {c['border2']};
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 14px;
    color: {c['text']};
    selection-background-color: {c['accent']};
    selection-color: #FFFFFF;
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{ border-color: #BFC8D8; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {c['accent']}; padding: 6px 9px;
}}
QLineEdit:disabled, QTextEdit:disabled {{ background: #F1F3F8; color: {c['text3']}; }}
QLineEdit[readOnly="true"] {{ background: {c['surface2']}; color: {c['text2']}; }}

QComboBox {{
    background: {c['surface']};
    border: 1px solid {c['border2']};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 14px;
    min-height: 20px;
    color: {c['text']};
}}
QComboBox:hover {{ border-color: #BFC8D8; }}
QComboBox:focus {{ border: 2px solid {c['accent']}; padding: 5px 9px; }}
QComboBox:disabled {{ background: #F1F3F8; color: {c['text3']}; }}
/* ⚠ Qt 不支持 CSS 三角（border trick ✗）→ 会渲染成一块黑 ✗
   下拉区改成"浅色端盖"作为可点击线索，不再画箭头 ✔ */
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: top right;
    border: none; width: 22px;
    border-left: 1px solid {c['border']};
    background: {c['surface2']};
    border-top-right-radius: 8px; border-bottom-right-radius: 8px;
}}
QComboBox QAbstractItemView {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 0px;
    padding: 4px;
    outline: none;
    selection-background-color: {c['accent_tint']};
    selection-color: {c['accent_a']};
}}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 3px 8px; border-radius: 6px; }}

QSpinBox, QDoubleSpinBox {{
    background: {c['surface']};
    border: 1px solid {c['border2']};
    border-radius: 8px; padding: 6px 8px; font-size: 14px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {c['accent']}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 16px; border: none; background: transparent;
}}
/* ⚠ Qt 不支持 CSS 三角（border trick ✗）→ 会渲染成一块黑 ✗
   所以这里把上下按钮宽度置 0 隐藏：数字框靠输入/滚轮修改，视觉上干净 ✔ */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: none; width: 0; height: 0; }}

QCheckBox, QRadioButton {{
    spacing: 8px; font-size: 13px; color: {c['text2']};
}}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 6px;
    border: 1.5px solid {c['border2']}; background: {c['surface']};
}}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{
    background: {c['accent']}; border-color: {c['accent']};
}}
QCheckBox::indicator:disabled {{ background: #F1F3F8; border-color: {c['border']}; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 9px;
    border: 1.5px solid {c['border2']}; background: {c['surface']};
}}
QRadioButton::indicator:checked {{
    background: {c['accent']}; border: 5px solid {c['surface']};
    outline: 1.5px solid {c['accent']};
}}

QPushButton {{
    font-size: 14px;
}}

/* ══════════════════════════ 表格（补 hover / 选中态 ✗ 结果表最常看）══════════════ */
QTableWidget, QTableView {{
    background: {c['surface']};
    alternate-background-color: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    gridline-color: {c['border']};
    selection-background-color: {c['accent_tint']};
    selection-color: {c['accent_a']};
    font-family: {c['mono']};
    font-size: 13px;
}}
QTableWidget::item, QTableView::item {{ padding: 6px 8px; border: none; }}
QTableWidget::item:hover, QTableView::item:hover {{ background: #F5F8FF; }}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {c['accent_tint2']}; color: {c['accent_a']};
}}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {c['surface2']};
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {c['border']};
    border-right: 1px solid {c['border']};
    font-size: 13px; font-weight: 600; color: {c['text2']};
}}
QHeaderView::section:hover {{ background: #EEF2FA; color: {c['accent']}; }}
QTableCornerButton::section {{ background: {c['surface2']}; border: none; }}

/* ══════════════════════════ 列表 / 树 / 菜单 ══════════════════════════ */
QListWidget, QListView, QTreeWidget, QTreeView {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    outline: none;
    font-size: 13px;
    selection-background-color: {c['accent_tint']};
    selection-color: {c['accent_a']};
}}
QListWidget::item, QListView::item, QTreeWidget::item {{ padding: 5px 8px; border-radius: 6px; }}
QListWidget::item:hover, QListView::item:hover {{ background: #F5F8FF; }}
QListWidget::item:selected, QListView::item:selected {{
    background: {c['accent_tint2']}; color: {c['accent_a']};
}}
QMenu {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{ padding: 7px 14px; border-radius: 8px; font-size: 13px; }}
QMenu::item:selected {{ background: {c['accent_tint']}; color: {c['accent_a']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}

/* ══════════════════════════ 进度 / 滑块 ══════════════════════════ */
QProgressBar {{
    background: #EDF1F7;
    border: none; border-radius: 6px;
    height: 12px; text-align: center;
    font-size: 11px; color: {c['text2']};
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 6px; }}

QSlider::groove:horizontal {{ background: #E3E8F0; height: 6px; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {c['surface']}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 8px;
    border: 2px solid {c['accent']};
}}
QSlider::handle:horizontal:hover {{ border-color: {c['accent_h']}; }}
QSlider::handle:horizontal:pressed {{ background: {c['accent_tint2']}; }}
QSlider::groove:horizontal:disabled {{ background: #EDF1F7; }}
QSlider::sub-page:horizontal:disabled {{ background: #C7D2E4; }}
QSlider::handle:horizontal:disabled {{ background: #F1F3F8; border-color: #C7D2E4; }}
QSlider::groove:vertical {{ background: #E3E8F0; width: 6px; border-radius: 3px; }}
QSlider::add-page:vertical {{ background: {c['accent']}; border-radius: 3px; }}
QSlider::handle:vertical {{
    background: {c['surface']}; width: 14px; height: 14px;
    margin: 0 -5px; border-radius: 8px; border: 2px solid {c['accent']};
}}

/* ══════════════════════════ 滚动条（补水平方向 ✗ 加宽到能抓 ✗）══════════════ */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 2px 2px 0; }}
QScrollBar::handle:vertical {{
    background: #C9D2E0; border-radius: 4px; min-height: 28px; margin: 0 2px;
}}
QScrollBar::handle:vertical:hover {{ background: #A9B4C6; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0 2px 2px 2px; }}
QScrollBar::handle:horizontal {{
    background: #C9D2E0; border-radius: 4px; min-width: 28px; margin: 2px 0;
}}
QScrollBar::handle:horizontal:hover {{ background: #A9B4C6; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: none; }}
QScrollBar::up-arrow, QScrollBar::down-arrow,
QScrollBar::left-arrow, QScrollBar::right-arrow {{ image: none; width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ══════════════════════════ 其它 ══════════════════════════ */
/* 折叠分组展开后的内容卡片：与 Tab1 QGroupBox 同一套边框/圆角 */
QWidget#CollapseBody {{
    background: transparent;
    border: 1px solid {c['border']};
    border-radius: 10px;
}}
QGroupBox {{
    background: transparent;
    border: 1px solid {c['border']};
    border-radius: 10px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    font-size: 13px; font-weight: 600; color: {c['text2']};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}

/* 分隔条：默认**透明留缝**（不画灰条 ✗），只在悬停/拖动时给一点提示 ✔ */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 6px; margin: 0; }}
QSplitter::handle:horizontal:hover {{ background: {c['border']}; }}
QSplitter::handle:horizontal:pressed {{ background: {c['accent']}; }}
QSplitter::handle:vertical {{ height: 6px; margin: 0; }}
QSplitter::handle:vertical:hover {{ background: {c['border']}; }}
QSplitter::handle:vertical:pressed {{ background: {c['accent']}; }}

QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['border']}; }}
QStatusBar::item {{ border: none; }}
"""


STYLESHEET = _sheet()

# 对话框样式（与主界面同一套 token ✗）
DIALOG_STYLESHEET = f"QDialog {{ background-color: {_C['bg']}; }}"

# 下拉弹层样式（弹层是独立窗口，全局 QSS 命中不了，需单独应用 ✗）
POPUP_QSS = (
    # 弹层是独立窗口，Windows 会再套一层原生方角边框（QSS 管不到，
    # 去掉圆角避免出现“方框套圆角卡片”的双层边框
    "QComboBox QAbstractItemView {"
    f"    background: {_C['surface']};"
    f"    color: {_C['text']};"
    f"    border: 1px solid {_C['border']};"
    "    border-radius: 0px;"
    "    padding: 2px;"
    "    outline: none;"
    f"    selection-background-color: {_C['accent_tint']};"
    "}"
    "QListView::item {"
    "    min-height: 24px;"
    "    padding: 3px 10px;"
    "    border: none;"
    "    outline: none;"
    "    background: transparent;"
    "}"
    f"QListView::item:hover {{ background: {_C['surface2']}; }}"
    f"QListView::item:selected {{ background: {_C['accent_tint']}; color: {_C['accent']}; }}"
    "QListView {"
    "    border: none;"
    "    outline: none;"
    "}"
    "QListView:focus { outline: none; }"
    "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }"
    "QScrollBar::handle:vertical {"
    f"    background: {_C['border2']}; border-radius: 4px; min-height: 20px;"
    "}"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
    "    height: 0; width: 0; background: none;"
    "}"
    "QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {"
    "    image: none; width: 0; height: 0;"
    "}"
)
