"""距离测量Tab — 标定 → 测距 → 统计 → 导出"""

import cv2
import numpy as np
import pandas as pd
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                             QFrame, QScrollArea, QLabel, QTableWidget,
                             QTableWidgetItem, QHeaderView, QInputDialog,
                             QMessageBox, QSizePolicy, QGraphicsDropShadowEffect)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from ui_components import (create_primary_button, create_secondary_button,
                           create_danger_button, create_step_title,
                           create_info_label, create_success_label)
from measure_canvas import MeasureCanvas


class MeasureTab(QWidget):

    def __init__(self):
        super().__init__()
        self.pixel_scale = 0.0
        self.measurements = []
        self.init_ui()

    def init_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(16)

        lo.addWidget(self._build_sidebar())
        self.canvas = MeasureCanvas()
        lo.addWidget(self.canvas, 1)

        self._connect()
        self._refresh()

    # ---------- 侧边栏 ----------

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("SidebarCard")
        sidebar.setMinimumWidth(320)
        sidebar.setMaximumWidth(420)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30); shadow.setOffset(0, 4); shadow.setColor(QColor(0, 0, 0, 25))
        sidebar.setGraphicsEffect(shadow)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(12)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ---- 上传 ----
        v.addWidget(create_primary_button("打开图片", self.load_image))

        # ---- 标定 ----
        v.addWidget(self._sep("标定"))
        calib_row = QHBoxLayout()
        self.btn_calib = create_secondary_button("划线标定", self.toggle_calib, checkable=True)
        self.btn_clear_calib = create_secondary_button("X", self.clear_calib)
        self.btn_clear_calib.setFixedWidth(40)
        self.btn_clear_calib.setToolTip("清除标定")
        calib_row.addWidget(self.btn_calib, 1)
        calib_row.addWidget(self.btn_clear_calib)
        v.addLayout(calib_row)
        self.lbl_calib = create_success_label("")
        v.addWidget(self.lbl_calib)

        # ---- 测量 ----
        v.addWidget(self._sep("距离测量"))
        meas_row = QHBoxLayout()
        self.btn_measure = create_secondary_button("测量模式", self.toggle_measure, checkable=True)
        self.btn_undo = create_secondary_button("撤销", self.undo_last)
        self.btn_clear = create_danger_button("全部清除", self.clear_all)
        meas_row.addWidget(self.btn_measure)
        meas_row.addWidget(self.btn_undo)
        meas_row.addWidget(self.btn_clear)
        v.addLayout(meas_row)
        self.lbl_hint = create_info_label("点击「测量模式」后在图上依次点击两点")
        v.addWidget(self.lbl_hint)

        # ---- 统计 ----
        v.addWidget(self._sep("统计"))
        self.stat_box = QFrame()
        self.stat_box.setObjectName("StatBox")
        self.stat_box.setStyleSheet("QFrame#StatBox { background: #f1f5f9; border-radius: 10px; padding: 8px; }")
        stat_lo = QVBoxLayout(self.stat_box)
        stat_lo.setContentsMargins(12, 8, 12, 8)
        stat_lo.setSpacing(2)
        self.lbl_count = QLabel("测量数量: 0")
        self.lbl_min = QLabel("最小距离: —")
        self.lbl_max = QLabel("最大距离: —")
        self.lbl_mean = QLabel("平均距离: —")
        self.lbl_total = QLabel("总距离: —")
        for lb in [self.lbl_count, self.lbl_min, self.lbl_max, self.lbl_mean, self.lbl_total]:
            lb.setStyleSheet("color: #475569; font-size: 13px; font-weight: 500;")
            stat_lo.addWidget(lb)
        v.addWidget(self.stat_box)

        # ---- 数据表格 ----
        v.addWidget(self._sep("测量数据"))
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["#", "距离 (μm)", "距离 (px)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMaximumHeight(300)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("alternate-background-color: #f8fafc;")
        v.addWidget(self.table)

        # ---- 导出 ----
        self.btn_export = create_secondary_button("导出 CSV", self.export_csv)
        self.btn_export.setEnabled(False)
        v.addWidget(self.btn_export)

        v.addStretch()

        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        scroll.setWidget(content)
        return sidebar

    @staticmethod
    def _sep(text):
        return create_step_title(f"── {text} ──")

    # ---------- 信号连接 ----------

    def _connect(self):
        self.canvas.calib_drawn.connect(self.finish_calib)
        self.canvas.measurement_added.connect(self.on_measure)

    # ---------- 状态刷新 ----------

    def _refresh(self):
        has_img = self.canvas.img_qt is not None
        has_calib = float(self.pixel_scale) > 0

        self.btn_calib.setEnabled(has_img)
        self.btn_clear_calib.setEnabled(has_img and has_calib)
        self.btn_measure.setEnabled(has_img and has_calib)
        self.btn_undo.setEnabled(len(self.measurements) > 0)
        self.btn_clear.setEnabled(len(self.measurements) > 0)
        self.btn_export.setEnabled(len(self.measurements) > 0)

    def _update_stats(self):
        n = len(self.measurements)
        self.lbl_count.setText(f"测量数量: {n}")
        if n == 0:
            for lb in [self.lbl_min, self.lbl_max, self.lbl_mean, self.lbl_total]:
                lb.setText(lb.text().split(":")[0] + ": —")
        else:
            vals = [m[4] for m in self.measurements]
            self.lbl_min.setText(f"最小距离: {min(vals):.2f} μm")
            self.lbl_max.setText(f"最大距离: {max(vals):.2f} μm")
            self.lbl_mean.setText(f"平均距离: {np.mean(vals):.2f} μm")
            self.lbl_total.setText(f"总距离: {sum(vals):.2f} μm")

    def _update_table(self):
        self.table.setRowCount(len(self.measurements))
        for i, (x1, y1, x2, y2, d_um) in enumerate(self.measurements):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(f"{d_um:.2f}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{d_um * self.pixel_scale:.1f}"))

    # ---------- 动作 ----------

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif)")
        if not path:
            return
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            QMessageBox.warning(self, "错误", "图片加载失败")
            return
        self.canvas.set_image(img)
        self._reset()
        self._refresh()

    def _reset(self):
        self.pixel_scale = 0.0
        self.measurements = []
        self.canvas.reset_all()
        self.lbl_calib.setText("")
        self.lbl_hint.setText("点击「测量模式」后在图上依次点击两点")
        self.table.setRowCount(0)
        self._update_stats()

    def toggle_calib(self):
        if self.btn_calib.isChecked():
            self.canvas.mode = 'calibrate'
            self.btn_measure.setChecked(False)
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.lbl_calib.setText("在图上拖拽画一条已知长度的参考线")
            self.lbl_calib.setStyleSheet("color: #4299e1; font-size: 13px; font-weight: 500;")
        else:
            self.canvas.mode = 'none'
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
            self._show_calib_status()
        self.canvas.update()

    def clear_calib(self):
        self.canvas.clear_calibration()
        self.pixel_scale = 0.0
        self.lbl_calib.setText("未标定")
        self.lbl_calib.setStyleSheet("color: #ef4444; font-size: 13px; font-weight: 500;")
        self.btn_measure.setChecked(False)
        self.canvas.mode = 'none'
        self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        self._refresh()

    def _show_calib_status(self):
        if self.pixel_scale > 0:
            self.lbl_calib.setText(f"标定成功   1 μm = {self.pixel_scale:.2f} px")
            self.lbl_calib.setStyleSheet("color: #10b981; font-size: 13px; font-weight: 600;")
        else:
            self.lbl_calib.setText("未标定")
            self.lbl_calib.setStyleSheet("color: #ef4444; font-size: 13px; font-weight: 500;")

    def finish_calib(self, p1, p2):
        self.canvas.mode = 'none'
        self.btn_calib.setChecked(False)
        self.canvas.setCursor(Qt.CursorShape.ArrowCursor)

        dist_px = np.hypot(p2.x() - p1.x(), p2.y() - p1.y())
        if dist_px < 5:
            QMessageBox.warning(self, "提示", "标定线太短，请重试")
            self.canvas.calib_start = self.canvas.calib_drag = None
            self.canvas.update()
            return

        dialog = QInputDialog(self)
        dialog.setWindowTitle("比例尺标定")
        dialog.setLabelText("参考线的实际长度:")
        dialog.setDoubleRange(0.1, 100000)
        dialog.setDoubleStep(0.1)
        dialog.setDoubleValue(50)
        dialog.setOkButtonText("确定")
        dialog.setCancelButtonText("取消")

        if dialog.exec():
            real_len = dialog.doubleValue()
            if real_len > 0:
                self.pixel_scale = dist_px / real_len
                self.canvas.pixel_scale = self.pixel_scale
                self.canvas.calib_line = (p1, p2, f"{real_len} μm")
                self.canvas.calibrated = True
                self.canvas.update()
        else:
            self.canvas.calib_start = self.canvas.calib_drag = None
            self.canvas.update()

        self._show_calib_status()
        self._refresh()

    def toggle_measure(self):
        if self.btn_measure.isChecked():
            if self.pixel_scale <= 0:
                QMessageBox.warning(self, "提示", "请先标定比例尺")
                self.btn_measure.setChecked(False)
                return
            self.canvas.mode = 'measure'
            self.btn_calib.setChecked(False)
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.lbl_hint.setText("依次点击两点进行测量")
        else:
            self.canvas.mode = 'none'
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
            self.lbl_hint.setText("点击「测量模式」后在图上依次点击两点")
        self.canvas.update()

    def on_measure(self, x1, y1, x2, y2, dist):
        self.measurements.append((x1, y1, x2, y2, dist))
        self._update_table()
        self._update_stats()
        self._refresh()

    def undo_last(self):
        self.canvas.remove_last_measurement()
        if self.measurements:
            self.measurements.pop()
            self._update_table()
            self._update_stats()
            self._refresh()

    def clear_all(self):
        self.measurements = []
        self.canvas.clear_measurements()
        self.table.setRowCount(0)
        self._update_stats()
        self._refresh()

    # ---------- 导出 ----------

    def export_csv(self):
        if not self.measurements:
            return
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", f"测量数据_{ts}.csv", "CSV Files (*.csv)")
        if not path:
            return
        rows = []
        for i, (x1, y1, x2, y2, d_um) in enumerate(self.measurements):
            rows.append({
                "序号": i + 1,
                "距离(μm)": round(d_um, 2),
                "距离(px)": round(d_um * self.pixel_scale, 1),
                "起点X": round(x1, 1),
                "起点Y": round(y1, 1),
                "终点X": round(x2, 1),
                "终点Y": round(y2, 1),
            })
        pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8-sig')
        QMessageBox.information(self, "成功", f"已导出 {len(rows)} 条测量数据")
