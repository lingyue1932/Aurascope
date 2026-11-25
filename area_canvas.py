"""缺陷面积画布：仅渲染、坐标变换及交互，不持有检测/标定业务逻辑。"""

import math

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QImage, QPainter, QPainterPath,
                         QPen, QPolygonF)
from PyQt6.QtWidgets import QWidget

from ui_components import paint_empty_state


def mask_to_qimage(mask):
    """局部 mask 逐像素着色；copy 使图像不依赖 numpy 临时内存。"""
    h, w = mask.shape
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[mask != 0] = (0, 200, 120, 100)
    return QImage(rgba.data, w, h, rgba.strides[0],
                  QImage.Format.Format_RGBA8888).copy()


def mask_hit(obj, x, y, tolerance=2):
    """真实填充像素命中；只检查鼠标附近的小窗口，孔洞内部不会命中。"""
    bx, by, w, h = obj['rect']
    lx, ly = x - bx, y - by
    ix, iy = math.floor(lx), math.floor(ly)
    mask = obj['mask']
    if 0 <= ix < w and 0 <= iy < h and mask[iy, ix]:
        return True
    if tolerance <= 0:
        return False
    x0, y0 = max(0, math.floor(lx - tolerance)), max(0, math.floor(ly - tolerance))
    x1, y1 = min(w, math.ceil(lx + tolerance) + 1), min(h, math.ceil(ly + tolerance) + 1)
    if x0 >= x1 or y0 >= y1:
        return False
    ys, xs = np.nonzero(mask[y0:y1, x0:x1])
    return bool(np.any((xs + x0 - lx) ** 2 + (ys + y0 - ly) ** 2 <= tolerance ** 2))


def hit_index(objects, x, y, roi_id=None):
    """删除及悬停共用，后绘制的对象优先；可限定当前 ROI。"""
    for index in range(len(objects) - 1, -1, -1):
        if roi_id is not None and objects[index].get('roi_id') != roi_id:
            continue
        if mask_hit(objects[index], x, y):
            return index
    return -1


SNAP_DEG = 7


def snap_endpoint(p1, p2, threshold=SNAP_DEG):
    """复用距离测量的 7° 规则：近水平对齐 y，近垂直对齐 x。"""
    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
    if abs(dx) < 2 and abs(dy) < 2:
        return QPointF(p2), ''
    angle = math.degrees(math.atan2(abs(dy), abs(dx)))
    if angle < threshold:
        return QPointF(p2.x(), p1.y()), 'h'
    if angle > 90 - threshold:
        return QPointF(p1.x(), p2.y()), 'v'
    return QPointF(p2), ''


def distance_hit_index(entries, x, y, tolerance=2):
    """按点到线段距离命中测距线，后绘制的优先。"""
    for index in range(len(entries) - 1, -1, -1):
        x1, y1 = entries[index]['p1']
        x2, y2 = entries[index]['p2']
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            distance = math.hypot(x - x1, y - y1)
        else:
            t = max(0., min(1., ((x - x1) * dx + (y - y1) * dy) / length_sq))
            distance = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
        if distance <= tolerance:
            return index
    return -1


