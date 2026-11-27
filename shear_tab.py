"""预覆金锡剪切力计算器Tab — 参考MIL-STD-883H Method 2019.9"""

import math

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QScrollArea, QLabel, QLineEdit, QGridLayout,
                             QSizePolicy, QApplication)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDoubleValidator

from styles import _C
from ui_components import (create_primary_button, create_secondary_button,
                           create_step_title, create_card_title,
                           create_card_subtitle, create_combo,
                           create_stat_value, create_warning_box,
                           create_info_label)


MM2_PER_IN2 = 645.16
MAX_AREA_IN2 = 64e-4
WARN_AREA_IN2 = 5e-4
FORCE_FACTOR = 0.04 / 0.0001


class ShearTab(QWidget):

    def __init__(self):
        super().__init__()
        self._force_2x_g = 0.0
        self._last_area_mm2 = 0.0
        self.init_ui()

    def init_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(16)

        lo.addWidget(self._build_form(), 1)
        lo.addWidget(self._build_info(), 1)

    # ---- 表单 ----

    def _build_form(self):
        card = QFrame()
        card.setObjectName("SidebarCard")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(14)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = create_card_title("芯片剪切力计算器")
        v.addWidget(title)
        sub = create_card_subtitle("参考 MIL-STD-883H Method 2019.9 规范（Figure 2019-4）")
        v.addWidget(sub)

        v.addWidget(create_step_title("芯片尺寸"))
        self.cbo_shape = create_combo(["矩形（输入长、宽）", "圆形（输入直径）",
                                       "已知面积（直接输入）"])
        self.cbo_shape.currentIndexChanged.connect(self._on_shape_changed)
        v.addWidget(self.cbo_shape)

        # 矩形：长 x 宽
        self.row_rect = self._build_rect_row()
        v.addWidget(self.row_rect)
        # 圆形：直径 -> π x D² / 4
        self.row_circle = self._build_circle_row()
        self.row_circle.setVisible(False)
        v.addWidget(self.row_circle)
        # 已知面积：直接输入 mm²（圆形/异形芯片量出来的面积）
        self.row_area = self._build_area_row()
        self.row_area.setVisible(False)
        v.addWidget(self.row_area)

        btn_lo = QHBoxLayout()
        btn_lo.addWidget(create_secondary_button("一键清零", self.reset))
        v.addLayout(btn_lo)

        v.addWidget(create_step_title("面积"))
        self.lbl_area_mm2 = QLabel("0.0000 平方毫米")
        self.lbl_area_in2 = QLabel("0.0000 平方英寸")
        for lb in [self.lbl_area_mm2, self.lbl_area_in2]:
            lb.setObjectName("AreaValue")
        area_lo = QHBoxLayout()
        area_lo.addWidget(self.lbl_area_mm2, 1)
        area_lo.addWidget(self.lbl_area_in2, 1)
        v.addLayout(area_lo)

        self.area_warn = create_warning_box("")
        self.area_warn.setVisible(False)
        v.addWidget(self.area_warn)

        v.addWidget(create_step_title("最小剪切力要求 (MIL-STD-883)"))
        self.result_widgets = {}
        for label, mult, color in [("1X 最小力值", 1.0, _C['accent']),
                                   ("1.25X 测试力值", 1.25, _C['warning']),
                                   ("2X 测试力值", 2.0, _C['danger'])]:
            f = QFrame()
            f.setObjectName("ResultCard")
            f_lo = QVBoxLayout(f)
            f_lo.setContentsMargins(12, 8, 12, 8)
            f_lo.setSpacing(4)

            hdr = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setObjectName("StatValue")
            badge = QLabel(f"x{mult}")
            badge.setObjectName("ForceBadge")
            # 注意：`{color}15` 是网页写法 ✗ Qt 会当成 #AARRGGBB（alpha 在前）→ 变成深底深字 ✗
            _h = color.lstrip('#')
            _r, _g, _b = int(_h[0:2], 16), int(_h[2:4], 16), int(_h[4:6], 16)
            badge.setStyleSheet(
                f"color: {color}; background: rgba({_r},{_g},{_b},0.10);"
                f" border: 1px solid rgba({_r},{_g},{_b},0.30); border-radius: 6px;")
            hdr.addWidget(lbl)
            hdr.addStretch()
            hdr.addWidget(badge)
            f_lo.addLayout(hdr)

            val_lo = QHBoxLayout()
            g_lb = QLabel("0.0 g")
            n_lb = QLabel("0.0000 N")
            for lb in [g_lb, n_lb]:
                lb.setObjectName("ForceValue")
            val_lo.addWidget(g_lb, 1)
            val_lo.addWidget(n_lb, 1)
            f_lo.addLayout(val_lo)

            self.result_widgets[mult] = (g_lb, n_lb)
            v.addWidget(f)

        # 一键复制 2x 力值
        copy_lo = QHBoxLayout()
        self.btn_copy = create_secondary_button("复制 2X 力值 (g)", self.copy_force)
        self.btn_copy.setEnabled(False)
        copy_lo.addWidget(self.btn_copy)
        v.addLayout(copy_lo)

        self.prompt = create_info_label("输入尺寸或面积后自动计算")
        v.addWidget(self.prompt)

        v.addStretch()

        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        scroll.setWidget(content)
        return card

    def _build_rect_row(self):
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self.inp_len = self._make_input("输入长度")
        self.inp_wid = self._make_input("输入宽度")
        grid.addWidget(QLabel("长度（mm）"), 0, 0)
        grid.addWidget(self.inp_len, 0, 1)
        grid.addWidget(QLabel("宽度（mm）"), 1, 0)
        grid.addWidget(self.inp_wid, 1, 1)
        return box

    def _build_circle_row(self):
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self.inp_dia = self._make_input("输入直径")
        grid.addWidget(QLabel("直径（mm）"), 0, 0)
        grid.addWidget(self.inp_dia, 0, 1)
        hint = create_info_label("面积 = π × 直径² ÷ 4")
        grid.addWidget(hint, 1, 0, 1, 2)
        return box

    def _build_area_row(self):
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self.inp_area = self._make_input("输入面积")
        grid.addWidget(QLabel("面积（mm²）"), 0, 0)
        grid.addWidget(self.inp_area, 0, 1)
        hint = create_info_label("适用于异形/已量好面积的芯片（按外形轮廓计）")
        grid.addWidget(hint, 1, 0, 1, 2)
        return box

    def _on_shape_changed(self, index):
        self.row_rect.setVisible(index == 0)
        self.row_circle.setVisible(index == 1)
        self.row_area.setVisible(index == 2)
        self.calculate()

    def _make_input(self, placeholder):
        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        inp.setValidator(QDoubleValidator(0.0, 99999.0, 3))
        inp.textChanged.connect(self.calculate)
        return inp

    # ---- 信息面板 ----

    def _build_info(self):
        card = QFrame()
        card.setObjectName("SidebarCard")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(14)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        v.addWidget(create_step_title("标准说明"))
        info = [
            ("参考标准：MIL-STD-883H Method 2019.9 (Figure 2019-4)", "InfoLabel"),
            ("", "InfoLabel"),
            ("适用范围：预制金锡 (Preform/Pre-coated) 芯片剪切力计算", "InfoLabel"),
            ("", "InfoLabel"),
            ("面积范围限制", "StepTitle"),
            ("  - 面积 < 5x10⁻⁴ in²: 力值按比例计算", "InfoLabel"),
            ("  - 5x10⁻⁴ ~ 64x10⁻⁴ in²: 线性插值区域", "InfoLabel"),
            ("  - 面积 > 64x10⁻⁴ in²: 标准要求 min 2.5 kgf (此计算器暂不适用)", "InfoLabel"),
            ("", "InfoLabel"),
            ("计算公式", "StepTitle"),
            ("  1. 面积(mm²)：矩形 = 长 x 宽", "InfoLabel"),
            ("                     圆形 = π x 直径² / 4", "InfoLabel"),
            ("                     也可直接输入已知面积", "InfoLabel"),
            ("  2. 面积(in²) = 面积(mm²) / 645.16", "InfoLabel"),
            ("  3. 1X 力值(g) = 面积(in²) x 400 x 1000", "InfoLabel"),
            ("     (即 0.04 kg / 1.0x10⁻⁴ in²)", "InfoLabel"),
            ("  4. 力值(N) = 力值(g) / 1000 x 9.8", "InfoLabel"),
            ("", "InfoLabel"),
        ]
        for text, obj_name in info:
            lb = QLabel(text)
            lb.setObjectName(obj_name)
            v.addWidget(lb)

        v.addStretch()

        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        scroll.setWidget(content)
        return card

    # ---- 计算 ----

    def calculate(self):
        # 三种输入互斥：矩形长宽 / 圆形直径 / 直接面积（mm²）
        try:
            shape = self.cbo_shape.currentIndex()
            if shape == 1:
                diameter = float(self.inp_dia.text())
                if diameter <= 0:
                    self._clear_results()
                    return
                area_mm2 = math.pi * diameter * diameter / 4.0
            elif shape == 2:
                area_mm2 = float(self.inp_area.text())
                if area_mm2 <= 0:
                    self._clear_results()
                    return
            else:
                length = float(self.inp_len.text())
                width = float(self.inp_wid.text())
                if length <= 0 or width <= 0:
                    self._clear_results()
                    return
                area_mm2 = length * width
        except (ValueError, TypeError):
            self._clear_results()
            return

        area_in2 = area_mm2 / MM2_PER_IN2
        self._last_area_mm2 = area_mm2

        self.lbl_area_mm2.setText(f"{area_mm2:.6f} 平方毫米")
        self.lbl_area_in2.setText(f"{area_in2:.6f} 平方英寸")

        if area_in2 > MAX_AREA_IN2:
            self.area_warn.setText("面积超过 64x10⁻⁴ 平方英寸，此计算器不适用（标准要求 min 2.5 kgf）")
            self.area_warn.setVisible(True)
            for mult in (1.0, 1.25, 2.0):
                g_lb, n_lb = self.result_widgets[mult]
                g_lb.setText("不适用")
                n_lb.setText("不适用")
                self._set_value_state(g_lb, error=True)
                self._set_value_state(n_lb, error=True)
            self.btn_copy.setEnabled(False)
            self.prompt.setVisible(False)
            return

        if area_in2 > WARN_AREA_IN2:
            self.area_warn.setText("面积超过 5x10⁻⁴ 平方英寸，超出标准推荐范围，仅供参考")
            self.area_warn.setVisible(True)
        else:
            self.area_warn.setVisible(False)

        force_1x_g = area_in2 * FORCE_FACTOR * 1000
        self._force_2x_g = force_1x_g * 2.0

        for mult, g_base in [(1.0, force_1x_g), (1.25, force_1x_g * 1.25), (2.0, force_1x_g * 2.0)]:
            g_lb, n_lb = self.result_widgets[mult]
            g_lb.setText(f"{g_base:.1f} g")
            n_lb.setText(f"{g_base / 1000 * 9.8:.4f} N")
            self._set_value_state(g_lb)
            self._set_value_state(n_lb)

        self.btn_copy.setEnabled(True)
        self.prompt.setVisible(False)

    def _clear_results(self):
        self._last_area_mm2 = 0.0
        self.lbl_area_mm2.setText("0.0000 平方毫米")
        self.lbl_area_in2.setText("0.0000 平方英寸")
        self.area_warn.setVisible(False)
        self.area_warn.setObjectName("WarningBox")
        for mult in (1.0, 1.25, 2.0):
            g_lb, n_lb = self.result_widgets[mult]
            g_lb.setText("0.0 g")
            n_lb.setText("0.0000 N")
            self._set_value_state(g_lb)
            self._set_value_state(n_lb)
        self.btn_copy.setEnabled(False)
        self.prompt.setVisible(True)

    @staticmethod
    def _set_value_state(label, error=False):
        """切换数值语义（正常/不适用），objectName 变化后强制重刷 QSS"""
        label.setObjectName('ErrorValue' if error else 'ForceValue')
        label.style().unpolish(label)
        label.style().polish(label)

    def reset(self):
        self.inp_len.clear()
        self.inp_wid.clear()
        self.inp_dia.clear()
        self.inp_area.clear()
        self._clear_results()

    def copy_force(self):
        if self._force_2x_g > 0:
            text = f"{self._force_2x_g:.1f} g"
            QApplication.clipboard().setText(text)
