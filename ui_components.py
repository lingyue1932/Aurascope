"""UI组件创建函数"""

from PyQt6.QtWidgets import (QPushButton, QLabel, QSlider, QGroupBox, 
                             QCheckBox, QVBoxLayout, QHBoxLayout, QSizePolicy)
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


def create_tool_buttons():
    """创建工具栏按钮组"""
    layout = QHBoxLayout()
    
    btn_poly = create_secondary_button("多边形框选", checkable=True)
    btn_rect = create_secondary_button("矩形框+阈值", checkable=True)
    
    layout.addWidget(btn_poly)
    layout.addWidget(btn_rect)
    
    return layout, btn_poly, btn_rect