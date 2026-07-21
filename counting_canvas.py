import cv2
import numpy as np
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPen, QColor, QBrush, QFont


class CountingCanvas(QWidget):
    roi_rect_finished = pyqtSignal(tuple)
    roi_polygon_finished = pyqtSignal(list)
    object_delete_at = pyqtSignal(float, float)
    object_add_at = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.img_cv = None
        self.img_qt = None
        self.scale = 1.0
        self.offset = QPointF(0, 0)

        self.roi_mode = 'none'
        self.roi_rect = None
        self.roi_polygon = None
        self.poly_drawing = []
        self.objects = []
        self.count = 0
        self.edit_mode = 'none'
        self._hovered_idx = -1
        self._mouse_pos = QPointF()

        self._drag_roi = False
        self._drag_start = QPointF()
        self._panning = False
        self._last_pos = QPointF()

    def set_image(self, img_cv):
        self.img_cv = img_cv
        h, w = img_cv.shape[:2]
        if len(img_cv.shape) == 3:
            rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
        else:
            rgb = cv2.cvtColor(img_cv, cv2.COLOR_GRAY2RGB)
        self.img_qt = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.fit_in_view()
        self.objects = []
        self.roi_rect = None
        self.roi_polygon = None
        self.poly_drawing = []
        self.count = 0
        self.update()

    def fit_in_view(self):
        if self.img_qt is None:
            return
        wr = self.width() / self.img_qt.width()
        hr = self.height() / self.img_qt.height()
        self.scale = min(wr, hr) * 0.9
        self.offset = QPointF(
            (self.width() - self.img_qt.width() * self.scale) / 2,
            (self.height() - self.img_qt.height() * self.scale) / 2)

    def widget_to_img(self, pos):
        if self.img_qt is None:
            return QPointF(0, 0)
        return QPointF((pos.x() - self.offset.x()) / self.scale,
                       (pos.y() - self.offset.y()) / self.scale)

    def mousePressEvent(self, event):
        if self.img_qt is None:
            return
        self.setFocus()
        p = self.widget_to_img(event.position())

        if event.button() == Qt.MouseButton.LeftButton:
            if self.edit_mode == 'delete':
                self.object_delete_at.emit(float(p.x()), float(p.y()))
                return
            if self.edit_mode == 'add':
                self.object_add_at.emit(float(p.x()), float(p.y()))
                return
            if self.roi_mode == 'rect':
                self._drag_start = p
                self.roi_rect = (p.x(), p.y(), 0, 0)
                self._drag_roi = True
                return
            if self.roi_mode == 'poly':
                if len(self.poly_drawing) >= 3:
                    first = self.poly_drawing[0]
                    hit = 10.0 / max(self.scale, 1e-6)
                    if abs(p.x() - first.x()) < hit and abs(p.y() - first.y()) < hit:
                        pts = [(pt.x(), pt.y()) for pt in self.poly_drawing]
                        self.roi_polygon = pts
                        self.poly_drawing = []
                        self.roi_polygon_finished.emit(pts)
                        self.roi_mode = 'none'
                        self.update()
                        return
                self.poly_drawing.append(p)
                self.update()
                return

        if event.button() == Qt.MouseButton.RightButton:
            self._last_pos = event.position()
            self._panning = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.roi_mode == 'poly':
            if len(self.poly_drawing) >= 3:
                pts = [(pt.x(), pt.y()) for pt in self.poly_drawing]
                self.roi_polygon = pts
                self.poly_drawing = []
                self.roi_polygon_finished.emit(pts)
                self.roi_mode = 'none'
                self.update()

    def mouseMoveEvent(self, event):
        if self.img_qt is None:
            return

        self._mouse_pos = self.widget_to_img(event.position())

        if self._drag_roi:
            p = self._mouse_pos
            x = min(self._drag_start.x(), p.x())
            y = min(self._drag_start.y(), p.y())
            w = abs(self._drag_start.x() - p.x())
            h = abs(self._drag_start.y() - p.y())
            self.roi_rect = (x, y, w, h)
            self.update()
            return

        if self._panning:
            delta = event.position() - self._last_pos
            self.offset += delta
            self._last_pos = event.position()
            self.update()
            return

        if self.edit_mode == 'delete':
            p = self._mouse_pos
            self._hovered_idx = -1
            for i, obj in enumerate(self.objects):
                pts = np.array(obj['points'], dtype=np.int32)
                if cv2.pointPolygonTest(pts, (p.x(), p.y()), False) >= 0:
                    self._hovered_idx = i
                    break
            self.update()

        if self.roi_mode == 'poly':
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_roi and event.button() == Qt.MouseButton.LeftButton:
            self._drag_roi = False
            if self.roi_rect and self.roi_rect[2] > 5 and self.roi_rect[3] > 5:
                self.roi_rect_finished.emit(self.roi_rect)
            else:
                self.roi_rect = None
            self.update()
            return

        if event.button() == Qt.MouseButton.RightButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event):
        if self.img_qt is None:
            return
        factor = 1.1 if event.angleDelta().y() > 0 else 0.9
        mp = event.position()
        ibx = (mp.x() - self.offset.x()) / self.scale
        self.scale = max(0.01, min(self.scale * factor, 50.0))
        self.offset = QPointF(mp.x() - ibx * self.scale,
                              mp.y() - ((mp.y() - self.offset.y()) / (self.scale / factor)) * self.scale)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#f0f4f8'))

        if self.img_qt is None:
            painter.setPen(QColor('#94a3b8'))
            painter.setFont(QFont('Segoe UI', 14))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '请先上传图片')
            return

        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        s = self.scale

        painter.fillRect(-2, -2, self.img_qt.width() + 4, self.img_qt.height() + 4, QColor(0, 0, 0, 20))
        painter.drawImage(0, 0, self.img_qt)

        for i, obj in enumerate(self.objects):
            pts = [QPointF(x, y) for x, y in obj['points']]
            polygon = [p.toPoint() for p in pts]
            is_hovered = (self.edit_mode == 'delete' and i == self._hovered_idx)

            painter.setBrush(QBrush(QColor(220, 20, 60, 120)))
            painter.setPen(QPen(QColor('#ff6b6b' if is_hovered else '#dc143c'), 2.0 / s))
            painter.drawPolygon(*polygon)

            cx, cy = obj.get('cx', 0), obj.get('cy', 0)
            label = str(obj.get('id', 0))
            painter.setPen(QPen(QColor('white'), 1.5 / s))
            painter.setFont(QFont('Segoe UI', int(11 / s), QFont.Weight.Bold))
            painter.drawText(QPointF(cx, cy).toPoint(), label)

        if self.roi_rect and self.roi_rect[2] > 0 and self.roi_rect[3] > 0:
            x, y, w, h = [int(v) for v in self.roi_rect]
            painter.setPen(QPen(QColor('#3b82f6'), 3.0 / s))
            painter.setBrush(QBrush(QColor(0, 0, 0, 0)))
            painter.drawRect(x, y, w, h)

        if self.roi_polygon:
            pts = [QPointF(x, y) for x, y in self.roi_polygon]
            painter.setPen(QPen(QColor('#3b82f6'), 3.0 / s))
            painter.setBrush(QBrush(QColor(0, 0, 0, 0)))
            painter.drawPolygon(*[p.toPoint() for p in pts])

        if self.roi_mode == 'poly' and self.poly_drawing:
            for pt in self.poly_drawing:
                painter.setBrush(QBrush(QColor('#3b82f6')))
                painter.setPen(QPen(QColor('white'), 1.5 / s))
                painter.drawEllipse(int(pt.x()) - 4, int(pt.y()) - 4, 8, 8)
            for i in range(len(self.poly_drawing) - 1):
                a = self.poly_drawing[i].toPoint()
                b = self.poly_drawing[i + 1].toPoint()
                painter.setPen(QPen(QColor('#3b82f6'), 2.5 / s))
                painter.drawLine(a, b)
            if len(self.poly_drawing) >= 1:
                last = self.poly_drawing[-1].toPoint()
                mouse = self._mouse_pos.toPoint()
                painter.setPen(QPen(QColor('#3b82f6'), 2.0 / s, Qt.PenStyle.DashLine))
                painter.drawLine(last, mouse)

        if self.edit_mode == 'delete' and self._hovered_idx >= 0:
            painter.setPen(QColor('#ff6b6b'))
            painter.setFont(QFont('Segoe UI', 10))
            painter.drawText(10, self.height() - 10, '点击删除高亮对象')

        painter.restore()

        if self.objects:
            text = f"总数: {self.count}"
            font = QFont('Segoe UI', 18, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            tr = fm.boundingRect(text)
            rx = self.width() - tr.width() - 24
            ry = 12
            tr.moveTo(rx, ry)
            tr.adjust(-14, -8, 14, 10)
            painter.fillRect(tr, QColor(0, 0, 0, 180))
            painter.setPen(QColor('#ffffff'))
            painter.drawText(tr, Qt.AlignmentFlag.AlignCenter, text)