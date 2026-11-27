"""UI组件创建函数"""

import os

from PyQt6.QtWidgets import (QPushButton, QLabel, QSlider, QGroupBox,
                             QCheckBox, QComboBox, QFrame, QMessageBox,
                             QTableWidgetItem,
                             QVBoxLayout, QHBoxLayout, QSizePolicy, QWidget)
from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap


def confirm_action(parent, title, text):
    """破坏性操作确认；离屏/CI 环境自动确认，避免阻塞自动化测试。"""
    if (os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
            or os.environ.get('AURASCOPE_AUTO_CONFIRM') == '1'):
        return True
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes |
                           QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    yes = box.button(QMessageBox.StandardButton.Yes)
    no = box.button(QMessageBox.StandardButton.No)
    if yes is not None:
        yes.setText('确定')
        yes.setObjectName('DangerBtn')
    if no is not None:
        no.setText('取消')
        no.setObjectName('SecondaryBtn')
    return box.exec() == QMessageBox.StandardButton.Yes


def create_primary_button(text, callback=None):
    """创建主按钮"""
    btn = QPushButton(text)
    btn.setObjectName("PrimaryBtn")
    if callback:
        btn.clicked.connect(callback)
    return btn


def create_secondary_button(text, callback=None, checkable=False):
    """创建次要按钮"""
    btn = QPushButton(text)
    btn.setObjectName("SecondaryBtn")
    btn.setCheckable(checkable)
    if callback:
        btn.clicked.connect(callback)
    return btn


def create_success_button(text, callback=None):
    """创建成功按钮"""
    btn = QPushButton(text)
    btn.setObjectName("SuccessBtn")
    if callback:
        btn.clicked.connect(callback)
    return btn


def create_danger_button(text, callback=None):
    """创建危险按钮"""
    btn = QPushButton(text)
    btn.setObjectName("DangerBtn")
    if callback:
        btn.clicked.connect(callback)
    return btn


def create_nav_button(text, callback=None, checkable=True):
    """创建步骤导航按钮（左侧竖排步骤条，checked 态主色填充）"""
    btn = QPushButton(text)
    btn.setObjectName("NavBtn")
    btn.setCheckable(checkable)
    if callback:
        btn.clicked.connect(callback)
    return btn


def align_right(item):
    """表格数值列右对齐（保留垂直居中）。"""
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight |
                          Qt.AlignmentFlag.AlignVCenter)
    return item


