"""预覆金锡剪切力计算器Tab — 参考MIL-STD-883H Method 2019.9"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QScrollArea, QLabel, QLineEdit, QGridLayout,
                             QSizePolicy, QGraphicsDropShadowEffect, QApplication)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QDoubleValidator

from ui_components import (create_primary_button, create_secondary_button,
                           create_step_title)


MM2_PER_IN2 = 645.16
MAX_AREA_IN2 = 64e-4
WARN_AREA_IN2 = 5e-4
FORCE_FACTOR = 0.04 / 0.0001


class ShearTab(QWidget):

    def __init__(self):
        super().__init__()
        self._force_2x_g = 0.0
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
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30); shadow.setOffset(0, 4); shadow.setColor(QColor(0, 0, 0, 25))
        card.setGraphicsEffect(shadow)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(28, 28, 28, 28)
        v.setSpacing(16)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Die Shear Force Calculator")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #1e293b;")
        v.addWidget(title)
        sub = QLabel("参考 MIL-STD-883H Method 2019.9 规范 (Figure 2019-4)")
        sub.setStyleSheet("color: #64748b; font-size: 14px; margin-bottom: 4px;")
        v.addWidget(sub)

        v.addWidget(create_step_title("芯片尺寸"))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.inp_len = self._make_input("长度 (mm)")
        self.inp_wid = self._make_input("宽度 (mm)")
        grid.addWidget(QLabel("长度 (毫米)"), 0, 0)
        grid.addWidget(self.inp_len, 0, 1)
        grid.addWidget(QLabel("宽度 (毫米)"), 1, 0)
        grid.addWidget(self.inp_wid, 1, 1)
        v.addLayout(grid)

        btn_lo = QHBoxLayout()
        btn_lo.addWidget(create_secondary_button("一键清零", self.reset))
        v.addLayout(btn_lo)

        v.addWidget(create_step_title("面积"))
        self.lbl_area_mm2 = QLabel("0.0000 平方毫米")
        self.lbl_area_in2 = QLabel("0.0000 平方英寸")
        for lb in [self.lbl_area_mm2, self.lbl_area_in2]:
            lb.setStyleSheet("font-size: 18px; font-weight: 700; color: #1e293b;")
        area_lo = QHBoxLayout()
        area_lo.addWidget(self.lbl_area_mm2, 1)
        area_lo.addWidget(self.lbl_area_in2, 1)
        v.addLayout(area_lo)

        self.area_warn = QLabel("")
        self.area_warn.setStyleSheet("color: #dc2626; font-size: 12px; font-weight: 600; padding: 6px 10px; background: #fef2f2; border-radius: 6px;")
        self.area_warn.setWordWrap(True)
        self.area_warn.setVisible(False)
        v.addWidget(self.area_warn)

        v.addWidget(create_step_title("最小剪切力要求 (MIL-STD-883)"))
        self.result_widgets = {}
        for label, mult, color in [("1X 最小力值", 1.0, "#2563eb"), ("1.25X 测试力值", 1.25, "#f59e0b"), ("2X 测试力值", 2.0, "#dc2626")]:
            f = QFrame()
            f.setStyleSheet(f"background: #f8fafc; border-radius: 8px; padding: 4px;")
            f_lo = QVBoxLayout(f)
            f_lo.setContentsMargins(12, 8, 12, 8)
            f_lo.setSpacing(4)

            hdr = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #64748b; font-size: 13px;")
            badge = QLabel(f"x{mult}")
            badge.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 11px; background: {color}15; padding: 1px 8px; border-radius: 4px;")
            hdr.addWidget(lbl)
            hdr.addStretch()
            hdr.addWidget(badge)
            f_lo.addLayout(hdr)

            val_lo = QHBoxLayout()
            g_lb = QLabel("0.0 g")
            n_lb = QLabel("0.0000 N")
            for lb in [g_lb, n_lb]:
                lb.setStyleSheet("font-size: 15px; font-weight: 600; color: #1e293b;")
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

        self.prompt = QLabel("请输入芯片尺寸后自动计算")
        self.prompt.setStyleSheet("color: #94a3b8; font-size: 13px; padding: 8px 0;")
        v.addWidget(self.prompt)

        v.addStretch()

        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        scroll.setWidget(content)
        return card

    def _make_input(self, placeholder):
        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        inp.setValidator(QDoubleValidator(0.0, 99999.0, 3))
        inp.setStyleSheet("""
            QLineEdit {
                border: 1.5px solid #cbd5e0; border-radius: 8px; padding: 8px 12px;
                font-size: 14px; background: white;
            }
            QLineEdit:focus { border-color: #4299e1; }
        """)
        inp.textChanged.connect(self.calculate)
        return inp

    # ---- 信息面板 ----

    def _build_info(self):
        card = QFrame()
        card.setObjectName("SidebarCard")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30); shadow.setOffset(0, 4); shadow.setColor(QColor(0, 0, 0, 25))
        card.setGraphicsEffect(shadow)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(28, 28, 28, 28)
        v.setSpacing(16)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        v.addWidget(create_step_title("标准说明"))
        info = [
            ("参考标准：MIL-STD-883H Method 2019.9 (Figure 2019-4)", "#1e293b", True),
            ("", "#64748b", False),
            ("适用范围：预制金锡 (Preform/Pre-coated) 芯片剪切力计算", "#dc2626", True),
            ("", "#64748b", False),
            ("面积范围限制", "#1e293b", True),
            ("  - 面积 < 5x10⁻⁴ in²: 力值按比例计算", "#64748b", False),
            ("  - 5x10⁻⁴ ~ 64x10⁻⁴ in²: 线性插值区域", "#64748b", False),
            ("  - 面积 > 64x10⁻⁴ in²: 标准要求 min 2.5 kgf (此计算器暂不适用)", "#64748b", False),
            ("", "#64748b", False),
            ("计算公式", "#1e293b", True),
            ("  1. 面积(mm²) = 长度 x 宽度", "#64748b", False),
            ("  2. 面积(in²) = 面积(mm²) / 645.16", "#64748b", False),
            ("  3. 1X 力值(g) = 面积(in²) x 400 x 1000", "#64748b", False),
            ("     (即 0.04 kg / 1.0x10⁻⁴ in²)", "#64748b", False),
            ("  4. 力值(N) = 力值(g) / 1000 x 9.8", "#64748b", False),
            ("", "#64748b", False),
            # ("验收判据 (Failure Criteria)", "#1e293b", True),
            # ("  - 1X: 低于此值即为不合格", "#64748b", False),
            # ("  - 1.25X: 低于此值且粘附 < 50% 为不合格", "#64748b", False),
            # ("  - 2X: 低于此值且粘附 < 10% 为不合格", "#64748b", False),
        ]
        for text, color, bold in info:
            lb = QLabel(text)
            w = "700" if bold else "400"
            lb.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: {w};")
            v.addWidget(lb)

        v.addStretch()

        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        scroll.setWidget(content)
        return card

    # ---- 计算 ----

    def calculate(self):
        try:
            length = float(self.inp_len.text())
            width = float(self.inp_wid.text())
        except (ValueError, TypeError):
            self._clear_results()
            return

        if length <= 0 or width <= 0:
            self._clear_results()
            return

        area_mm2 = length * width
        area_in2 = area_mm2 / MM2_PER_IN2

        self.lbl_area_mm2.setText(f"{area_mm2:.6f} 平方毫米")
        self.lbl_area_in2.setText(f"{area_in2:.6f} 平方英寸")

        if area_in2 > MAX_AREA_IN2:
            self.area_warn.setText("面积超过 64x10⁻⁴ 平方英寸，此计算器不适用（标准要求 min 2.5 kgf）")
            self.area_warn.setVisible(True)
            for mult in (1.0, 1.25, 2.0):
                g_lb, n_lb = self.result_widgets[mult]
                g_lb.setText("不适用")
                n_lb.setText("不适用")
                g_lb.setStyleSheet("font-size: 15px; font-weight: 700; color: #dc2626;")
                n_lb.setStyleSheet("font-size: 15px; font-weight: 700; color: #dc2626;")
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
            g_lb.setStyleSheet("font-size: 15px; font-weight: 600; color: #1e293b;")
            n_lb.setStyleSheet("font-size: 15px; font-weight: 600; color: #1e293b;")

        self.btn_copy.setEnabled(True)
        self.prompt.setVisible(False)

    def _clear_results(self):
        self.lbl_area_mm2.setText("0.0000 平方毫米")
        self.lbl_area_in2.setText("0.0000 平方英寸")
        self.area_warn.setVisible(False)
        for mult in (1.0, 1.25, 2.0):
            g_lb, n_lb = self.result_widgets[mult]
            g_lb.setText("0.0 g")
            n_lb.setText("0.0000 N")
            g_lb.setStyleSheet("font-size: 15px; font-weight: 600; color: #1e293b;")
            n_lb.setStyleSheet("font-size: 15px; font-weight: 600; color: #1e293b;")
        self.btn_copy.setEnabled(False)
        self.prompt.setVisible(True)

    def reset(self):
        self.inp_len.clear()
        self.inp_wid.clear()
        self._clear_results()

    def copy_force(self):
        if self._force_2x_g > 0:
            text = f"{self._force_2x_g:.1f} g"
            QApplication.clipboard().setText(text)
