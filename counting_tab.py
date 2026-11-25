import cv2
import numpy as np
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                              QFrame, QScrollArea, QLabel,
                              QSpinBox, QComboBox, QMessageBox, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer

from image import detect_objects, otsu_threshold
from csv_export import write_csv
from ui_components import (create_primary_button, create_secondary_button,
                           create_danger_button, create_step_title,
                           create_checkbox, create_slider, create_divider,
                           create_slider_with_label, create_count_result)
from counting_canvas import CountingCanvas


class CountingTab(QWidget):

    def __init__(self):
        super().__init__()
        self.img_cv = None
        self.objects = []
        self.min_area = 1
        self.invert = True
        self.morph_enabled = True
        self.morph_kernel = 3
        self.morph_shape = cv2.MORPH_ELLIPSE
        self.watershed_enabled = False
        self.watershed_distance = 10
        self.canvas = None
        self._detect_timer = QTimer()
        self._detect_timer.setSingleShot(True)
        self._detect_timer.timeout.connect(self._do_detect)
        self.init_ui()

    def init_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(16)

        lo.addWidget(self._build_sidebar())
        self.canvas = CountingCanvas()
        self.canvas.empty_import.connect(self.load_image)
        lo.addWidget(self.canvas, 1)

        self.canvas.roi_rect_finished.connect(self._on_roi_finished)
        self.canvas.roi_polygon_finished.connect(self._on_roi_finished_poly)
        self.canvas.object_delete_at.connect(self._on_delete_at)
        self.canvas.object_add_at.connect(self._on_add_at)

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("SidebarCard")
        sidebar.setMinimumWidth(280)
        sidebar.setMaximumWidth(360)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        sb = QWidget()
        layout = QVBoxLayout(sb)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.btn_load = create_primary_button("上传图片", self.load_image)
        layout.addWidget(self.btn_load)

        layout.addWidget(create_step_title("框选区域"))
        roi_row = QHBoxLayout()
        roi_row.setSpacing(8)
        self.btn_roi_rect = create_secondary_button("矩形框选", checkable=True)
        self.btn_roi_rect.toggled.connect(lambda e: self._toggle_roi('rect', e))
        roi_row.addWidget(self.btn_roi_rect)
        self.btn_roi_poly = create_secondary_button("多边形框选", checkable=True)
        self.btn_roi_poly.toggled.connect(lambda e: self._toggle_roi('poly', e))
        roi_row.addWidget(self.btn_roi_poly)
        roi_row.setStretch(0, 1)
        roi_row.setStretch(1, 1)
        layout.addLayout(roi_row)
        roi_row2 = QHBoxLayout()
        self.btn_rerun = create_secondary_button("重新框选", self._reset_roi)
        roi_row2.addWidget(self.btn_rerun)
        layout.addLayout(roi_row2)

        layout.addWidget(create_step_title("检测设置"))
        self._detect_widgets = QWidget()
        dw = QVBoxLayout(self._detect_widgets)
        dw.setContentsMargins(0, 0, 0, 0)

        self.chk_invert = create_checkbox("检测亮色物体", True, self.detect)
        dw.addWidget(self.chk_invert)

        dw.addWidget(QLabel("二值化阈值"))
        self.slider_thresh, self.lbl_thresh = create_slider_with_label(0, 255, 80, self.detect)
        dw.addWidget(self.lbl_thresh)
        dw.addWidget(self.slider_thresh)

        btn_otsu = create_secondary_button("自动阈值 (Otsu)", self.auto_otsu)
        dw.addWidget(btn_otsu)

        dw.addWidget(QLabel("最小面积（像素）"))
        self.spin_min_area = QSpinBox()
        self.spin_min_area.setRange(0, 100000)
        self.spin_min_area.setValue(1)
        self.spin_min_area.setSuffix(' px²')
        self.spin_min_area.valueChanged.connect(self._on_min_area_changed)
        dw.addWidget(self.spin_min_area)

        self.chk_morph = create_checkbox("形态学去噪", True, self._on_morph_toggled)
        dw.addWidget(self.chk_morph)

        morph_row = QHBoxLayout()
        morph_row.addWidget(QLabel("核大小"))
        self.slider_morph = create_slider(1, 15, 3, self._on_morph_changed)
        self.slider_morph.setSingleStep(2)
        self.slider_morph.setMinimumWidth(60)
        morph_row.addWidget(self.slider_morph, 1)
        self.lbl_morph_val = QLabel("3")
        self.lbl_morph_val.setFixedWidth(24)
        morph_row.addWidget(self.lbl_morph_val)
        self.cb_morph_shape = QComboBox()
        self.cb_morph_shape.addItems(["椭圆", "矩形", "十字"])
        self.cb_morph_shape.currentIndexChanged.connect(self._on_morph_shape_changed)
        morph_row.addWidget(self.cb_morph_shape)
        dw.addLayout(morph_row)

        self.chk_watershed = create_checkbox("距离峰值计数（分离粘连物体）", False, self._on_watershed_toggled)
        dw.addWidget(self.chk_watershed)

        ws_row = QHBoxLayout()
        ws_row.addWidget(QLabel("最小间距"))
        self.slider_ws = create_slider(3, 50, 10, self._on_ws_changed)
        self.slider_ws.setMinimumWidth(60)
        ws_row.addWidget(self.slider_ws, 1)
        self.lbl_ws_val = QLabel("10")
        self.lbl_ws_val.setFixedWidth(24)
        ws_row.addWidget(self.lbl_ws_val)
        self.slider_ws.setEnabled(False)
        dw.addLayout(ws_row)

        self._detect_widgets.setEnabled(False)
        layout.addWidget(self._detect_widgets)

        layout.addWidget(create_divider())

        layout.addWidget(create_step_title("手动编辑"))
        edit_row = QHBoxLayout()
        self.btn_add = create_secondary_button("添加遗漏", checkable=True)
        self.btn_add.toggled.connect(self._toggle_add)
        edit_row.addWidget(self.btn_add)
        self.btn_del = create_secondary_button("删除多选", checkable=True)
        self.btn_del.toggled.connect(self._toggle_del)
        edit_row.addWidget(self.btn_del)
        layout.addLayout(edit_row)

        layout.addWidget(create_divider())

        self.btn_defaults = create_danger_button("恢复默认设置", self._restore_defaults)
        layout.addWidget(self.btn_defaults)

        self.lbl_count = create_count_result("数量：0")
        layout.addWidget(self.lbl_count)

        self.btn_export = create_secondary_button("导出 CSV", self.export_csv)
        layout.addWidget(self.btn_export)

        layout.addStretch()
        scroll.setWidget(sb)

        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return sidebar

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.tif)")
        if not path:
            return
        with open(path, 'rb') as f:
            buf = np.frombuffer(f.read(), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            QMessageBox.warning(self, "错误", "无法读取图片")
            return
        self.img_cv = img
        self.canvas.set_image(img)
        self.objects = []
        self._detect_widgets.setEnabled(False)
        self._update_result()

    def _toggle_roi(self, mode, enabled):
        if enabled:
            self.canvas.roi_mode = mode
            self.canvas.roi_rect = None
            self.canvas.roi_polygon = None
            self.canvas.poly_drawing = []
            self.objects = []
            self._detect_widgets.setEnabled(False)
            self._sync_canvas()
            if mode == 'rect':
                self.btn_roi_poly.blockSignals(True)
                self.btn_roi_poly.setChecked(False)
                self.btn_roi_poly.blockSignals(False)
            else:
                self.btn_roi_rect.blockSignals(True)
                self.btn_roi_rect.setChecked(False)
                self.btn_roi_rect.blockSignals(False)
        else:
            self.canvas.roi_mode = 'none'
        self.canvas.update()

    def _reset_roi(self):
        self.canvas.roi_mode = 'none'
        self.canvas.roi_rect = None
        self.canvas.roi_polygon = None
        self.canvas.poly_drawing = []
        self.objects = []
        self._detect_widgets.setEnabled(False)
        self._sync_canvas()
        self.canvas.update()
        self.btn_roi_rect.blockSignals(True)
        self.btn_roi_rect.setChecked(True)
        self.btn_roi_rect.blockSignals(False)
        self.btn_roi_poly.blockSignals(True)
        self.btn_roi_poly.setChecked(False)
        self.btn_roi_poly.blockSignals(False)
        self._toggle_roi('rect', True)

    def _toggle_add(self, enabled):
        self.canvas.edit_mode = 'add' if enabled else 'none'
        self.canvas._hovered_idx = -1
        self.canvas.update()

    def _toggle_del(self, enabled):
        self.canvas.edit_mode = 'delete' if enabled else 'none'
        self.canvas._hovered_idx = -1
        self.canvas.update()

    def _on_delete_at(self, x, y):
        pt = (float(x), float(y))
        for i in range(len(self.objects) - 1, -1, -1):
            pts = np.array(self.objects[i]['points'], dtype=np.int32)
            if len(pts) >= 3 and cv2.pointPolygonTest(pts, pt, False) >= 0:
                del self.objects[i]
                self._sync_canvas()
                return

    def _on_add_at(self, x, y):
        if self.img_cv is None:
            return
        h, w = self.img_cv.shape[:2]
        cx, cy = int(x), int(y)
        if not (0 <= cx < w and 0 <= cy < h):
            return

        radius = 8
        pts = []
        for a in range(0, 360, 15):
            rad = np.radians(a)
            px = cx + radius * np.cos(rad)
            py = cy + radius * np.sin(rad)
            pts.append([px, py])

        pts_array = np.array(pts, dtype=np.int32)
        area = cv2.contourArea(pts_array)
        x_r, y_r, w_r, h_r = cv2.boundingRect(pts_array)

        new_id = 1
        if self.objects:
            new_id = max(o['id'] for o in self.objects) + 1

        self.objects.append({
            'id': new_id,
            'area_px': area,
            'rect': (x_r, y_r, w_r, h_r),
            'cx': float(cx),
            'cy': float(cy),
            'points': pts,
        })
        self._sync_canvas()

    def _on_roi_finished(self, rect):
        self._detect_widgets.setEnabled(True)
        self.detect()

    def _on_roi_finished_poly(self, pts):
        self._detect_widgets.setEnabled(True)
        self.canvas.roi_rect = None
        self.detect()

    def _restore_defaults(self):
        self.slider_thresh.setValue(80)
        self.lbl_thresh.setText("80")
        self.chk_invert.setChecked(True)
        self.spin_min_area.setValue(1)
        self.chk_morph.setChecked(True)
        self.slider_morph.setValue(3)
        self.lbl_morph_val.setText("3")
        self.cb_morph_shape.setCurrentIndex(0)
        self.slider_morph.setEnabled(True)
        self.chk_watershed.setChecked(False)
        self.slider_ws.setValue(10)
        self.lbl_ws_val.setText("10")
        self.slider_ws.setEnabled(False)
        self.morph_enabled = True
        self.morph_kernel = 3
        self.morph_shape = cv2.MORPH_ELLIPSE
        self.watershed_enabled = False
        self.watershed_distance = 10
        self.min_area = 1
        self.invert = True
        self.detect()

    def auto_otsu(self):
        if self.img_cv is None:
            return
        gray = cv2.cvtColor(self.img_cv, cv2.COLOR_BGR2GRAY)
        thresh = otsu_threshold(gray)
        self.slider_thresh.setValue(thresh)
        self.lbl_thresh.setText(str(thresh))
        self.detect()

    def _on_min_area_changed(self):
        self.min_area = self.spin_min_area.value()
        self.detect()

    def _on_morph_toggled(self):
        self.morph_enabled = self.chk_morph.isChecked()
        self.slider_morph.setEnabled(self.morph_enabled)
        self.detect()

    def _on_morph_changed(self):
        val = self.slider_morph.value()
        if val % 2 == 0:
            val = max(1, val - 1)
            self.slider_morph.setValue(val)
        self.morph_kernel = val
        self.lbl_morph_val.setText(str(val))
        self.detect()

    def _on_morph_shape_changed(self, idx):
        mapping = [cv2.MORPH_ELLIPSE, cv2.MORPH_RECT, cv2.MORPH_CROSS]
        self.morph_shape = mapping[idx]
        self.detect()

    def _on_watershed_toggled(self):
        self.watershed_enabled = self.chk_watershed.isChecked()
        self.slider_ws.setEnabled(self.watershed_enabled)
        self.detect()

    def _on_ws_changed(self):
        self.watershed_distance = self.slider_ws.value()
        self.lbl_ws_val.setText(str(self.watershed_distance))
        self.detect()

    def detect(self):
        self._detect_timer.start(150)

    def _do_detect(self):
        if self.img_cv is None:
            return

        h_img, w_img = self.img_cv.shape[:2]
        roi_mask = None

        if self.canvas.roi_polygon:
            roi_mask = np.zeros((h_img, w_img), dtype=np.uint8)
            pts = np.array([(int(x), int(y)) for x, y in self.canvas.roi_polygon], dtype=np.int32)
            cv2.fillPoly(roi_mask, [pts], 255)
        elif self.canvas.roi_rect and self.canvas.roi_rect[2] > 5 and self.canvas.roi_rect[3] > 5:
            x, y, w, h = [int(v) for v in self.canvas.roi_rect]
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(w_img, x + w)
            y2 = min(h_img, y + h)
            roi_mask = np.zeros((h_img, w_img), dtype=np.uint8)
            roi_mask[y1:y2, x1:x2] = 255
        else:
            self.objects = []
            self._sync_canvas()
            return

        gray = cv2.cvtColor(self.img_cv, cv2.COLOR_BGR2GRAY)
        thresh = self.slider_thresh.value()
        self.lbl_thresh.setText(str(thresh))
        self.invert = self.chk_invert.isChecked()

        self.objects = detect_objects(
            gray,
            thresh_val=thresh,
            min_area=self.min_area,
            max_area=None,
            enhanced=True,
            clahe_enabled=True,
            clahe_clip_limit=2.0,
            morph_enabled=self.morph_enabled,
            morph_kernel=self.morph_kernel,
            morph_shape=self.morph_shape,
            min_roundness=0.0,
            edge_verify=False,
            invert=self.invert,
            watershed_enabled=self.watershed_enabled,
            watershed_distance=self.watershed_distance,
            roi_mask=roi_mask,
        )

        self._sync_canvas()

    def _sync_canvas(self):
        self.canvas.objects = self.objects
        self.canvas.count = len(self.objects)
        self.canvas.update()
        self._update_result()

    def _update_result(self):
        self.lbl_count.setText(f"数量：{len(self.objects)}")

    def export_csv(self):
        if not self.objects:
            QMessageBox.information(self, "提示", "没有数据可导出")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", f"计数_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV (*.csv)")
        if not path:
            return
        data = []
        for o in self.objects:
            x, y, w, h = o['rect']
            data.append({
                '编号': o['id'],
                '面积(像素)': o['area_px'],
                '中心X': round(o['cx'], 2),
                '中心Y': round(o['cy'], 2),
                '宽度': w,
                '高度': h,
            })
        write_csv(path, data)
        QMessageBox.information(self, "成功", f"导出 {len(data)} 条数据")