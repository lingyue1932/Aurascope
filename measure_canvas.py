"""距离测量画布 — 支持标定、测距、缩放平移、标注显示"""

import cv2
import numpy as np
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QImage, QPainter, QPen, QColor, QBrush, QFont

from ui_components import paint_empty_state


class MeasureCanvas(QWidget):
    calib_drawn = pyqtSignal(QPointF, QPointF)
    measurement_added = pyqtSignal(float, float, float, float, float)

    SNAP_DEG = 7

    MODE_COLORS = {
        'calibrate': '#4299e1',
        'measure': '#f59e0b',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.img_cv = None
        self.img_qt = None
        self.scale = 1.0
        self.offset = QPointF(0, 0)

        self.mode = 'none'
        self._dragging = False
        self._panning = False
        self._last_pos = QPointF()

        # 标定
        self.calib_start = None
        self.calib_drag = None
        self.calib_line = None
        self.pixel_scale = 0.0
        self.calibrated = False

        # 测量
        self.pending_point = None
        self.completed = []
        self._mouse_img = None

    # ---- 图片操作 ----

    def set_image(self, img_cv):
        self.img_cv = img_cv
        h, w = img_cv.shape[:2]
        rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB) if len(img_cv.shape) == 3 else cv2.cvtColor(img_cv, cv2.COLOR_GRAY2RGB)
        self.img_qt = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.fit_in_view()
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

    def img_to_widget(self, pos):
        return QPointF(pos.x() * self.scale + self.offset.x(),
                       pos.y() * self.scale + self.offset.y())

    # ---- 状态操作 ----

    def clear_calibration(self):
        self.calib_line = None
        self.pixel_scale = 0.0
        self.calibrated = False
        self.update()

    def clear_measurements(self):
        self.pending_point = None
        self.completed = []
        self.update()

    def remove_last_measurement(self):
        if self.completed:
            self.completed.pop()
            self.update()
            return True
        return False

    def reset_all(self):
        self.clear_calibration()
        self.clear_measurements()
        self.calib_start = None
        self.calib_drag = None

    # ---- 水平/竖直吸附 ----

    def _snap_endpoint(self, p1, p2):
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        if abs(dx) < 2 and abs(dy) < 2:
            return p2, None
        angle = abs(np.degrees(np.arctan2(abs(dy), abs(dx))))
        if angle < self.SNAP_DEG:
            return QPointF(p2.x(), p1.y()), 'h'
        if angle > 90 - self.SNAP_DEG:
            return QPointF(p1.x(), p2.y()), 'v'
        return p2, None

    # ---- 鼠标事件 ----

    def mousePressEvent(self, event):
        if self.img_qt is None:
            return
        self.setFocus()
        p = self.widget_to_img(event.position())

        if event.button() == Qt.MouseButton.LeftButton:
            if self.mode == 'calibrate':
                self.calib_start = p
                self.calib_drag = p
                self._dragging = True
            elif self.mode == 'measure' and self.calibrated:
                if self.pending_point is None:
                    self.pending_point = p
                else:
                    snapped, constraint = self._snap_endpoint(self.pending_point, p)
                    dx = snapped.x() - self.pending_point.x()
                    dy = snapped.y() - self.pending_point.y()
                    dist_px = np.hypot(dx, dy)
                    dist_real = dist_px / self.pixel_scale
                    self.completed.append((self.pending_point.x(), self.pending_point.y(), snapped.x(), snapped.y(), dist_real, constraint))
                    self.measurement_added.emit(self.pending_point.x(), self.pending_point.y(), snapped.x(), snapped.y(), dist_real)
                    self.pending_point = None
                self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._last_pos = event.position()
            self._panning = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.img_qt is None:
            return
        self._mouse_img = self.widget_to_img(event.position())

        if self._dragging and self.mode == 'calibrate':
            self.calib_drag = self._mouse_img
            self.update()
        elif self._panning:
            delta = event.position() - self._last_pos
            self.offset += delta
            self._last_pos = event.position()
            self.update()
        elif self.mode == 'measure':
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            if self.mode == 'calibrate' and self.calib_start and self.calib_drag:
                d = np.hypot(self.calib_drag.x() - self.calib_start.x(), self.calib_drag.y() - self.calib_start.y())
                if d >= 5:
                    self.calib_drawn.emit(self.calib_start, self.calib_drag)
                else:
                    self.calib_start = self.calib_drag = None
                    self.update()
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

    # ---- 约束徽标 ----

    @staticmethod
    def _draw_constraint_badge(painter, x1, y1, x2, y2, constraint, s):
        offset = 12 / s
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        r = 6 / s
        painter.setPen(QPen(QColor('#ef4444'), 3 / s))
        if constraint == 'h':
            painter.drawLine(int(cx - r), int(cy + offset), int(cx + r), int(cy + offset))
        else:
            painter.drawLine(int(cx + offset), int(cy - r), int(cx + offset), int(cy + r))

    # ---- 绘制 ----

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#f0f4f8'))

        if self.img_qt is None:
            paint_empty_state(painter, self)
            return

        # ===== 图像坐标绘制 =====
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        s = self.scale

        # 阴影 + 图片
        painter.fillRect(-2, -2, self.img_qt.width() + 4, self.img_qt.height() + 4, QColor(0, 0, 0, 20))
        painter.drawImage(0, 0, self.img_qt)

        # --- 标定线 ---
        if self.calib_line:
            p1, p2, _ = self.calib_line
            pen = QPen(QColor('#3b82f6'), 3 / s)
            painter.setPen(pen)
            painter.drawLine(p1, p2)
            painter.setBrush(QColor('#3b82f6'))
            r = 5 / s
            painter.drawEllipse(p1, r, r)
            painter.drawEllipse(p2, r, r)

        if self.mode == 'calibrate' and self._dragging and self.calib_start and self.calib_drag:
            painter.setPen(QPen(QColor('#3b82f6'), 2 / s, Qt.PenStyle.DashLine))
            painter.drawLine(self.calib_start, self.calib_drag)

        # --- 已完成的测量 ---
        for idx, (x1, y1, x2, y2, dist, constraint) in enumerate(self.completed):
            painter.setPen(QPen(QColor('#10b981'), 2.5 / s))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            for (px, py) in [(x1, y1), (x2, y2)]:
                painter.setBrush(QColor('#10b981'))
                painter.setPen(QPen(QColor('white'), 1.5 / s))
                painter.drawEllipse(QPointF(px, py), 4 / s, 4 / s)
            if constraint:
                self._draw_constraint_badge(painter, x1, y1, x2, y2, constraint, s)

        # --- 待确认第一点 + 预览线 ---
        if self.pending_point and self._mouse_img and self.mode == 'measure':
            pp = self.pending_point
            snapped, constraint = self._snap_endpoint(pp, self._mouse_img)
            painter.setPen(QPen(QColor('#f59e0b'), 2.5 / s))
            painter.drawLine(pp, snapped)
            painter.setBrush(QColor('#f59e0b'))
            painter.setPen(QPen(QColor('white'), 1.5 / s))
            painter.drawEllipse(pp, 5 / s, 5 / s)
            if constraint:
                self._draw_constraint_badge(painter, pp.x(), pp.y(), snapped.x(), snapped.y(), constraint, s)

        painter.restore()

        # ===== 控件坐标文字 =====
        font = QFont('Segoe UI', 11, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()

        def draw_label(text, img_pt, offset_x=0, offset_y=0):
            wpt = self.img_to_widget(img_pt) + QPointF(offset_x, offset_y)
            tr = fm.boundingRect(text)
            tr.moveCenter(wpt.toPoint())
            tr.adjust(-5, -3, 5, 3)
            painter.fillRect(tr, QColor(0, 0, 0, 150))
            painter.setPen(QColor('white'))
            painter.drawText(tr, Qt.AlignmentFlag.AlignCenter, text)

        # 标定线标签
        if self.calib_line:
            p1, p2, txt = self.calib_line
            draw_label(txt, (p1 + p2) / 2, offset_y=-25)

        # 测量结果标签（序号+距离）
        for idx, (x1, y1, x2, y2, dist, _) in enumerate(self.completed):
            label = f"#{idx+1}  {dist:.2f} μm"
            draw_label(label, QPointF((x1 + x2) / 2, (y1 + y2) / 2), offset_y=-20)

        # 预览标签
        if self.pending_point and self._mouse_img and self.mode == 'measure':
            snapped, _ = self._snap_endpoint(self.pending_point, self._mouse_img)
            dx = snapped.x() - self.pending_point.x()
            dy = snapped.y() - self.pending_point.y()
            dp = np.hypot(dx, dy)
            if self.pixel_scale > 0:
                preview = f"{dp / self.pixel_scale:.2f} μm"
            else:
                preview = f"{dp:.1f} px"
            draw_label(preview, (self.pending_point + snapped) / 2, offset_y=-20)

        # 模式提示（左下角）
        if self.mode != 'none':
            hints = {
                'calibrate': '标定模式：拖拽画一条已知长度的参考线',
                'measure': '测量模式：点击两点测量距离',
            }
            hint = hints.get(self.mode, '')
            painter.setFont(QFont('Segoe UI', 12))
            fm2 = painter.fontMetrics()
            tr = fm2.boundingRect(hint)
            tr.moveTo(12, self.height() - tr.height() - 12)
            tr.adjust(-8, -4, 8, 4)
            c = self.MODE_COLORS.get(self.mode, '#4299e1')
            bg = QColor(c)
            bg.setAlpha(200)
            painter.fillRect(tr, bg)
            painter.setPen(QColor('white'))
            painter.drawText(tr, Qt.AlignmentFlag.AlignCenter, hint)