class AreaCanvas(QWidget):
    calib_drawn = pyqtSignal(tuple, tuple)
    distance_added = pyqtSignal(float, float, float, float, float, str)
    distance_delete_clicked = pyqtSignal(int)
    roi_rect = pyqtSignal(tuple)
    roi_poly = pyqtSignal(list)
    roi_pick = pyqtSignal(float, float)
    mode_cancel = pyqtSignal()
    add_click = pyqtSignal(float, float)
    add_confirm = pyqtSignal()
    add_cancel = pyqtSignal()
    delete_click = pyqtSignal(float, float)
    empty_import = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 180)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.img_qt = None
        self.scale = 1.0
        self.offset = QPointF()
        self.mode = 'none'
        self.roi_entries = []
        self.selected_roi_id = -1
        self.calib_line = None
        self.calib_label = ''
        self.distance_entries = []
        self.pending_distance = None
        self.hovered_distance_index = -1
        self._drag_constraint = ''
        self.objects = []
        self.summary = ''
        self.preview = None
        self._mask_images = []
        self._preview_image = None
        self.hovered_index = -1
        self.selected_index = -1
        self.poly_drawing = []
        self._drag_start = None
        self._drag_end = None
        self._drag_interrupted = False
        self._mouse_img = QPointF()
        self._panning = False
        self._last_pos = QPointF()
        self.label_font = QFont(self.font())
        self.label_font.setPixelSize(12)

    def set_image(self, img):
        rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB if img.ndim == 2 else cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        h, w = rgb.shape[:2]
        self.img_qt = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.cancel_draft()
        self._panning = False
        self.unsetCursor()
        self.set_rois([], -1)
        self.set_calib(None)
        self.set_distances([])
        self.selected_index = -1
        self.set_objects([])
        self.set_preview(None)
        self.fit_in_view()

    def fit_in_view(self):
        if self.img_qt is not None:
            self.scale = min(50., max(.01, min(self.width() / self.img_qt.width(),
                                               self.height() / self.img_qt.height()) * .9))
            self.offset = QPointF((self.width() - self.img_qt.width() * self.scale) / 2,
                                  (self.height() - self.img_qt.height() * self.scale) / 2)
            self.update()

    def widget_to_img(self, pos):
        return (pos - self.offset) / self.scale

    def img_to_widget(self, pos):
        return pos * self.scale + self.offset

    def _clamped(self, pos):
        return QPointF(min(max(0., pos.x()), float(self.img_qt.width())),
                       min(max(0., pos.y()), float(self.img_qt.height())))

    def set_mode(self, mode):
        self.cancel_draft()
        self.add_cancel.emit()
        self.mode = mode
        self.hovered_index = -1
        self.update()

    def set_rois(self, entries, selected_id):
        """entries = [{'id': int, 'roi': ('rect'|'poly', data), 'label': str}, ...]。"""
        self.roi_entries = [dict(entry) for entry in entries]
        self.selected_roi_id = selected_id
        self.update()

    def set_calib(self, line, label=''):
        self.calib_line, self.calib_label = line, label
        self.update()

    def set_distances(self, entries):
        self.distance_entries = [dict(entry) for entry in entries]
        self.hovered_distance_index = -1
        self.update()

    def set_objects(self, objects, summary=''):
        self.objects = objects
        self.summary = summary
        self._mask_images = [mask_to_qimage(o['mask']) for o in objects]
        self.hovered_index = -1
        if not 0 <= self.selected_index < len(objects):
            self.selected_index = -1
        self.update()

    def set_preview(self, obj):
        self.preview = obj
        self._preview_image = None if obj is None else mask_to_qimage(obj['mask'])
        self.update()

    def cancel_draft(self):
        self.poly_drawing = []
        self.pending_distance = None
        self.hovered_distance_index = -1
        self._drag_start = self._drag_end = None
        self._drag_interrupted = False
        self._drag_constraint = ''
        self.update()

    def mousePressEvent(self, event):
        if self.img_qt is None:
            return
        self.setFocus()
        if event.button() == Qt.MouseButton.RightButton:
            self._panning = True
            if self._drag_start is not None:
                self._drag_interrupted = True
            self._last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton or self._panning:
            return
        p = self.widget_to_img(event.position())
        if self.mode == 'none':
            self.roi_pick.emit(p.x(), p.y())
        elif self.mode == 'add':
            self.add_click.emit(p.x(), p.y())
        elif self.mode == 'delete':
            self.delete_click.emit(p.x(), p.y())
        elif self.mode == 'distance_delete':
            index = distance_hit_index(self.distance_entries, p.x(), p.y(),
                                       tolerance=2 / self.scale)
            if index >= 0:
                self.distance_delete_clicked.emit(index)
        elif self.mode in ('rect', 'calibrate'):
            self._drag_interrupted = False
            self._drag_constraint = ''
            self._drag_start = self._drag_end = self._clamped(p)
        elif self.mode == 'measure':
            p = self._clamped(p)
            if self.pending_distance is None:
                self.pending_distance = p
            else:
                snapped, constraint = snap_endpoint(self.pending_distance, p)
                dist_px = math.hypot(snapped.x() - self.pending_distance.x(),
                                     snapped.y() - self.pending_distance.y())
                if dist_px > 0:
                    self.distance_added.emit(
                        self.pending_distance.x(), self.pending_distance.y(),
                        snapped.x(), snapped.y(), dist_px, constraint)
                self.pending_distance = None
        elif self.mode == 'poly':
            p = self._clamped(p)
            point = (p.x(), p.y())
            if not self.poly_drawing or point != self.poly_drawing[-1]:
                self.poly_drawing.append(point)
        self.update()

    def mouseMoveEvent(self, event):
        if self.img_qt is None:
            return
        # 平移优先，不能把右键运动当成 ROI/标定草图运动。
        if self._panning:
            self.offset += event.position() - self._last_pos
            self._last_pos = event.position()
            self.update()
            return
        self._mouse_img = self._clamped(self.widget_to_img(event.position()))
        if self._drag_start is not None and not self._drag_interrupted:
            if self.mode == 'calibrate':
                self._drag_end, self._drag_constraint = snap_endpoint(
                    self._drag_start, self._mouse_img)
            else:
                self._drag_end = self._mouse_img
        if self.mode == 'delete':
            p = self.widget_to_img(event.position())
            self.hovered_index = hit_index(
                self.objects, p.x(), p.y(), self.selected_roi_id)
        elif self.mode == 'distance_delete':
            p = self.widget_to_img(event.position())
            self.hovered_distance_index = distance_hit_index(
                self.distance_entries, p.x(), p.y(), tolerance=2 / self.scale)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._panning = False
            self.unsetCursor()
            return
        if event.button() != Qt.MouseButton.LeftButton or self._drag_start is None:
            return
        if self._panning or self._drag_interrupted:
            # 平移打断左键拖拽：无论左右键释放顺序，都不提交意外区域。
            self.cancel_draft()
            return
        start = self._drag_start
        end = self._clamped(self.widget_to_img(event.position()))
        self._drag_start = self._drag_end = None
        if self.mode == 'rect':
            rect = (min(start.x(), end.x()), min(start.y(), end.y()),
                    abs(end.x() - start.x()), abs(end.y() - start.y()))
            if rect[2] > 5 and rect[3] > 5:
                self.roi_rect.emit(rect)
        elif self.mode == 'calibrate':
            end, _ = snap_endpoint(start, end)
            self.calib_drawn.emit((start.x(), start.y()), (end.x(), end.y()))
        self.update()

    def mouseDoubleClickEvent(self, event):
        if (self.img_qt is None or self._panning
                or event.button() != Qt.MouseButton.LeftButton):
            return
        if self.mode == 'add':
            # 首击负责提取；双击只确认，不能重新提取或重复增加。
            self.add_confirm.emit()
        elif self.mode == 'poly':
            p = self._clamped(self.widget_to_img(event.position()))
            point = (p.x(), p.y())
            points = list(self.poly_drawing)
            if not points or point != points[-1]:
                points.append(point)
            if len(points) >= 3:
                self.roi_poly.emit(points)
            self.poly_drawing = []
            self.update()

    def wheelEvent(self, event):
        if self.img_qt is None or event.angleDelta().y() == 0:
            return
        anchor = self.widget_to_img(event.position())
        factor = 1.1 if event.angleDelta().y() > 0 else .9
        self.scale = min(50., max(.01, self.scale * factor))
        # 使用限幅后的实际倍率，两轴以相同方式保持锚点。
        self.offset = event.position() - anchor * self.scale
        self.update()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_draft()
            self.add_cancel.emit()
            self.mode_cancel.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def leaveEvent(self, event):
        self.hovered_index = -1
        self.hovered_distance_index = -1
        self.update()
        super().leaveEvent(event)

    @staticmethod
    def _outline(painter, points):
        polygon = QPolygonF([QPointF(float(x), float(y)) for x, y in points])
        if len(polygon) == 1:
            painter.drawPoint(polygon[0])
        elif len(polygon) == 2:
            painter.drawPolyline(polygon)
        elif polygon:
            painter.drawPolygon(polygon)

    def _draw_object(self, painter, obj, overlay, hovered=False, preview=False, selected=False):
        x, y, _, _ = obj['rect']
        painter.drawImage(QPointF(x, y), overlay)
        color = QColor('#ff6b6b') if hovered else QColor('#ffd166') if selected else QColor(0, 220, 130)
        painter.setPen(QPen(color, (2.5 if selected else 1.5) / self.scale,
                            Qt.PenStyle.DashLine if preview else Qt.PenStyle.SolidLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        self._outline(painter, obj['points'])

    def _draw_roi(self, painter, roi):
        kind, data = roi
        if kind == 'rect':
            painter.drawRect(QRectF(*data))
        else:
            self._outline(painter, data)

    @staticmethod
    def _draw_constraint_badge(painter, p1, p2, constraint, scale):
        cx, cy = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        offset, radius = 12 / scale, 6 / scale
        painter.setPen(QPen(QColor('#ef4444'), 3 / scale))
        if constraint == 'h':
            painter.drawLine(QPointF(cx - radius, cy + offset),
                             QPointF(cx + radius, cy + offset))
        elif constraint == 'v':
            painter.drawLine(QPointF(cx + offset, cy - radius),
                             QPointF(cx + offset, cy + radius))

    def _draw_distance(self, painter, p1, p2, constraint='', preview=False, hovered=False):
        start, end = QPointF(*p1), QPointF(*p2)
        color = QColor('#ff6b6b') if hovered else QColor('#f59e0b')
        painter.setPen(QPen(color, 2.5 / self.scale,
                            Qt.PenStyle.DashLine if preview else Qt.PenStyle.SolidLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(start, end)
        painter.setBrush(color)
        painter.setPen(QPen(QColor('white'), 1.5 / self.scale))
        for point in (start, end):
            painter.drawEllipse(point, 4 / self.scale, 4 / self.scale)
        if constraint:
            self._draw_constraint_badge(painter, p1, p2, constraint, self.scale)

    def _text(self, painter, pos, text):
        path = QPainterPath()
        path.addText(pos, self.label_font, text)
        painter.setPen(QPen(QColor('black'), 3))
        painter.setBrush(QColor('white'))
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#f0f4f8'))
        if self.img_qt is None:
            paint_empty_state(painter, self)
            return
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        # 默认 nearest-neighbour：掩膜不插值、不填外轮廓孔洞。
        painter.drawImage(QPointF(), self.img_qt)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, obj in enumerate(self.objects):
            self._draw_object(painter, obj, self._mask_images[index],
                              self.mode == 'delete' and index == self.hovered_index,
                              selected=index == self.selected_index)
        if self.preview is not None:
            self._draw_object(painter, self.preview, self._preview_image, preview=True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for entry in self.roi_entries:
            selected = entry['id'] == self.selected_roi_id
            painter.setPen(QPen(QColor('#ffd166') if selected else QColor('#3b82f6'),
                                (2.5 if selected else 2) / self.scale,
                                Qt.PenStyle.SolidLine if selected else Qt.PenStyle.DashLine))
            self._draw_roi(painter, entry['roi'])
        for index, entry in enumerate(self.distance_entries):
            self._draw_distance(painter, entry['p1'], entry['p2'], entry['constraint'],
                                hovered=self.mode == 'distance_delete'
                                and index == self.hovered_distance_index)
        if self.mode == 'measure' and self.pending_distance is not None:
            snapped, constraint = snap_endpoint(self.pending_distance, self._mouse_img)
            self._draw_distance(painter, (self.pending_distance.x(), self.pending_distance.y()),
                                (snapped.x(), snapped.y()), constraint, preview=True)
        painter.setPen(QPen(QColor('#3b82f6'), 2 / self.scale, Qt.PenStyle.DashLine))
        if self._drag_start is not None:
            if self.mode == 'rect':
                painter.drawRect(QRectF(self._drag_start, self._drag_end).normalized())
            else:
                painter.drawLine(self._drag_start, self._drag_end)
                if self.mode == 'calibrate' and self._drag_constraint:
                    self._draw_constraint_badge(
                        painter, (self._drag_start.x(), self._drag_start.y()),
                        (self._drag_end.x(), self._drag_end.y()),
                        self._drag_constraint, self.scale)
        if self.poly_drawing:
            points = QPolygonF([QPointF(*p) for p in self.poly_drawing] + [self._mouse_img])
            painter.drawPolyline(points)
        if self.calib_line:
            start, end = [QPointF(*p) for p in self.calib_line]
            painter.setPen(QPen(QColor('#3b82f6'), 2 / self.scale))
            painter.setBrush(QColor('#3b82f6'))
            painter.drawLine(start, end)
            for point in (start, end):
                painter.drawEllipse(point, 3 / self.scale, 3 / self.scale)
        painter.restore()
        painter.setFont(self.label_font)
        for entry in self.roi_entries:
            kind, data = entry['roi']
            anchor = QPointF(data[0], data[1]) if kind == 'rect' else QPointF(*data[0])
            self._text(painter, self.img_to_widget(anchor) + QPointF(4, -4),
                       entry['label'])
        for entry in self.distance_entries:
            p1, p2 = entry['p1'], entry['p2']
            midpoint = QPointF((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            self._text(painter, self.img_to_widget(midpoint) + QPointF(6, -10),
                       entry['label'])
        if self.calib_line:
            start, end = [QPointF(*p) for p in self.calib_line]
            self._text(painter, self.img_to_widget((start + end) / 2) + QPointF(6, -10),
                       self.calib_label)
        if self.summary:
            bounds = painter.fontMetrics().boundingRect(self.summary).adjusted(-8, -5, 8, 5)
            bounds.moveTopRight(self.rect().topRight() + QPointF(-12, 12).toPoint())
            painter.fillRect(bounds, QColor(0, 0, 0, 190))
            painter.setPen(QColor('white'))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, self.summary)
