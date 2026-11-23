"""缺陷面积测量：原图像素检测、可选标定、ROI、手动修正及 CSV。"""

import csv
import math
import os
from datetime import datetime
from pathlib import Path
import tempfile
import zlib

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog,
                             QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel,
                             QScrollArea, QSpinBox, QSplitter, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from area_canvas import AreaCanvas, hit_index, mask_hit
from image import detect_defects, otsu_threshold, polygon_to_mask
from ui_components import (CollapsibleSection, create_checkbox, create_groupbox,
                           create_info_label, create_primary_button,
                           create_secondary_button, create_slider,
                           create_slider_with_label)


UNIT_FACTORS = {'nm': 1e-3, 'µm': 1., 'mm': 1e3, 'cm': 1e4, 'm': 1e6}
CSV_COLUMNS = ['ROI编号', '缺陷编号', '像素面积', '实际面积', '面积单位', '质心x_px', '质心y_px', '来源']


def compute_real_area(area_px: int, unit_per_px: float | None) -> float | None:
    return None if unit_per_px is None else float(area_px * unit_per_px ** 2)


def fmt_area(value: float, unit: str) -> str:
    if value <= 0:
        return f'0.00 {unit}²'
    units = list(UNIT_FACTORS)
    index = units.index(unit)
    while value >= 1e6 and index < len(units) - 1:
        value *= (UNIT_FACTORS[units[index]] / UNIT_FACTORS[units[index + 1]]) ** 2
        index += 1
    while value < .01 and index > 0:
        value *= (UNIT_FACTORS[units[index]] / UNIT_FACTORS[units[index - 1]]) ** 2
        index -= 1
    return f'{value:.2f} {units[index]}²'


def _read_image(path):
    """返回 uint8 BGR/灰度及规范化提示；拒绝把科学图像的 Z/T 轴当颜色。"""
    note = ''
    if Path(path).suffix.lower() in ('.tif', '.tiff'):
        import tifffile
        with tifffile.TiffFile(path) as tif:
            if len(tif.pages) != 1 or len(tif.series) != 1:
                raise ValueError('不支持多页 TIF；请选择单张二维图像')
            series, page = tif.series[0], tif.pages[0]
            axes = series.axes
            if axes not in ('YX', 'YXS', 'SYX'):
                raise ValueError(f'不支持 TIF 维度 {axes} / {series.shape}')
            photo = page.photometric.name
            if photo not in ('MINISBLACK', 'MINISWHITE', 'RGB'):
                raise ValueError(f'不支持 TIF 色彩类型 {photo}')
            if (axes != 'YX') != (photo == 'RGB'):
                raise ValueError('不支持非二维灰度或非 RGB 的 TIF 通道布局')
            img = series.asarray()
            if axes == 'SYX':
                img = np.moveaxis(img, 0, -1)
            if img.ndim == 3:
                if img.shape[2] not in (3, 4):
                    raise ValueError('TIF 仅支持 RGB / RGBA 三或四通道')
                img = img[:, :, :3][:, :, ::-1]  # RGB(A) → BGR，不改变空间尺寸
            elif photo == 'MINISWHITE' and img.dtype in (np.uint8, np.uint16):
                img = np.iinfo(img.dtype).max - img
    else:
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is not None and img.ndim == 3 and img.shape[2] == 4:
            img = img[:, :, :3]
    if img is None or img.size == 0:
        raise ValueError('无法解码图片')
    if img.ndim not in (2, 3) or (img.ndim == 3 and img.shape[2] != 3):
        raise ValueError(f'不支持图像维度 {img.shape}；需要灰度、RGB 或 RGBA')
    if img.dtype not in (np.uint8, np.uint16):
        raise ValueError(f'不支持数据类型 {img.dtype}；需要 uint8 / uint16')
    if img.dtype == np.uint16:
        img = (img.astype(np.float64) / max(1, int(img.max())) * 255).astype(np.uint8)
        note = '；16 位按最大值缩放至 8 位，未缩放图像尺寸'
    return np.ascontiguousarray(img), note


def _overlaps(candidate, objects):
    """只检查 bbox 交集内的真实像素，不能把孔洞当作已占用面积。"""
    x, y, w, h = candidate['rect']
    for obj in objects:
        ox, oy, ow, oh = obj['rect']
        left, top = max(x, ox), max(y, oy)
        right, bottom = min(x + w, ox + ow), min(y + h, oy + oh)
        if left < right and top < bottom:
            a = candidate['mask'][top - y:bottom - y, left - x:right - x]
            b = obj['mask'][top - oy:bottom - oy, left - ox:right - ox]
            if np.any((a != 0) & (b != 0)):
                return True
    return False


class DefectAreaTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.img_cv = None
        self.gray = None
        self.objects = []
        self.rois = []
        self.measurements = []
        self._next_distance_id = 1
        self.selected_roi_id = -1
        self._next_roi_id = 1
        self._batch_queue = []
        self._batch_active = False
        self._batch_generation = 0
        self.unit_per_px = None
        self.unit = 'µm'
        self._preview = None
        self._detect_timer = QTimer(self)
        self._detect_timer.setSingleShot(True)
        self._detect_timer.setInterval(150)
        self._detect_timer.timeout.connect(self.detect_now)
        self._slider_dragging = False
        self._batch_timer = QTimer(self)
        self._batch_timer.setSingleShot(True)
        self._batch_timer.setInterval(0)
        self._batch_timer.timeout.connect(self._run_next_batch)
        self.canvas = AreaCanvas(self)
        self._build_ui()
        self.canvas.calib_drawn.connect(self.calibrate)
        self.canvas.distance_added.connect(self.add_distance)
        self.canvas.distance_delete_clicked.connect(self.delete_distance)
        self.canvas.roi_rect.connect(self.set_roi_rect)
        self.canvas.roi_poly.connect(self.set_roi_poly)
        self.canvas.roi_pick.connect(self.pick_roi)
        self.canvas.mode_cancel.connect(lambda: self.set_mode('none'))
        self.canvas.add_click.connect(self.preview_add)
        self.canvas.add_confirm.connect(self.confirm_add)
        self.canvas.add_cancel.connect(self.cancel_add)
        self.canvas.delete_click.connect(self.delete_at)
        self._refresh_results()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter)
        sidebar = QFrame()
        sidebar.setObjectName('SidebarCard')
        sidebar.setMinimumWidth(280)
        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(0, 0, 0, 0)
        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.sidebar_scroll)
        content = QWidget()
        panel = QVBoxLayout(content)
        panel.setContentsMargins(16, 16, 16, 16)
        panel.setSpacing(14)
        self.sidebar_scroll.setWidget(content)
        self.btn_load = create_primary_button('导入图片', lambda: self.load_image())
        panel.addWidget(self.btn_load)
        self.tools = QButtonGroup(self)
        self.tools.setExclusive(True)
        self._tool_buttons = {}

        self.sections = {}

        def group(title, expanded=False):
            section = CollapsibleSection(title)
            self.sections[title] = section
            panel.addWidget(section)
            section.setExpanded(expanded)
            return section

        def tool(target, text, mode):
            button = create_secondary_button(text, checkable=True)
            self.tools.addButton(button)
            self._tool_buttons[mode] = button
            button.clicked.connect(
                lambda: self.set_mode('none' if self.canvas.mode == mode else mode))
            target.addWidget(button)
            return button

        calib = group('比例尺标定', expanded=True)
        self.btn_calib = tool(calib, '划线标定', 'calibrate')
        self.btn_clear_calib = create_secondary_button('清除标定', self.clear_calibration)
        calib.addWidget(self.btn_clear_calib)
        self.lbl_calib = create_info_label('未标定')
        calib.addWidget(self.lbl_calib)
        distance = group('距离测量')
        self.btn_measure = tool(distance, '距离测量', 'measure')
        self.btn_distance_delete = tool(distance, '删除测距', 'distance_delete')
        self.btn_clear_distances = create_secondary_button('清空测距', self.clear_distances)
        distance.addWidget(self.btn_clear_distances)
        distance.addWidget(create_info_label('标定后依次点击两点；小于 7° 自动水平或垂直。'))
        self.lbl_distance_count = create_info_label('测量数量: 0')
        self.lbl_distance_min = create_info_label('最小距离: —')
        self.lbl_distance_max = create_info_label('最大距离: —')
        self.lbl_distance_mean = create_info_label('平均距离: —')
        self.lbl_distance_total = create_info_label('总距离: —')
        for label in (self.lbl_distance_count, self.lbl_distance_min,
                      self.lbl_distance_max, self.lbl_distance_mean,
                      self.lbl_distance_total):
            distance.addWidget(label)
        self.distance_table = QTableWidget(0, 3)
        self.distance_table.setHorizontalHeaderLabels(['#', '距离', '像素距离'])
        self.distance_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.distance_table.verticalHeader().setVisible(False)
        self.distance_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.distance_table.setMinimumHeight(120)
        distance.addWidget(self.distance_table)
        self.btn_export_distances = create_secondary_button('导出距离 CSV', lambda: self.export_distance_csv())
        distance.addWidget(self.btn_export_distances)
        roi = group('检测区域', expanded=True)
        roi_row1 = QHBoxLayout()
        roi_row1.setSpacing(8)
        self.btn_roi_rect = tool(roi_row1, '矩形框选', 'rect')
        self.btn_roi_poly = tool(roi_row1, '多边形框选', 'poly')
        roi_row1.setStretch(0, 1)
        roi_row1.setStretch(1, 1)
        roi.addLayout(roi_row1)
        roi_row2 = QHBoxLayout()
        roi_row2.setSpacing(8)
        self.btn_delete_roi = create_secondary_button('删除当前 ROI', self.delete_current_roi)
        self.btn_clear_roi = create_secondary_button('清空全部 ROI', self.clear_roi)
        roi_row2.addWidget(self.btn_delete_roi)
        roi_row2.addWidget(self.btn_clear_roi)
        roi_row2.setStretch(0, 1)
        roi_row2.setStretch(1, 1)
        roi.addLayout(roi_row2)
        detection = group('阈值检测', expanded=True)
        self.lbl_current_roi = create_info_label('当前 ROI：未选择')
        detection.addWidget(self.lbl_current_roi)
        self.btn_detect = create_primary_button('检测全部 ROI', self.toggle_detection)
        detection.addWidget(self.btn_detect)
        detection.addWidget(create_info_label('先框选 ROI，再开始检测；导入图片不会自动检测。'))
        self.chk_bright = create_checkbox('检测亮色缺陷', True, self.schedule_detection)
        detection.addWidget(self.chk_bright)
        detection.addWidget(QLabel('二值化阈值'))
        self.slider_thresh, self.lbl_thresh = create_slider_with_label(0, 255, 127)
        self.slider_thresh.valueChanged.connect(self.schedule_detection)
        self.slider_thresh.sliderPressed.connect(lambda: setattr(self, '_slider_dragging', True))
        self.slider_thresh.sliderReleased.connect(self._on_slider_released)
        detection.addWidget(self.lbl_thresh)
        detection.addWidget(self.slider_thresh)
        self.btn_otsu = create_secondary_button('自动阈值 (Otsu)', self.auto_otsu)
        detection.addWidget(self.btn_otsu)
        detection.addWidget(QLabel('最小面积（像素）'))
        self.slider_min_area = create_slider(1, 100000, 1)
        self.spin_min_area = QSpinBox()
        self.spin_min_area.setRange(1, 100000)
        self.spin_min_area.setValue(1)
        self.spin_min_area.setSuffix(' px²')
        self.spin_min_area.setKeyboardTracking(False)
        self.spin_min_area.setAccessibleName('最小面积（像素）')
        self.spin_min_area.valueChanged.connect(self.slider_min_area.setValue)
        self.slider_min_area.valueChanged.connect(self.spin_min_area.setValue)
        self.slider_min_area.valueChanged.connect(self.schedule_detection)
        detection.addWidget(self.spin_min_area)
        detection.addWidget(self.slider_min_area)
        detection.addWidget(create_info_label('开始检测后，调节当前 ROI 的参数会重新检测，并清空手动增删。'))
        manual = group('手动修正')
        self.btn_add = tool(manual, '添加遗漏', 'add')
        self.btn_del = tool(manual, '删除误检', 'delete')
        manual.addWidget(create_info_label('添加：单击预览，双击确认，ESC 取消。\n右键拖动平移，滚轮缩放。'))
        results = group('测量结果')
        self.lbl_count = create_info_label()
        self.lbl_total = create_info_label()
        results.addWidget(self.lbl_count)
        results.addWidget(self.lbl_total)
        self.roi_table = QTableWidget(0, 7)
        self.roi_table.setHorizontalHeaderLabels(
            ['ROI', '状态', '阈值', '亮/暗', '最小面积', '缺陷数', '总面积'])
        self.roi_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.roi_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.roi_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.roi_table.verticalHeader().setVisible(False)
        self.roi_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.roi_table.itemSelectionChanged.connect(self.select_roi_from_table)
        self.roi_table.setMinimumHeight(130)
        results.addWidget(self.roi_table)
        results.addWidget(create_info_label('当前 ROI 缺陷明细'))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['编号', '像素面积', '实际面积', '来源'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.select_object)
        self.table.setMinimumHeight(160)
        self.table.setMinimumWidth(0)
        results.addWidget(self.table)
        self.btn_export = create_secondary_button('导出 CSV', lambda: self.export_csv())
        results.addWidget(self.btn_export)
        self.lbl_status = create_info_label('请先导入图片；未标定时按像素面积统计。')
        self.lbl_status.setTextFormat(Qt.TextFormat.PlainText)
        panel.addWidget(self.lbl_status)
        panel.addStretch()
        self.splitter.addWidget(sidebar)
        self.splitter.addWidget(self.canvas)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([330, 638])

    def _status(self, text, error=False):
        self.lbl_status.setText(text)
        if error:
            self.sidebar_scroll.ensureWidgetVisible(self.lbl_status)

    def set_mode(self, mode):
        if mode == 'measure' and self.unit_per_px is None:
            self._status('请先完成比例尺标定，再进行距离测量', error=True)
            mode = 'none'
        self.canvas.set_mode(mode)
        self.tools.setExclusive(False)
        for name, button in self._tool_buttons.items():
            button.blockSignals(True)
            button.setChecked(name == mode)
            button.blockSignals(False)
        self.tools.setExclusive(True)

    def load_image(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, '选择缺陷图片', '', '图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)')
        if not path:
            return False
        # 导入只解码和显示原图，绝不在此执行连通域检测或创建掩膜。
        try:
            img, note = _read_image(path)
            gray = img.copy() if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        except (OSError, ValueError, cv2.error, zlib.error, ImportError) as exc:
            self._status(f'图片加载失败：{exc}', error=True)
            return False
        self._detect_timer.stop()
        self._invalidate_batch()
        self.img_cv, self.gray = img, gray
        self.unit_per_px, self.unit = None, 'µm'
        self.rois.clear()
        self.measurements.clear()
        self._next_distance_id = 1
        self.selected_roi_id = -1
        self._next_roi_id = 1
        self.cancel_add()
        self.btn_detect.setText('检测全部 ROI')
        self.set_mode('none')
        self.canvas.set_image(img)
        self.objects[:] = []
        self.canvas.selected_index = -1
        self.lbl_calib.setText('未标定')
        self._refresh_results()
        self._status(f'已加载 {Path(path).name}（{gray.shape[1]} × {gray.shape[0]} px）{note}；请先框选 ROI，再点击开始检测')
        return True

    def _ask_calibration(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('比例尺标定')
        layout = QFormLayout(dialog)
        length = QDoubleSpinBox()
        length.setObjectName('calibrationLength')
        length.setDecimals(9)
        length.setRange(0, 1e12)
        length.setValue(0)
        units = QComboBox()
        units.setObjectName('calibrationUnit')
        units.addItems(list(UNIT_FACTORS))
        units.setCurrentText(self.unit)
        layout.addRow('实际长度（大于 0）', length)
        layout.addRow('长度单位', units)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(length.value() > 0)
        length.valueChanged.connect(
            lambda value: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(value > 0))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        length.setFocus()
        length.lineEdit().selectAll()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return length.value(), units.currentText()

    def calibrate(self, p1, p2, length=None, unit=None):
        if self.gray is None:
            self._status('请先导入图片', error=True)
            return False
        distance = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if not math.isfinite(distance) or distance < 10:
            self._status('标定线太短（至少 10px）', error=True)
            return False
        if length is None:
            answer = self._ask_calibration()
            if answer is None:
                return False
            length, unit = answer
        unit = self.unit if unit is None else unit
        if not math.isfinite(length) or length <= 0 or unit not in UNIT_FACTORS:
            self._status('标定失败：实际长度必须大于 0，单位须为 nm/µm/mm/cm/m', error=True)
            return False
        self.unit_per_px, self.unit = length / distance, unit
        self.canvas.set_calib((tuple(p1), tuple(p2)), f'{length:g} {unit}')
        self.lbl_calib.setText(f'已标定：1 {unit} = {1 / self.unit_per_px:.2f} px')
        self._refresh_results()
        self._status('标定已更新（未重新检测，保留手动增删）')
        return True

    def clear_calibration(self):
        self.unit_per_px = None
        self.measurements.clear()
        self._next_distance_id = 1
        self.canvas.set_calib(None)
        self.canvas.set_distances([])
        self.set_mode('none')
        self.lbl_calib.setText('未标定')
        self._refresh_results()
        self._status('已清除标定和测距，保留检测与手动增删')

    def add_distance(self, x1, y1, x2, y2, dist_px, constraint):
        if self.unit_per_px is None:
            self._status('请先完成比例尺标定，再进行距离测量', error=True)
            return False
        item = {
            'id': self._next_distance_id,
            'p1': (x1, y1),
            'p2': (x2, y2),
            'dist_px': dist_px,
            'constraint': constraint,
        }
        self._next_distance_id += 1
        self.measurements.append(item)
        self._refresh_distances()
        self._status(f"距离 #{item['id']} 已记录；继续点击两点可连续测量")
        return True

    def _refresh_distances(self):
        entries = []
        for item in self.measurements:
            label = f"#{item['id']} {item['dist_px'] * self.unit_per_px:.2f} {self.unit}"
            entries.append({
                'id': item['id'], 'p1': item['p1'], 'p2': item['p2'],
                'constraint': item['constraint'], 'label': label,
            })
        self.canvas.set_distances(entries)
        self._refresh_distance_results()

    def _refresh_distance_results(self):
        count = len(self.measurements)
        self.lbl_distance_count.setText(f'测量数量: {count}')
        stats = (self.lbl_distance_min, self.lbl_distance_max,
                 self.lbl_distance_mean, self.lbl_distance_total)
        prefixes = ('最小距离', '最大距离', '平均距离', '总距离')
        if count == 0 or self.unit_per_px is None:
            for label, prefix in zip(stats, prefixes):
                label.setText(f'{prefix}: —')
        else:
            values = [item['dist_px'] * self.unit_per_px for item in self.measurements]
            results = (min(values), max(values), float(np.mean(values)), sum(values))
            for label, prefix, value in zip(stats, prefixes, results):
                label.setText(f'{prefix}: {value:.2f} {self.unit}')
        self.distance_table.setHorizontalHeaderLabels(['#', f'距离 ({self.unit})', '距离 (px)'])
        self.distance_table.setRowCount(count)
        for row, item in enumerate(self.measurements):
            real = item['dist_px'] * (self.unit_per_px or 0)
            values = (str(item['id']), f'{real:.2f}', f"{item['dist_px']:.1f}")
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.distance_table.setItem(row, column, cell)

    def export_distance_csv(self, path=None):
        if not self.measurements:
            self._status('无距离数据可导出', error=True)
            return False
        if path is None:
            name = f'distance_{datetime.now():%Y%m%d_%H%M%S}.csv'
            path, _ = QFileDialog.getSaveFileName(self, '导出距离测量', name, 'CSV (*.csv)')
        if not path:
            return False
        temporary = None
        constraint_text = {'h': '水平', 'v': '垂直', '': '自由'}
        try:
            destination = Path(path).absolute()
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                                             dir=destination.parent, prefix='.distance_',
                                             suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                writer = csv.writer(stream)
                writer.writerow(['序号', f'距离({self.unit})', '距离(px)',
                                 '起点X', '起点Y', '终点X', '终点Y', '约束'])
                for item in self.measurements:
                    real = item['dist_px'] * self.unit_per_px
                    x1, y1 = item['p1']
                    x2, y2 = item['p2']
                    writer.writerow([
                        item['id'], round(real, 2), round(item['dist_px'], 1),
                        round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1),
                        constraint_text.get(item['constraint'], '自由'),
                    ])
            os.replace(temporary, destination)
            temporary = None
        except OSError as exc:
            self._status(f'距离 CSV 导出失败：{exc}', error=True)
            return False
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError as exc:
                    self._status(f'距离 CSV 导出失败；临时文件清理失败：{exc}', error=True)
        self._status(f'已导出距离 CSV：{path}')
        return True

    def delete_distance(self, index):
        if not 0 <= index < len(self.measurements):
            return False
        item = self.measurements.pop(index)
        self._refresh_distances()
        self._status(f"距离 #{item['id']} 已删除；其余编号不变")
        return True

    def clear_distances(self):
        self.measurements.clear()
        self._next_distance_id = 1
        self.canvas.cancel_draft()
        self._refresh_distances()
        self._status('已清空全部测距；ROI、缺陷结果和标定保留')
        return True

    def set_roi_rect(self, rect):
        if self.gray is None:
            return False
        x, y, w, h = rect
        if not all(math.isfinite(v) for v in rect) or w <= 5 or h <= 5:
            return False
        height, width = self.gray.shape
        x0, y0 = max(0, math.floor(x)), max(0, math.floor(y))
        x1, y1 = min(width, math.ceil(x + w)), min(height, math.ceil(y + h))
        if x1 - x0 <= 5 or y1 - y0 <= 5:
            return False
        mask = np.zeros_like(self.gray)
        mask[y0:y1, x0:x1] = 255
        return self._append_roi(mask, ('rect', (x0, y0, x1 - x0, y1 - y0)))

    def set_roi_poly(self, points):
        if self.gray is None or len(points) < 3:
            return False
        vertices = np.asarray(points, dtype=np.float64)
        if not np.isfinite(vertices).all():
            return False
        h, w = self.gray.shape
        vertices = np.clip(vertices, (0, 0), (w - 1, h - 1)).astype(np.int32)
        if cv2.contourArea(vertices) == 0:
            return False
        points = vertices.tolist()
        mask = polygon_to_mask(points, self.gray.shape)
        if not np.any(mask):
            return False
        return self._append_roi(mask, ('poly', points))

    def current_roi(self):
        return next((roi for roi in self.rois if roi['id'] == self.selected_roi_id), None)

    @property
    def _analysis_active(self):
        return self._batch_active or any(
            roi['status'] in ('active', 'error') for roi in self.rois)

    def _sync_parameter_widgets(self, params):
        widgets = (self.slider_thresh, self.chk_bright,
                   self.slider_min_area, self.spin_min_area)
        for widget in widgets:
            widget.blockSignals(True)
        self.slider_thresh.setValue(params['threshold'])
        self.chk_bright.setChecked(params['bright'])
        self.slider_min_area.setValue(params['min_area'])
        self.spin_min_area.setValue(params['min_area'])
        for widget in widgets:
            widget.blockSignals(False)
        self.lbl_thresh.setText(str(params['threshold']))

    def _cancel_pending_detection(self):
        """选择变化时放弃未执行的防抖，并清除与新参数不匹配的旧结果。"""
        if not self._detect_timer.isActive():
            return None
        self._detect_timer.stop()
        roi = self.current_roi()
        if roi is None or roi['status'] != 'active':
            return None
        roi['objects'] = []
        roi['status'] = 'pending'
        roi['manual_changed'] = False
        roi['area_px'] = 0
        self.canvas.selected_index = -1
        return roi['id']

    def select_roi(self, roi_id):
        roi = next((item for item in self.rois if item['id'] == roi_id), None)
        if roi is None:
            return False
        if roi_id == self.selected_roi_id:
            return True
        stale_id = self._cancel_pending_detection()
        self.cancel_add()
        self.selected_roi_id = roi_id
        self.canvas.selected_index = -1
        self._sync_parameter_widgets(roi['params'])
        self._refresh_results()
        if stale_id is not None:
            self._status(f'ROI {stale_id} 参数已保存并转为待检测；选择 ROI 不会自动重跑')
        return True

    def select_roi_from_table(self):
        rows = self.roi_table.selectionModel().selectedRows()
        if len(rows) == 1:
            roi_id = self.roi_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
            if roi_id != self.selected_roi_id:
                self.select_roi(roi_id)

    def pick_roi(self, x, y):
        ix, iy = math.floor(x), math.floor(y)
        for roi in reversed(self.rois):
            mask = roi['mask']
            if 0 <= iy < mask.shape[0] and 0 <= ix < mask.shape[1] and mask[iy, ix]:
                return self.select_roi(roi['id'])
        return False

    def _append_roi(self, mask, roi):
        self._cancel_pending_detection()
        current = self.current_roi()
        params = dict(current['params']) if current is not None else {
            'threshold': self.slider_thresh.value(),
            'bright': self.chk_bright.isChecked(),
            'min_area': self.slider_min_area.value(),
        }
        item = {
            'id': self._next_roi_id,
            'roi': roi,
            'mask': mask,
            'params': params,
            'objects': [],
            'status': 'pending',
            'manual_changed': False,
            'area_px': 0,
        }
        self._next_roi_id += 1
        self.rois.append(item)
        self.canvas.cancel_draft()
        self.select_roi(item['id'])
        self._run_roi(item)
        self._status(f"ROI {item['id']} 已添加并自动检测；再次点击“检测全部 ROI”可整批重跑")
        return True

    def delete_current_roi(self):
        roi = self.current_roi()
        if roi is None:
            return False
        self._cancel_pending_detection()
        self.cancel_add()
        self.rois.remove(roi)
        self._batch_queue = [roi_id for roi_id in self._batch_queue if roi_id != roi['id']]
        self.selected_roi_id = self.rois[-1]['id'] if self.rois else -1
        if not self.rois:
            self._invalidate_batch()
        current = self.current_roi()
        if current is not None:
            self._sync_parameter_widgets(current['params'])
        self.canvas.selected_index = -1
        self._refresh_results()
        self._status(f"ROI {roi['id']} 已删除；其他 ROI 编号与结果不变")
        return True

    def _invalidate_batch(self):
        self._batch_generation += 1
        self._batch_queue.clear()
        self._batch_timer.stop()
        self._batch_active = False

    def clear_roi(self):
        if self.gray is None:
            return False
        self._detect_timer.stop()
        self._invalidate_batch()
        self.cancel_add()
        self.rois.clear()
        self._next_roi_id = 1
        self.selected_roi_id = -1
        self.canvas.selected_index = -1
        self.btn_detect.setText('检测全部 ROI')
        self._refresh_results()
        self._status('已清空全部 ROI；图片和标定保留')
        return True

    def roi_area_px(self, roi_id):
        roi = next((item for item in self.rois if item['id'] == roi_id), None)
        return 0 if roi is None else roi['area_px']

    def union_area_px(self):
        if self.gray is None:
            return 0
        union = np.zeros_like(self.gray)
        for roi in self.rois:
            for obj in roi['objects']:
                x, y, w, h = obj['rect']
                union[y:y + h, x:x + w] |= obj['mask']
        return cv2.countNonZero(union)

    def toggle_detection(self):
        has_pending = any(roi['status'] == 'pending' for roi in self.rois)
        if self._batch_active or (self._analysis_active and not has_pending):
            self._detect_timer.stop()
            self._invalidate_batch()
            self.cancel_add()
            for roi in self.rois:
                roi['objects'] = []
                roi['status'] = 'pending'
                roi['manual_changed'] = False
                roi['area_px'] = 0
            self.canvas.selected_index = -1
            self._refresh_results()
            self._status('已停止并清空全部检测结果；ROI 与参数保留')
            return True
        if self.gray is None:
            self._status('请先导入图片', error=True)
            return False
        if not self.rois:
            self._status('请先框选 ROI，再开始检测；不会默认检测全图', error=True)
            return False
        self._detect_timer.stop()
        self._invalidate_batch()
        self.cancel_add()
        current = self.current_roi()
        if current is not None:
            current['params'] = {
                'threshold': self.slider_thresh.value(),
                'bright': self.chk_bright.isChecked(),
                'min_area': self.slider_min_area.value(),
            }
        for roi in self.rois:
            roi['objects'] = []
            roi['status'] = 'pending'
            roi['manual_changed'] = False
            roi['area_px'] = 0
        self._batch_queue = [roi['id'] for roi in self.rois]
        self._batch_active = True
        self._run_next_batch()
        return True

    def _run_next_batch(self):
        if not self._batch_active:
            return
        if not self._batch_queue:
            self._batch_active = False
            self._refresh_results()
            self._status('全部 ROI 检测完成；选择某框调参只会重跑该框')
            return
        roi_id = self._batch_queue.pop(0)
        roi = next((item for item in self.rois if item['id'] == roi_id), None)
        if roi is None:
            self._run_next_batch()
            return
        total = len(self.rois)
        self._run_roi(roi)
        self._status(f"正在检测 ROI {roi_id}（{total - len(self._batch_queue)}/{total}）")
        self._batch_timer.start()

    def _run_roi(self, roi):
        params = roi['params']
        try:
            objects = detect_defects(
                self.gray, params['threshold'], params['bright'],
                params['min_area'], roi['mask'])
        except (ValueError, cv2.error) as exc:
            roi['objects'] = []
            roi['status'] = 'error'
            roi['manual_changed'] = False
            roi['area_px'] = 0
            self._refresh_results()
            self._status(f"ROI {roi['id']} 检测失败：{exc}", error=True)
            return False
        for obj in objects:
            obj['source'] = '自动'
            obj['roi_id'] = roi['id']
        roi['objects'] = objects
        roi['status'] = 'active'
        roi['manual_changed'] = False
        roi['area_px'] = sum(obj['area_px'] for obj in objects)
        if roi['id'] == self.selected_roi_id:
            self.canvas.selected_index = -1
        self._refresh_results()
        return True

    def _on_slider_released(self):
        self._slider_dragging = False
        roi = self.current_roi()
        if roi is not None and roi['status'] == 'active':
            self.detect_now()

    def schedule_detection(self, *_):
        self.lbl_thresh.setText(str(self.slider_thresh.value()))
        self.cancel_add()
        roi = self.current_roi()
        if roi is None:
            if self.gray is not None:
                self._status('参数已保存；框选 ROI 后点击“检测全部 ROI”')
            return
        roi['params'] = {
            'threshold': self.slider_thresh.value(),
            'bright': self.chk_bright.isChecked(),
            'min_area': self.slider_min_area.value(),
        }
        if self._slider_dragging:
            self._status(f"拖动阈值中；松开后重跑 ROI {roi['id']}")
            return
        if roi['status'] == 'active':
            self._detect_timer.start()
            self._status(f"等待重新检测 ROI {roi['id']}；仅重跑该框并清空其手动增删")
        elif self.gray is not None:
            self._status(f"ROI {roi['id']} 参数已保存；点击“检测全部 ROI”后生效")
        self._refresh_results()

    def detect_now(self):
        self._detect_timer.stop()
        self.cancel_add()
        roi = self.current_roi()
        if self.gray is None or roi is None or roi['status'] != 'active':
            return False
        had_manual = roi['manual_changed']
        if not self._run_roi(roi):
            return False
        self._status(
            f"ROI {roi['id']} 检测完成；该框手动增删已清空" if had_manual
            else f"ROI {roi['id']} 检测完成；其他 ROI 未改变")
        return True

    def _flush_detection(self):
        return self.detect_now() if self._detect_timer.isActive() else True

    def auto_otsu(self):
        roi = self.current_roi()
        if self.gray is None:
            self._status('请先导入图片', error=True)
            return False
        if roi is None:
            self._status('请先选择 ROI；Otsu 只计算当前框', error=True)
            return False
        threshold = otsu_threshold(self.gray, roi['mask'])
        self.slider_thresh.setValue(threshold)
        if roi['status'] == 'active':
            return self.detect_now()
        self._status(f"ROI {roi['id']} 的 Otsu 阈值已设为 {threshold}；点击“检测全部 ROI”后生效")
        return True

    def _area_label(self, area_px):
        area = compute_real_area(area_px, self.unit_per_px)
        return f'{area_px}px²' if area is None else fmt_area(area, self.unit)

    def _refresh_results(self):
        self.objects[:] = [obj for roi in self.rois for obj in roi['objects']]
        total_px = self.union_area_px()
        total = self._area_label(total_px)
        suffix = '（未标定）' if self.unit_per_px is None else ''
        summary = f'全部 ROI 总面积（重叠去重）: {total} · {len(self.rois)} 个区域{suffix}'
        current = self.current_roi()
        current_objects = [] if current is None else current['objects']
        self.lbl_count.setText(f"ROI 数量: {len(self.rois)} · 当前框缺陷: {len(current_objects)}")
        self.lbl_total.setText(f'全部 ROI 总面积（重叠去重）: {total}{suffix}')
        self.lbl_current_roi.setText(
            '当前 ROI：未选择' if current is None else f"当前 ROI：{current['id']}")
        has_pending = any(roi['status'] == 'pending' for roi in self.rois)
        self.btn_detect.setText(
            '停止并清空' if self._batch_active or (self._analysis_active and not has_pending)
            else '检测全部 ROI')

        self.roi_table.blockSignals(True)
        self.roi_table.setRowCount(len(self.rois))
        selected_row = -1
        status_text = {'pending': '待检测', 'active': '已检测', 'error': '检测失败'}
        entries = []
        for row, roi in enumerate(self.rois):
            if roi['id'] == self.selected_roi_id:
                selected_row = row
            params = roi['params']
            values = (
                f"ROI {roi['id']}", status_text[roi['status']], str(params['threshold']),
                '亮' if params['bright'] else '暗', str(params['min_area']),
                str(len(roi['objects'])), self._area_label(roi['area_px']))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, roi['id'])
                self.roi_table.setItem(row, column, item)
            label = (f"ROI {roi['id']} 待检测" if roi['status'] == 'pending'
                     else f"ROI {roi['id']} 检测失败" if roi['status'] == 'error'
                     else f"ROI {roi['id']} {self._area_label(roi['area_px'])}")
            entries.append({'id': roi['id'], 'roi': roi['roi'], 'label': label})
        if selected_row >= 0:
            self.roi_table.selectRow(selected_row)
        else:
            self.roi_table.clearSelection()
        self.roi_table.blockSignals(False)
        self.canvas.set_rois(entries, self.selected_roi_id)
        self.canvas.set_objects(self.objects, summary)

        self.table.blockSignals(True)
        self.table.setRowCount(len(current_objects))
        for row, obj in enumerate(current_objects):
            values = (str(obj['id']), str(obj['area_px']),
                      '未标定' if self.unit_per_px is None else self._area_label(obj['area_px']),
                      obj.get('source', '自动'))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self.btn_measure.setEnabled(self.unit_per_px is not None)
        self._refresh_distances()

    def select_object(self):
        rows = self.table.selectionModel().selectedRows()
        current = self.current_roi()
        index = -1
        if current is not None and len(rows) == 1:
            obj = current['objects'][rows[0].row()]
            index = next((i for i, candidate in enumerate(self.objects)
                          if candidate is obj), -1)
        if index != self.canvas.selected_index:
            self.canvas.selected_index = index
            self.canvas.update()

    def cancel_add(self):
        self._preview = None
        self.canvas.set_preview(None)

    def preview_add(self, x, y):
        self.cancel_add()
        if self.gray is None or not self._flush_detection():
            return False
        roi = self.current_roi()
        if roi is None or roi['status'] != 'active':
            self._status('请先选择已检测的 ROI，再添加遗漏', error=True)
            return False
        h, w = self.gray.shape
        if not (0 <= x < w and 0 <= y < h):
            self._status('点击处未识别到缺陷（图像外）')
            return False
        cx, cy = int(x), int(y)
        if not roi['mask'][cy, cx]:
            self._status(f"添加拒绝：点击必须在当前 ROI {roi['id']} 内", error=True)
            return False
        x0, y0 = max(0, cx - 40), max(0, cy - 40)
        window = self.gray[y0:min(h, cy + 41), x0:min(w, cx + 41)]
        window_roi = roi['mask'][y0:min(h, cy + 41), x0:min(w, cx + 41)]
        if int(window.max()) == int(window.min()):
            self._status('点击处未识别到缺陷（局部窗口无对比度）')
            return False
        candidates = detect_defects(window, otsu_threshold(window, window_roi),
                                    bright=roi['params']['bright'], min_area=1,
                                    roi_mask=window_roi)
        lx, ly = x - x0, y - y0
        chosen = next((obj for obj in candidates if mask_hit(obj, lx, ly, 0)), None)
        if chosen is None and candidates:
            nearest = min(candidates, key=lambda obj: math.hypot(obj['cx'] - lx, obj['cy'] - ly))
            if math.hypot(nearest['cx'] - lx, nearest['cy'] - ly) <= 20:
                chosen = nearest
        if chosen is None:
            self._status('点击处未识别到缺陷')
            return False
        bx, by, bw, bh = chosen['rect']
        chosen['rect'] = (bx + x0, by + y0, bw, bh)
        chosen['cx'] += x0
        chosen['cy'] += y0
        chosen['points'] = [[px + x0, py + y0] for px, py in chosen['points']]
        # mask 始终为 bbox 局部数组，绝不能随坐标平移。
        chosen['source'] = '手动'
        chosen['roi_id'] = roi['id']
        if _overlaps(chosen, roi['objects']):
            self._status('添加拒绝：与当前 ROI 已有缺陷像素重叠，不能重复计数', error=True)
            return False
        self._preview = chosen
        self.canvas.set_preview(chosen)
        self._status(f"预览 {self._area_label(chosen['area_px'])}；双击确认，ESC 取消")
        return True

    def confirm_add(self):
        if not self._flush_detection() or self._preview is None:
            return False
        roi = self.current_roi()
        candidate = self._preview
        self.cancel_add()
        if roi is None or roi['status'] != 'active' or candidate['roi_id'] != roi['id']:
            return False
        if _overlaps(candidate, roi['objects']):
            self._status('添加拒绝：与当前 ROI 已有缺陷像素重叠，不能重复计数', error=True)
            return False
        candidate['id'] = max((obj['id'] for obj in roi['objects']), default=0) + 1
        roi['objects'].append(candidate)
        roi['manual_changed'] = True
        roi['area_px'] = sum(obj['area_px'] for obj in roi['objects'])
        self._refresh_results()
        self._status(f"已添加到 ROI {roi['id']}；仅重跑该框会清空其手动增删")
        return True

    def delete_at(self, x, y):
        if not self._flush_detection():
            return False
        roi = self.current_roi()
        if roi is None or roi['status'] != 'active':
            self._status('请先选择已检测的 ROI，再删除误检', error=True)
            return False
        index = hit_index(roi['objects'], x, y)
        if index < 0:
            return False
        self.cancel_add()
        del roi['objects'][index]
        roi['manual_changed'] = True
        roi['area_px'] = sum(obj['area_px'] for obj in roi['objects'])
        self._refresh_results()
        self._status(f"已从 ROI {roi['id']} 删除缺陷；其他 ROI 未改变")
        return True

    def export_csv(self, path=None):
        if self._batch_active:
            self._status('批量检测进行中，请等待完成或停止后再导出 CSV', error=True)
            return False
        if not self._flush_detection():
            return False
        if not self.objects:
            self._status('无数据可导出', error=True)
            return False
        if path is None:
            name = f'defect_area_{datetime.now():%Y%m%d_%H%M%S}.csv'
            path, _ = QFileDialog.getSaveFileName(self, '导出缺陷面积', name, 'CSV (*.csv)')
        if not path:
            return False
        if not self._flush_detection():
            return False
        if not self.objects:
            self._status('无数据可导出', error=True)
            return False
        temporary = None
        try:
            # 同目录临时文件 + 原子替换，写入失败不截断旧导出文件。
            destination = Path(path).absolute()
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                                             dir=destination.parent, prefix='.defect_area_',
                                             suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                writer = csv.writer(stream)
                writer.writerow(CSV_COLUMNS)
                for roi in self.rois:
                    for obj in roi['objects']:
                        real = compute_real_area(obj['area_px'], self.unit_per_px)
                        writer.writerow([
                            roi['id'], obj['id'], obj['area_px'],
                            '' if real is None else f'{real:.6g}',
                            '未标定' if real is None else f'{self.unit}²',
                            f"{obj['cx']:.10g}", f"{obj['cy']:.10g}",
                            obj.get('source', '自动')])
            os.replace(temporary, destination)
            temporary = None
        except OSError as exc:
            self._status(f'CSV 导出失败：{exc}', error=True)
            return False
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError as exc:
                    self._status(f'CSV 导出失败；临时文件清理失败：{exc}', error=True)
        self._status(f'已导出 CSV：{path}')
        return True
