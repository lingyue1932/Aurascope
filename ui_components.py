"""UI组件创建函数"""

from PyQt6.QtWidgets import (QPushButton, QLabel, QSlider, QGroupBox, 
                             QCheckBox, QVBoxLayout, QHBoxLayout, QSizePolicy,
                             QWidget)
from PyQt6.QtCore import Qt


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
    """可折叠区域组件"""
    def __init__(self, title="高级设置", parent=None):
        super().__init__(parent)
        self._toggled = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toggle_btn = QPushButton(f"{title}")
        self.toggle_btn.setObjectName("SecondaryBtn")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self._toggle)
        layout.addWidget(self.toggle_btn)

        self.container = QWidget()
        self.container.setVisible(False)
        self._container_layout = QVBoxLayout(self.container)
        self._container_layout.setContentsMargins(8, 8, 8, 4)
        self._container_layout.setSpacing(8)
        layout.addWidget(self.container)

    def _toggle(self):
        self._toggled = not self._toggled
        self.container.setVisible(self._toggled)
        # self.toggle_btn.setText(f"▾ {self.toggle_btn.text()[2:]}" if self._toggled else f"{self.toggle_btn.text()[2:]}")

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