class NumericItem(QTableWidgetItem):
    """显示原文本、按真实数值排序的表格项。"""

    def __init__(self, text, value):
        super().__init__(str(text))
        self._sort_value = float(value)

    def __lt__(self, other):
        if isinstance(other, NumericItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


_EMPTY_LOGO_SIZE = 400
_empty_logo_cache = {}


def empty_logo_pixmap(size=_EMPTY_LOGO_SIZE):
    """空画布中央的公司 logo；缩放结果缓存，避免每次重绘都重新缩放。"""
    if size not in _empty_logo_cache:
        from app_paths import resource_path
        pixmap = QPixmap(resource_path('logo.png'))
        _empty_logo_cache[size] = None if pixmap.isNull() else pixmap.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
    return _empty_logo_cache[size]


def paint_empty_state(painter, widget, dy=-40):
    """统一的空画布视觉：居中公司 logo；logo 缺失时退回一行提示。"""
    logo = empty_logo_pixmap()
    if logo is not None:
        painter.drawPixmap((widget.width() - logo.width()) // 2,
                           (widget.height() - logo.height()) // 2 + dy, logo)
        return
    from styles import _C
    painter.setPen(QColor(_C['text3']))
    painter.drawText(widget.rect(), Qt.AlignmentFlag.AlignCenter, '请先导入图片')


def enable_click_sort(table, locked=None):
    """用户点击表头后才启用排序，初始保持插入顺序。"""
    header = table.horizontalHeader()
    header.setSortIndicatorShown(True)
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    def on_click(column):
        if locked is not None and locked():
            return
        if not table.isSortingEnabled():
            table.setSortingEnabled(True)
        table.sortItems(column, header.sortIndicatorOrder())

    header.sectionClicked.connect(on_click)


class _ViewportResizeFilter(QObject):
    def __init__(self, table, sync):
        super().__init__(table)
        self.sync = sync

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self.sync()
        return False


def attach_empty_hint(table, text):
    """表内空状态提示（行数为 0 时覆盖视口居中显示）。"""
    hint = QLabel(text, table.viewport())
    hint.setObjectName('TableEmptyHint')
    hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hint.setWordWrap(True)
    hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def sync(*_args):
        try:
            hint.setGeometry(table.viewport().rect())
            hint.setVisible(table.rowCount() == 0)
        except RuntimeError:
            pass

    table._empty_hint = hint
    table._empty_hint_filter = _ViewportResizeFilter(table, sync)
    table.viewport().installEventFilter(table._empty_hint_filter)
    table.model().rowsInserted.connect(lambda *a: QTimer.singleShot(0, sync))
    table.model().rowsRemoved.connect(lambda *a: QTimer.singleShot(0, sync))
    table.model().modelReset.connect(lambda *a: QTimer.singleShot(0, sync))
    sync()
    return hint


def create_step_title(text):
    """创建步骤标题"""
    label = QLabel(text)
    label.setObjectName("StepTitle")
    return label


def create_info_label(text=""):
    """创建信息标签"""
    label = QLabel(text)
    label.setObjectName("InfoLabel")
    label.setWordWrap(True)
    return label


def create_success_label(text=""):
    """创建成功标签"""
    label = QLabel(text)
    label.setObjectName("SuccessLabel")
    label.setWordWrap(True)
    return label


def create_slider(min_val, max_val, default_val, callback=None):
    """创建滑块"""
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(min_val, max_val)
    slider.setValue(default_val)
    if callback:
        slider.valueChanged.connect(callback)
    return slider


def create_slider_with_label(min_val, max_val, default_val, callback=None):
    """创建带标签的滑块"""
    slider = create_slider(min_val, max_val, default_val, callback)
    label = create_info_label(str(default_val))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFixedHeight(20)
    return slider, label


def create_checkbox(text, checked=False, callback=None):
    """创建复选框"""
    cb = QCheckBox(text)
    cb.setChecked(checked)
    if callback:
        cb.toggled.connect(callback)
    return cb


def create_groupbox(title):
    """创建分组框"""
    gb = QGroupBox(title)
    gb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return gb


def create_divider():
    """创建 1px 分割线（token 描边色）"""
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    line.setFixedHeight(1)
    return line


def create_card_title(text):
    """创建卡片大标题"""
    label = QLabel(text)
    label.setObjectName("CardTitle")
    return label


def create_card_subtitle(text):
    """创建卡片副标题"""
    label = QLabel(text)
    label.setObjectName("CardSubtitle")
    return label


def create_stat_value(text=""):
    """创建统计数值标签"""
    label = QLabel(text)
    label.setObjectName("StatValue")
    return label


def create_success_value(text=""):
    """创建成功语义的大号数值标签（等宽 17px）"""
    label = QLabel(text)
    label.setObjectName("SuccessValue")
    return label


def create_error_value(text=""):
    """创建错误语义的大号数值标签（等宽 17px）"""
    label = QLabel(text)
    label.setObjectName("ErrorValue")
    return label


def create_warning_box(text=""):
    """创建警告框"""
    label = QLabel(text)
    label.setObjectName("WarningBox")
    label.setWordWrap(True)
    return label


def create_error_label(text=""):
    """创建错误标签"""
    label = QLabel(text)
    label.setObjectName("ErrorLabel")
    label.setWordWrap(True)
    return label


def create_blue_label(text=""):
    """创建蓝色提示标签"""
    label = QLabel(text)
    label.setObjectName("BlueLabel")
    label.setWordWrap(True)
    return label


def create_count_result(text=""):
    """创建计数大号结果标签"""
    label = QLabel(text)
    label.setObjectName("CountResult")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


class CollapsibleSection(QWidget):
    """可折叠区域：头部为标题+方向箭头，点击整行切换，内容随状态显示。"""
    def __init__(self, title="高级设置", parent=None):
        super().__init__(parent)
        self._title = title
        self._expanded = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName("CollapseHeader")
        self.toggle_btn.setCheckable(False)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggle_btn.setStyleSheet(
            "QPushButton#CollapseHeader {"
            "  background: transparent;"
            "  border: 1px solid transparent;"
            "  border-radius: 6px;"
            "  color: #334155;"
            "  font-weight: 600;"
            "  text-align: left;"
            "  padding: 8px 10px;"
            "}"
            "QPushButton#CollapseHeader:hover { background: #e8edf4; }"
            "QPushButton#CollapseHeader:pressed { background: #dde5ef; }"
            "QPushButton#CollapseHeader:focus { border: 1px solid #3b82f6; }")
        self.toggle_btn.clicked.connect(self.toggle)
        layout.addWidget(self.toggle_btn)

        self.container = QWidget()
        self.container.setObjectName("CollapseBody")
        self._container_layout = QVBoxLayout(self.container)
        self._container_layout.setContentsMargins(10, 8, 10, 10)
        self._container_layout.setSpacing(6)
        layout.addWidget(self.container)

        self.setExpanded(False)

    def _refresh_header(self):
        arrow = '▼' if self._expanded else '▲'
        self.toggle_btn.setText(f"{arrow}  {self._title}")
        self.toggle_btn.setAccessibleName(self._title)

    def setExpanded(self, expanded):
        self._expanded = bool(expanded)
        self._refresh_header()
        self.container.setVisible(self._expanded)

    def toggle(self):
        self.setExpanded(not self._expanded)

    def isExpanded(self):
        return self._expanded

    def addWidget(self, widget):
        self._container_layout.addWidget(widget)

    def addLayout(self, layout):
        self._container_layout.addLayout(layout)


def create_tool_buttons():
    """创建工具栏按钮组"""
    layout = QHBoxLayout()
    
    btn_poly = create_secondary_button("多边形框选", checkable=True)
    btn_rect = create_secondary_button("矩形框+阈值", checkable=True)
    
    layout.addWidget(btn_poly)
    layout.addWidget(btn_rect)
    
    return layout, btn_poly, btn_rect

def copy_bgr_to_clipboard(img, silent=True):
    """把 OpenCV 图像（BGR / 灰度 / BGRA numpy）复制到系统剪贴板

    各功能公用（金锡拼接图导出、拼接 tab 等 ✗）。返回 (是否成功, 失败原因) ✔
    """
    if img is None:
        return False, '没有图像'
    try:
        import numpy as np
        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QApplication
        a = img
        if a.ndim == 2:                       # 灰度 → RGB
            a = np.repeat(a[:, :, None], 3, axis=2)
        elif a.shape[2] == 4:                 # BGRA → BGR
            a = a[:, :, :3]
        rgb = np.ascontiguousarray(a[:, :, ::-1])          # BGR → RGB
        h, w = rgb.shape[:2]
        # .copy() 让 QImage 自己持有数据（否则 numpy 释放后花屏 ✗）
        q = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        cb = QApplication.clipboard()
        if cb is None:
            return False, '剪贴板不可用'
        cb.setImage(q)
        return True, ''
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


class ChevronComboBox(QComboBox):
    """带自绘箭头的下拉框。

    QSS 里 `::drop-down` 一旦被样式覆盖，Qt 就不画原生箭头；
    而 CSS 三角又不支持 → 端盖会变成一块空白。这里在 paintEvent 里
    补一个小 chevron，颜色取 text2，禁用时取 text3。
    """

    def paintEvent(self, event):
        super().paintEvent(event)
        from styles import _C
        color = QColor(_C['text3'] if not self.isEnabled() else _C['text2'])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color)
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - 11.0      # 端盖宽 22px 的中心
        cy = self.height() / 2.0
        painter.drawPolyline([QPointF(cx - 4.0, cy - 2.0),
                              QPointF(cx, cy + 2.2),
                              QPointF(cx + 4.0, cy - 2.0)])
        painter.end()


def create_combo(items=None, parent=None):
    """下拉框工厂：统一使用带箭头自绘的实现。"""
    combo = ChevronComboBox(parent)
    if items:
        combo.addItems(list(items))
    return combo


def style_combo_popups(widget):
    """把下拉弹层的样式直接套到每个 QComboBox 的视图上

    为什么必须这么做 ✗：QComboBox 的弹层是**独立弹出窗口** ✗，
    全局 QSS 的 `QComboBox QAbstractItemView{…}` 在某些风格下命中不了 ✗
    → 会露出原生的灰框选中项、滚动条箭头、裁切 ✗
    直接 setStyleSheet 到 view() 上是唯一 100% 生效的写法 ✔
    """
    from PyQt6.QtWidgets import QComboBox
    from styles import POPUP_QSS
    try:
        combos = widget.findChildren(QComboBox)
    except Exception:
        return 0
    # 原生焦点框（选中项外面那圈灰线 ✗）是 Qt style 画的 ✗ QSS 管不到
    # → 用委托把 State_HasFocus 去掉 ✔
    from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle

    class _NoFocusDelegate(QStyledItemDelegate):
        def paint(self, painter, option, index):
            opt = QStyleOptionViewItem(option)
            opt.state &= ~QStyle.StateFlag.State_HasFocus
            super().paint(painter, opt, index)

    for cb in combos:
        try:
            cb.setItemDelegate(_NoFocusDelegate(cb))
            cb.view().setStyleSheet(POPUP_QSS)
            n = cb.count()
            if n:
                # 高度 = 内容 + 弹层自身 chrome（POPUP_QSS 的 padding 2px×2 + 边框 1px×2）
                # 少算这几个像素 → 视口比内容矮 → Qt 认为要滚动，
                # 弹层底部就会多出一条 QComboBoxPrivateScroller（灰条 + 小箭头）
                row = cb.view().sizeHintForRow(0)
                if row and row > 0:
                    cb.view().setFixedHeight(min(n, 12) * row + 6)
                else:
                    cb.view().setMinimumHeight(min(n, 12) * 27 + 10)
        except Exception:
            pass
    return len(combos)


class WindowControlButton(QPushButton):
    """无边框窗口的标题栏按钮：最小化 / 最大化（还原）/ 关闭。

    图形用 QPainter 自绘，不拿 ⛶ ✕ 这类字符当图标——
    否则不同 Windows 字体下粗细和基线会飘。
    """

    _LABEL = {'min': '最小化', 'max': '最大化', 'close': '关闭'}

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._maximized = False
        self.setObjectName('WinBtnClose' if kind == 'close' else 'WinBtn')
        self.setFixedSize(46, 32)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sync_hint()

    def _sync_hint(self):
        text = '还原' if (self.kind == 'max' and self._maximized) \
            else self._LABEL[self.kind]
        self.setAccessibleName(text)
        self.setToolTip(text)

    def set_maximized(self, value):
        value = bool(value)
        if value != self._maximized:
            self._maximized = value
            self._sync_hint()
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        from styles import _C
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = self.underMouse() or self.isDown()
        color = '#FFFFFF' if (self.kind == 'close' and hovered) else _C['text2']
        pen = QPen(QColor(color))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        center = self.rect().center()
        cx, cy = center.x() + 0.5, center.y() + 0.5
        half = 5.0
        if self.kind == 'min':
            painter.drawLine(QPointF(cx - half, cy), QPointF(cx + half, cy))
        elif self.kind == 'max':
            if self._maximized:
                painter.drawRect(QRectF(cx - half + 1.5, cy - half,
                                        2 * half - 1.5, 2 * half - 1.5))
                painter.drawLine(QPointF(cx - half, cy - half + 1.5),
                                 QPointF(cx - half, cy + half))
                painter.drawLine(QPointF(cx - half, cy - half + 1.5),
                                 QPointF(cx + half - 1.5, cy - half + 1.5))
            else:
                painter.drawRect(QRectF(cx - half, cy - half, 2 * half, 2 * half))
        else:
            painter.drawLine(QPointF(cx - half, cy - half),
                             QPointF(cx + half, cy + half))
            painter.drawLine(QPointF(cx + half, cy - half),
                             QPointF(cx - half, cy + half))


class TitleBar(QFrame):
    """自绘窗口标题栏：品牌 + 「文件 / 帮助」菜单 + 窗口控制。

    替代系统标题栏：一整行 40px，菜单和最小化/最大化/关闭都内嵌在应用里，
    不再出现「系统标题栏 + 菜单栏」两行。拖动走 startSystemMove()，
    双击走最大化/还原（不抢双击事件）。
    """

    def __init__(self, window, title, version='', logo=None, parent=None):
        super().__init__(parent)
        self.setObjectName('TitleBar')
        self.setFixedHeight(40)
        self._window = window
        self._press_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)

        if logo is not None and not logo.isNull():
            mark = QLabel()
            mark.setPixmap(logo.scaledToHeight(
                18, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(mark)

        name = QLabel(title)
        name.setObjectName('TitleBarName')
        layout.addWidget(name)
        if version:
            version_label = QLabel(version)
            version_label.setObjectName('AppVersion')
            layout.addWidget(version_label)
        layout.addSpacing(16)

        self._menu_layout = QHBoxLayout()
        self._menu_layout.setSpacing(2)
        layout.addLayout(self._menu_layout)
        layout.addStretch()

        self.btn_min = WindowControlButton('min')
        self.btn_max = WindowControlButton('max')
        self.btn_close = WindowControlButton('close')
        self.btn_min.clicked.connect(self._window.showMinimized)
        self.btn_max.clicked.connect(self.toggle_maximize)
        self.btn_close.clicked.connect(self._window.close)
        for button in (self.btn_min, self.btn_max, self.btn_close):
            layout.addWidget(button)

    def add_menu(self, text, menu):
        """在品牌右侧挂一个菜单按钮（弹层位置交给 QPushButton 自己算）。"""
        button = QPushButton(text)
        button.setObjectName('MenuButton')
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setMenu(menu)
        self._menu_layout.addWidget(button)
        return button

    def set_maximized(self, value):
        self.btn_max.set_maximized(value)

    def toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.set_maximized(self._window.isMaximized())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 按下后位移超过 4px 才交给系统拖动：否则双击最大化会被抢掉
        if (self._press_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            moved = event.globalPosition().toPoint() - self._press_pos
            if moved.manhattanLength() > 4:
                self._press_pos = None
                handle = self._window.windowHandle()
                if handle is not None:
                    handle.startSystemMove()
                    return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximize()
            return
        super().mouseDoubleClickEvent(event)
