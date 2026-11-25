"""图像画布组件"""

import cv2
import numpy as np
from PyQt6.QtWidgets import QWidget, QMessageBox
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QRect, QTimer
from PyQt6.QtGui import QImage, QPainter, QPen, QColor, QBrush, QFont, QCursor, QPixmap

from app_paths import resource_path
from ui_components import paint_empty_state


class ImageCanvas(QWidget):
    """图像显示和交互画布"""
    
    calib_drawn = pyqtSignal(QPointF, QPointF)
    roi_poly_finished = pyqtSignal(list)
    roi_rect_changed = pyqtSignal(tuple)
    roi_rect_finished = pyqtSignal(tuple)
    roi_polygon_edited = pyqtSignal(list)
    void_delete_at = pyqtSignal(float, float)
    void_add_polygon = pyqtSignal(list)
    void_selected_for_local = pyqtSignal(int)
    void_local_region_confirmed = pyqtSignal(float, float, float)  # cx, cy, radius
    void_local_threshold_changed = pyqtSignal(int, int)  # region_index, new_thresh
    void_local_region_removed = pyqtSignal(int)  # region_index
    teach_void_at = pyqtSignal(float, float)     # 示教点选空洞（图像坐标）
    empty_import = pyqtSignal()                  # 空状态「导入图片」

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.img_cv = None
        self.img_qt = None

        self.scale = 1.0
        self.offset = QPointF(0, 0)
        self.last_mouse_pos = QPointF()

        self.mode = 'none'  # calibration / poly / rect / none
        self.is_dragging = False
        self.drag_start_img = QPointF()
        self.current_points = []
        self.current_rect = None

        self.overlay_mask = None
        self.overlay_preview = None
        self.draw_voids = []
        self.show_labels = False
        self.fill_voids = True
        self.show_roi_overlay = True
        self.calib_line = None

        # editable ROI polygon
        self.roi_polygon_points = []
        self.roi_edit_enabled = False
        self.snap_enabled = True
        self.edge_snap_mask = None
        self.selected_vertex_idx = -1
        self.active_edge_idx = -1
        self.drag_kind = None
        self.drag_last_img = QPointF()
        self.hit_radius_px = 10.0
        self.snap_radius_px = 8
        self.void_edit_mode = 'none'
        self.void_add_preview = None       # {'points': [...], 'seed': (x,y), 'sensitivity': int}
        self.void_add_offset = 0          # 局部 Otsu 阈值偏移量
        self.void_add_status = ""          # 临时状态文字
        self._add_click_pos = None         # 保存上次点击位置，供 Ctrl+滚轮重算
        self.local_brush_mode = False
        self.brush_radius = 60
        # 局部笔刷交互状态
        self.lb_state = 'none'          # 'preview' | 'placed' | 'none'
        self.lb_radius = 60.0
        self.lb_preview_pos = None      # QPointF 鼠标位置（预显）
        self.lb_placed_pos = None       # QPointF 点击放置但未确认
        self.lb_confirmed = []          # [{'cx','cy','radius','thresh'}, ...]
        self.void_rate_text = ""        # 空洞率文字，显示在图像右上角
        self.hovered_void_id = -1       # 删除模式下悬停的空洞ID，用于高亮预览
        self.hovered_vertex_idx = -1    # 编辑态下光标最近的顶点（按需显示手柄）
        self.teach_void_mode = False    # 示教模式：左键点选空洞

    def set_void_edit_mode(self, mode):
        self.void_edit_mode = mode
        if mode != 'add':
            self.void_add_preview = None
            self._add_click_pos = None
        if mode != 'delete':
            self.hovered_void_id = -1
        if mode == 'local_brush':
            self.lb_state = 'preview'
            self.lb_placed_pos = None
        else:
            self.lb_state = 'none'
            self.lb_preview_pos = None
            self.lb_placed_pos = None
        self.update()

    def set_local_brush_regions(self, regions):
        """从主窗口同步已确认区域列表（含阈值）用于渲染"""
        self.lb_confirmed = list(regions)
        self.update()

    def set_teach_void_mode(self, enabled):
        """示教点选模式：左键点击直接发射信号，不进其他交互分支"""
        self.teach_void_mode = bool(enabled)
        if self.teach_void_mode:
            self.void_edit_mode = 'none'
        self.update()

    def set_image(self, img_cv):
        self.img_cv = img_cv
        if len(img_cv.shape) == 2:
            h, w = img_cv.shape
            rgb = cv2.cvtColor(img_cv, cv2.COLOR_GRAY2RGB)
        else:
            h, w, _ = img_cv.shape
            rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)

        bytes_per_line = 3 * w
        self.img_qt = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

        self.clear_roi_polygon()
        self.set_edge_snap_mask(None)
        self.set_roi_edit_enabled(False)
        self.fit_in_view()
        self.update()

    def fit_in_view(self):
        if self.img_qt is None:
            return
        w_ratio = self.width() / self.img_qt.width()
        h_ratio = self.height() / self.img_qt.height()
        self.scale = min(w_ratio, h_ratio) * 0.9
        cx = (self.width() - self.img_qt.width() * self.scale) / 2
        cy = (self.height() - self.img_qt.height() * self.scale) / 2
        self.offset = QPointF(cx, cy)

    def widget_to_img(self, pos):
        if self.img_qt is None:
            return QPointF(0, 0)
        x = (pos.x() - self.offset.x()) / self.scale
        y = (pos.y() - self.offset.y()) / self.scale
        x = max(0, min(x, self.img_qt.width() - 1))
        y = max(0, min(y, self.img_qt.height() - 1))
        return QPointF(x, y)

    def img_to_widget(self, pos_img):
        x = pos_img.x() * self.scale + self.offset.x()
        y = pos_img.y() * self.scale + self.offset.y()
        return QPointF(x, y)

    def set_roi_polygon(self, points):
        self.roi_polygon_points = [QPointF(float(x), float(y)) for x, y in points]
        self.selected_vertex_idx = -1
        self.active_edge_idx = -1
        self.update()

    def clear_roi_polygon(self):
        self.roi_polygon_points = []
        self.selected_vertex_idx = -1
        self.active_edge_idx = -1
        self.drag_kind = None
        self.update()

    def set_roi_edit_enabled(self, enabled):
        self.roi_edit_enabled = bool(enabled)
        if not self.roi_edit_enabled:
            self.selected_vertex_idx = -1
            self.active_edge_idx = -1
            self.hovered_vertex_idx = -1
            self.drag_kind = None
        self.update()

    def set_edge_snap_mask(self, edge_mask):
        self.edge_snap_mask = edge_mask

    def set_snap_enabled(self, enabled):
        self.snap_enabled = bool(enabled)

    def set_polygon_vertex_count(self, target_count):
        if len(self.roi_polygon_points) < 3:
            return
        pts = np.array([[p.x(), p.y()] for p in self.roi_polygon_points], dtype=np.float32)
        target_count = max(3, int(target_count))
        if target_count == len(pts):
            return
        pts = self._resample_polygon(pts, target_count)
        self.set_roi_polygon(pts.tolist())
        self._emit_roi_polygon_edited()

    def _emit_roi_polygon_edited(self):
        if len(self.roi_polygon_points) < 3:
            return
        self.roi_polygon_edited.emit([(p.x(), p.y()) for p in self.roi_polygon_points])

    @staticmethod
    def _distance(p1, p2):
        return float(np.hypot(p1.x() - p2.x(), p1.y() - p2.y()))

    @staticmethod
    def _point_segment_distance(p, a, b):
        ax, ay = a.x(), a.y()
        bx, by = b.x(), b.y()
        px, py = p.x(), p.y()
        abx = bx - ax
        aby = by - ay
        ab2 = abx * abx + aby * aby
        if ab2 <= 1e-6:
            return float(np.hypot(px - ax, py - ay))
        t = ((px - ax) * abx + (py - ay) * aby) / ab2
        t = max(0.0, min(1.0, t))
        proj_x = ax + t * abx
        proj_y = ay + t * aby
        return float(np.hypot(px - proj_x, py - proj_y))

    def _closest_vertex_index(self, pos_img):
        if not self.roi_polygon_points:
            return -1
        threshold = self.hit_radius_px / max(self.scale, 1e-6)
        dists = [self._distance(pos_img, p) for p in self.roi_polygon_points]
        idx = int(np.argmin(dists))
        return idx if dists[idx] <= threshold else -1

    def _closest_edge_index(self, pos_img):
        n = len(self.roi_polygon_points)
        if n < 2:
            return -1
        threshold = self.hit_radius_px / max(self.scale, 1e-6)
        best_idx = -1
        best_dist = 1e9
        for i in range(n):
            a = self.roi_polygon_points[i]
            b = self.roi_polygon_points[(i + 1) % n]
            d = self._point_segment_distance(pos_img, a, b)
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx if best_dist <= threshold else -1

    def _clear_status(self):
        self.void_add_status = ""
        self.update()

    def _local_detect_at(self, pos_img, offset):
        """基于局部 Otsu 自适应阈值检测点击位置的空洞"""
        try:
            if self.img_cv is None:
                return None
            img = self.img_cv
            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img
            h, w = gray.shape
            cx, cy = int(round(pos_img.x())), int(round(pos_img.y()))
            if not (0 <= cx < w and 0 <= cy < h):
                return None
            half = 80
            x0 = max(0, cx - half)
            y0 = max(0, cy - half)
            x1 = min(w, cx + half)
            y1 = min(h, cy + half)
            local = gray[y0:y1, x0:x1].copy()
            if local.size < 100:
                return None
            otsu_val, _ = cv2.threshold(local, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            thresh = max(0, min(255, otsu_val + offset))
            _, local_bin = cv2.threshold(local, thresh, 255, cv2.THRESH_BINARY_INV)
            full_bin = np.zeros((h, w), dtype=np.uint8)
            full_bin[y0:y1, x0:x1] = local_bin
            cnts, _ = cv2.findContours(full_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                if cv2.pointPolygonTest(c, (float(cx), float(cy)), False) >= 0:
                    area = cv2.contourArea(c)
                    if area > 3:
                        return c
            return None
        except Exception:
            return None

    def _clamp_to_image(self, p):
        if self.img_qt is None:
            return QPointF(p)
        x = max(0.0, min(float(p.x()), float(self.img_qt.width() - 1)))
        y = max(0.0, min(float(p.y()), float(self.img_qt.height() - 1)))
        return QPointF(x, y)

    def _snap_point(self, p):
        p = self._clamp_to_image(p)
        if (not self.snap_enabled) or self.edge_snap_mask is None:
            return p
        x = int(round(p.x()))
        y = int(round(p.y()))
        h, w = self.edge_snap_mask.shape[:2]
        if x < 0 or y < 0 or x >= w or y >= h:
            return p
        r = int(self.snap_radius_px)
        x0 = max(0, x - r)
        y0 = max(0, y - r)
        x1 = min(w - 1, x + r)
        y1 = min(h - 1, y + r)
        patch = self.edge_snap_mask[y0:y1 + 1, x0:x1 + 1]
        ys, xs = np.where(patch > 0)
        if len(xs) == 0:
            return p
        xs = xs + x0
        ys = ys + y0
        dist2 = (xs - p.x()) ** 2 + (ys - p.y()) ** 2
        idx = int(np.argmin(dist2))
        return QPointF(float(xs[idx]), float(ys[idx]))

    @staticmethod
    def _resample_polygon(pts, target_count):
        n = len(pts)
        if n < 3 or target_count < 3:
            return pts
        segs = np.roll(pts, -1, axis=0) - pts
        seg_len = np.linalg.norm(segs, axis=1)
        total_len = float(np.sum(seg_len))
        if total_len <= 1e-6:
            return pts
        cumsum = np.cumsum(seg_len)
        step = total_len / target_count
        out = []
        for i in range(target_count):
            d = i * step
            seg_idx = int(np.searchsorted(cumsum, d, side='right'))
            seg_idx = min(seg_idx, n - 1)
            prev_sum = 0.0 if seg_idx == 0 else float(cumsum[seg_idx - 1])
            local = (d - prev_sum) / max(float(seg_len[seg_idx]), 1e-6)
            p0 = pts[seg_idx]
            p1 = pts[(seg_idx + 1) % n]
            out.append((1 - local) * p0 + local * p1)
        return np.array(out, dtype=np.float32)

    def mousePressEvent(self, event):
        if self.img_qt is None:
            return
        self.setFocus()

        pos_widget = event.position()
        pos_img = self.widget_to_img(pos_widget)

        if event.button() == Qt.MouseButton.LeftButton:

            # 示教点选模式优先级最高：点击即发射，不进任何其他交互分支
            if self.teach_void_mode:
                self.teach_void_at.emit(float(pos_img.x()), float(pos_img.y()))
                return

            if self.void_edit_mode == 'delete':
                self.void_delete_at.emit(float(pos_img.x()), float(pos_img.y()))
                self.hovered_void_id = -1
                return
            if self.void_edit_mode == 'add':
                self._add_click_pos = pos_img
                try:
                    contour = self._local_detect_at(pos_img, self.void_add_offset)
                    if contour is not None and cv2.contourArea(contour) > 3:
                        pts = contour.reshape(-1, 2).tolist()
                        self.void_add_preview = {
                            'points': pts,
                            'seed': (float(pos_img.x()), float(pos_img.y())),
                            'offset': self.void_add_offset
                        }
                    else:
                        self.void_add_preview = None
                        self.void_add_status = "未检测到空洞，Ctrl+滚轮调偏移量"
                        QTimer.singleShot(2000, self._clear_status)
                except Exception:
                    self.void_add_preview = None
                    self.void_add_status = "未检测到空洞，Ctrl+滚轮调偏移量"
                    QTimer.singleShot(2000, self._clear_status)
                self.update()
                return
            if self.void_edit_mode == 'local_brush' and self.lb_state == 'preview':
                self.lb_placed_pos = pos_img
                self.lb_preview_pos = None
                self.lb_state = 'placed'
                self.update()
                return

            if self.roi_edit_enabled and len(self.roi_polygon_points) >= 3:
                v_idx = self._closest_vertex_index(pos_img)
                if v_idx >= 0:
                    self.selected_vertex_idx = v_idx
                    self.drag_kind = 'vertex'
                    self.drag_last_img = pos_img
                    self.is_dragging = True
                    self.update()
                    return

                e_idx = self._closest_edge_index(pos_img)
                if e_idx >= 0:
                    self.selected_vertex_idx = -1
                    self.active_edge_idx = e_idx
                    self.drag_kind = 'edge'
                    self.drag_last_img = pos_img
                    self.is_dragging = True
                    self.update()
                    return

                self.selected_vertex_idx = -1
                self.active_edge_idx = -1

            if self.mode == 'calibration':
                self.current_points = [pos_img, pos_img]
                self.is_dragging = True
            elif self.mode == 'poly':
                if len(self.current_points) >= 3:
                    first_pt = self.current_points[0]
                    hit_r = self.hit_radius_px / max(self.scale, 1e-6)
                    if self._distance(first_pt, pos_img) <= hit_r:
                        pts_list = [(p.x(), p.y()) for p in self.current_points]
                        self.roi_poly_finished.emit(pts_list)
                        self.current_points = []
                        self.update()
                        return
                self.current_points.append(pos_img)
                self.update()
            elif self.mode == 'rect':
                self.drag_start_img = pos_img
                self.current_rect = (pos_img.x(), pos_img.y(), 0, 0)
                self.is_dragging = True

        elif event.button() == Qt.MouseButton.RightButton:
            self.last_mouse_pos = pos_widget
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.img_qt is None:
            return
        pos_widget = event.position()
        pos_img = self.widget_to_img(pos_widget)

        # 局部笔刷预览：始终跟踪鼠标位置
        if self.void_edit_mode == 'local_brush' and self.lb_state == 'preview':
            self.lb_preview_pos = pos_img
            self.update()

        # 删除模式下跟踪鼠标悬停的空洞
        if self.void_edit_mode == 'delete' and self.draw_voids:
            self.hovered_void_id = -1
            for v in reversed(self.draw_voids):
                pts = np.array(v['points'], dtype=np.int32)
                if len(pts) >= 3:
                    if cv2.pointPolygonTest(pts, (pos_img.x(), pos_img.y()), False) >= 0:
                        self.hovered_void_id = v['id']
                        break
            self.update()

        if self.is_dragging:
            if self.drag_kind == 'vertex' and 0 <= self.selected_vertex_idx < len(self.roi_polygon_points):
                self.roi_polygon_points[self.selected_vertex_idx] = self._clamp_to_image(pos_img)
                self.update()
            elif self.drag_kind == 'edge' and len(self.roi_polygon_points) >= 3 and self.active_edge_idx >= 0:
                n = len(self.roi_polygon_points)
                i0 = self.active_edge_idx
                i1 = (i0 + 1) % n
                delta = pos_img - self.drag_last_img
                self.roi_polygon_points[i0] = self._clamp_to_image(self.roi_polygon_points[i0] + delta)
                self.roi_polygon_points[i1] = self._clamp_to_image(self.roi_polygon_points[i1] + delta)
                self.drag_last_img = pos_img
                self.update()
            elif self.mode == 'calibration':
                self.current_points[1] = pos_img
                self.update()
            elif self.mode == 'rect':
                x = min(self.drag_start_img.x(), pos_img.x())
                y = min(self.drag_start_img.y(), pos_img.y())
                w = abs(self.drag_start_img.x() - pos_img.x())
                h = abs(self.drag_start_img.y() - pos_img.y())
                self.current_rect = (x, y, w, h)
                self.roi_rect_changed.emit(self.current_rect)
                self.update()

        # 编辑态：跟踪光标最近的顶点，用于"按需显示"手柄（只高亮最近的那个）
        if (self.roi_edit_enabled and not self.is_dragging
                and not (event.buttons() & Qt.MouseButton.RightButton)
                and len(self.roi_polygon_points) >= 3):
            idx = self._closest_vertex_index(pos_img)
            if idx != self.hovered_vertex_idx:
                self.hovered_vertex_idx = idx
                self.update()
            if idx >= 0:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        if event.buttons() & Qt.MouseButton.RightButton:
            delta = pos_widget - self.last_mouse_pos
            self.offset += delta
            self.last_mouse_pos = pos_widget
            self.update()

    def mouseReleaseEvent(self, event):
        if self.is_dragging and event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False

            if self.drag_kind in ('vertex', 'edge'):
                if self.snap_enabled:
                    if self.drag_kind == 'vertex' and 0 <= self.selected_vertex_idx < len(self.roi_polygon_points):
                        self.roi_polygon_points[self.selected_vertex_idx] = self._snap_point(
                            self.roi_polygon_points[self.selected_vertex_idx])
                    elif self.drag_kind == 'edge' and len(self.roi_polygon_points) >= 3 and self.active_edge_idx >= 0:
                        n = len(self.roi_polygon_points)
                        i0 = self.active_edge_idx
                        i1 = (i0 + 1) % n
                        self.roi_polygon_points[i0] = self._snap_point(self.roi_polygon_points[i0])
                        self.roi_polygon_points[i1] = self._snap_point(self.roi_polygon_points[i1])
                self.drag_kind = None
                self.active_edge_idx = -1
                self._emit_roi_polygon_edited()
                self.update()
                return

            if self.mode == 'calibration':
                if len(self.current_points) == 2:
                    self.calib_drawn.emit(self.current_points[0], self.current_points[1])
                    self.current_points = []
            elif self.mode == 'rect':
                if self.current_rect and self.current_rect[2] > 5 and self.current_rect[3] > 5:
                    self.roi_rect_finished.emit(self.current_rect)
                else:
                    self.current_rect = None
                    self.overlay_preview = None
                self.update()

        if event.button() == Qt.MouseButton.RightButton:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        # 双击 ROI 边：在该处插入顶点（配合拖拽顶点 / Delete 删除，实现增删顶点）
        if (event.button() == Qt.MouseButton.LeftButton
                and self.roi_edit_enabled and len(self.roi_polygon_points) >= 3
                and self.void_edit_mode == 'none' and not self.teach_void_mode):
            pos_img = self.widget_to_img(event.position())
            e_idx = self._closest_edge_index(pos_img)
            if e_idx >= 0:
                self.roi_polygon_points.insert(e_idx + 1, pos_img)
                self.selected_vertex_idx = e_idx + 1
                self.active_edge_idx = -1
                self.is_dragging = False
                self._emit_roi_polygon_edited()
                self.update()
                return

        if event.button() == Qt.MouseButton.LeftButton and self.void_edit_mode == 'add':
            if self.void_add_preview:
                pts = self.void_add_preview['points']
                if len(pts) >= 3:
                    self.void_add_polygon.emit(pts)
                self.void_add_preview = None
            self.update()
            return

        if event.button() == Qt.MouseButton.LeftButton and self.void_edit_mode == 'local_brush' and self.lb_state == 'placed':
            if self.lb_placed_pos is not None and self.lb_radius > 0:
                cx, cy = self.lb_placed_pos.x(), self.lb_placed_pos.y()
                self.void_local_region_confirmed.emit(cx, cy, self.lb_radius)
                self.lb_placed_pos = None
                self.lb_state = 'preview'
                self.update()
            return

        if event.button() == Qt.MouseButton.RightButton and self.void_edit_mode == 'local_brush' and self.lb_confirmed:
            pos_img = self.widget_to_img(event.position())
            for i, reg in enumerate(self.lb_confirmed):
                d = np.hypot(pos_img.x() - reg['cx'], pos_img.y() - reg['cy'])
                if d <= reg['radius']:
                    self.void_local_region_removed.emit(i)
                    del self.lb_confirmed[i]
                    self.update()
                    break
            return

        if event.button() == Qt.MouseButton.LeftButton and self.roi_edit_enabled and len(self.roi_polygon_points) >= 3:
            pos_img = self.widget_to_img(event.position())
            edge_idx = self._closest_edge_index(pos_img)
            if edge_idx >= 0:
                insert_idx = edge_idx + 1
                self.roi_polygon_points.insert(insert_idx, self._snap_point(pos_img))
                self.selected_vertex_idx = insert_idx
                self._emit_roi_polygon_edited()
                self.update()
                return

        if self.mode == 'poly' and len(self.current_points) > 2:
            pts = np.array([[p.x(), p.y()] for p in self.current_points], np.int32).reshape((-1, 1, 2))
            if cv2.contourArea(pts) > 10:
                pts_list = [(p.x(), p.y()) for p in self.current_points]
                self.roi_poly_finished.emit(pts_list)
                self.current_points = []
            else:
                QMessageBox.warning(self.parent(), 'Notice', 'Invalid polygon (too small or self-intersecting).')
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.void_edit_mode == 'add':
            self.void_add_preview = None
            self.update()
            return
        if event.key() == Qt.Key.Key_Delete and self.roi_edit_enabled and len(self.roi_polygon_points) > 3:
            if 0 <= self.selected_vertex_idx < len(self.roi_polygon_points):
                self.roi_polygon_points.pop(self.selected_vertex_idx)
                self.selected_vertex_idx = -1
                self._emit_roi_polygon_edited()
                self.update()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if self.img_qt is None:
            return

        modifiers = event.modifiers()
        # 局部笔刷模式下的滚轮操作
        if self.void_edit_mode == 'local_brush':
            pos_widget = event.position()
            pos_img = self.widget_to_img(pos_widget)

            # Ctrl+滚轮：调笔刷半径（预览态 或 已放置未确认态）
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                factor = 1.05 if delta > 0 else 0.95
                self.lb_radius = max(10, min(200, self.lb_radius * factor))
                self.update()
                return

            # Shift+滚轮：调节已确认区域的阈值
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                if not self.lb_confirmed:
                    return
                # 找鼠标下方的已确认区域
                hit_idx = -1
                for i, reg in enumerate(self.lb_confirmed):
                    d = np.hypot(pos_img.x() - reg['cx'], pos_img.y() - reg['cy'])
                    if d <= reg['radius']:
                        hit_idx = i
                        break
                if hit_idx >= 0:
                    delta = 5 if event.angleDelta().y() > 0 else -5
                    new_thresh = max(0, min(255, self.lb_confirmed[hit_idx]['thresh'] + delta))
                    self.lb_confirmed[hit_idx]['thresh'] = new_thresh
                    self.void_local_threshold_changed.emit(hit_idx, new_thresh)
                    self.update()
                return

            # 无修饰键：在 placed 态可继续调半径
            if self.lb_state == 'placed':
                delta = event.angleDelta().y()
                factor = 1.05 if delta > 0 else 0.95
                self.lb_radius = max(10, min(200, self.lb_radius * factor))
                self.update()
                return

        # 添加遗漏模式：Ctrl+滚轮调节 Otsu 阈值偏移
        modifiers = event.modifiers()
        if self.void_edit_mode == 'add' and modifiers & Qt.KeyboardModifier.ControlModifier:
            try:
                delta = event.angleDelta().y()
                step = 2 if abs(delta) > 60 else 1
                self.void_add_offset = max(-50, min(50, self.void_add_offset + (step if delta > 0 else -step)))
                self.void_add_preview = None
                if hasattr(self, '_add_click_pos') and self._add_click_pos:
                    contour = self._local_detect_at(self._add_click_pos, self.void_add_offset)
                    if contour is not None and cv2.contourArea(contour) > 3:
                        pts = contour.reshape(-1, 2).tolist()
                        self.void_add_preview = {
                            'points': pts,
                            'seed': (float(self._add_click_pos.x()), float(self._add_click_pos.y())),
                            'offset': self.void_add_offset
                        }
                self.void_add_status = f"阈值偏移: {self.void_add_offset:+d}"
                QTimer.singleShot(1500, self._clear_status)
            except Exception:
                pass
            self.update()
            return

        # 默认缩放
        zoom_in = event.angleDelta().y() > 0
        factor = 1.1 if zoom_in else 0.9
        mouse_pos = event.position()
        img_pos_before = (mouse_pos.x() - self.offset.x()) / self.scale
        self.scale *= factor
        self.scale = max(0.01, min(self.scale, 50.0))
        new_offset_x = mouse_pos.x() - img_pos_before * self.scale
        img_y_before = (mouse_pos.y() - self.offset.y()) / self.scale
        new_offset_y = mouse_pos.y() - img_y_before * self.scale
        self.offset = QPointF(new_offset_x, new_offset_y)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#f0f4f8'))

        if self.img_qt is None:
            paint_empty_state(painter, self)
            return

        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)

        # 图片阴影效果
        shadow_rect = QRectF(-2, -2, self.img_qt.width() + 4, self.img_qt.height() + 4)
        painter.fillRect(shadow_rect, QColor(0, 0, 0, 20))
        
        painter.drawImage(0, 0, self.img_qt)

        if self.overlay_mask and self.show_roi_overlay:
            painter.drawImage(0, 0, self.overlay_mask)

        if self.overlay_preview and self.current_rect:
            rx, ry, _, _ = self.current_rect
            painter.drawImage(int(rx), int(ry), self.overlay_preview)

        if len(self.roi_polygon_points) >= 2:
            for i in range(len(self.roi_polygon_points)):
                p0 = self.roi_polygon_points[i]
                p1 = self.roi_polygon_points[(i + 1) % len(self.roi_polygon_points)]
                if i == self.active_edge_idx:
                    painter.setPen(QPen(QColor(245, 64, 64), 2.8 / self.scale))
                else:
                    painter.setPen(QPen(QColor(66, 153, 225), 2.0 / self.scale))
                painter.drawLine(p0, p1)

            # 顶点手柄按需显示：只在编辑态画，且只画"光标最近的"和"已选中的"两个。
            # 焊层带边界常有上百个顶点（界面过渡带起伏是真实几何），全画会挤成一片
            # 既挡住图像又抓不住想拖的那个点。
            if self.roi_edit_enabled:
                rad = 4.5 / self.scale
                marks = {self.selected_vertex_idx, self.hovered_vertex_idx}
                for i in marks:
                    if 0 <= i < len(self.roi_polygon_points):
                        pt = self.roi_polygon_points[i]
                        if i == self.hovered_vertex_idx:
                            painter.setBrush(QColor(245, 64, 64))
                            painter.setPen(QPen(QColor(255, 255, 255), 1.4 / self.scale))
                            painter.drawEllipse(pt, rad * 1.25, rad * 1.25)
                        else:
                            painter.setBrush(QColor(56, 189, 248))
                            painter.setPen(QPen(QColor(255, 255, 255), 1.0 / self.scale))
                            painter.drawEllipse(pt, rad, rad)

        if self.void_edit_mode == 'add' and self.void_add_preview and len(self.void_add_preview.get('points', [])) >= 3:
            pts_q = [QPointF(p[0], p[1]) for p in self.void_add_preview['points']]
            painter.setPen(QPen(QColor(255, 193, 7), 2.5 / self.scale))
            painter.setBrush(QBrush(QColor(255, 193, 7, 60)))
            painter.drawPolygon(pts_q)
            seed = self.void_add_preview.get('seed')
            if seed:
                painter.setBrush(QColor(255, 193, 7))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(seed[0], seed[1]), 3.5 / self.scale, 3.5 / self.scale)
            # 灵敏度标签
            off = self.void_add_preview.get('offset', self.void_add_offset)
            label = f"阈值偏移: {off:+d}  Ctrl+滚轮调 · 双击确认 · ESC取消"
            painter.restore()
            font = QFont('Segoe UI', 11, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            tr = fm.boundingRect(label)
            tr.moveCenter(QPointF(self.width() / 2, 30).toPoint())
            tr.adjust(-12, -6, 12, 8)
            painter.fillRect(tr, QColor(0, 0, 0, 170))
            painter.setPen(QColor('white'))
            painter.drawText(tr, Qt.AlignmentFlag.AlignCenter, label)
            painter.save()
            painter.translate(self.offset)
            painter.scale(self.scale, self.scale)

        if self.draw_voids:
            pen_edge = QPen(QColor(239, 68, 68), 2 / self.scale)
            painter.setPen(pen_edge)
            brush_fill = QBrush(QColor(220, 38, 38, 180)) if self.fill_voids else Qt.BrushStyle.NoBrush
            painter.setBrush(brush_fill)
            for v in self.draw_voids:
                poly_pts = [QPointF(pt[0], pt[1]) for pt in v['points']]
                painter.drawPolygon(poly_pts)

        # 删除模式下高亮悬停的空洞
        if self.void_edit_mode == 'delete' and self.hovered_void_id > 0:
            for v in self.draw_voids:
                if v['id'] == self.hovered_void_id:
                    poly_pts = [QPointF(pt[0], pt[1]) for pt in v['points']]
                    painter.setPen(QPen(QColor(255, 255, 0), 3 / self.scale))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPolygon(poly_pts)
                    break

        if self.mode == 'calibration' and len(self.current_points) == 2:
            painter.setPen(QPen(QColor('#4299e1'), 2 / self.scale))
            painter.drawLine(self.current_points[0], self.current_points[1])

        if self.mode == 'poly' and len(self.current_points) > 0:
            painter.setPen(QPen(QColor('#4299e1'), 2 / self.scale, Qt.PenStyle.DashLine))
            pts = self.current_points
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])
            painter.drawLine(pts[-1], self.widget_to_img(self.mapFromGlobal(QCursor.pos())))
            rad = 4.0 / self.scale
            painter.setBrush(QColor('#4299e1'))
            painter.setPen(QPen(QColor('white'), 1.0 / self.scale))
            for p in pts:
                painter.drawEllipse(p, rad, rad)

        if self.mode == 'rect' and self.current_rect:
            painter.setPen(QPen(QColor('#4299e1'), 2 / self.scale, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(*self.current_rect))

        if self.calib_line:
            p1, p2, txt = self.calib_line
            painter.setPen(QPen(QColor('#4299e1'), 3 / self.scale))
            painter.drawLine(p1, p2)
            painter.setBrush(QColor('#4299e1'))
            rad = 4 / self.scale
            painter.drawEllipse(p1, rad, rad)
            painter.drawEllipse(p2, rad, rad)

        # ==== 局部笔刷渲染（图像坐标） ====
        pen_blue = QPen(QColor(56, 189, 248), 2.0 / self.scale)
        pen_blue_bold = QPen(QColor(56, 189, 248), 2.5 / self.scale)

        # 已确认区域
        for reg in self.lb_confirmed:
            painter.setPen(pen_blue)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(reg['cx'], reg['cy']), reg['radius'], reg['radius'])

        # 已放置未确认区域（虚线圆 + 点）
        if self.lb_state == 'placed' and self.lb_placed_pos:
            r = self.lb_radius
            painter.setPen(pen_blue_bold)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self.lb_placed_pos, r, r)
            dot_r = 2.5 / self.scale
            num_dots = 16
            for i in range(num_dots):
                angle = 2 * np.pi * i / num_dots
                painter.setBrush(QColor(56, 189, 248))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(
                    QPointF(self.lb_placed_pos.x() + r * np.cos(angle),
                            self.lb_placed_pos.y() + r * np.sin(angle)),
                    dot_r, dot_r)

        # 预览区域（半透明蓝）
        if self.lb_state == 'preview' and self.lb_preview_pos:
            painter.setPen(QPen(QColor(56, 189, 248, 120), 2.0 / self.scale))
            painter.setBrush(QBrush(QColor(56, 189, 248, 30)))
            painter.drawEllipse(self.lb_preview_pos, self.lb_radius, self.lb_radius)

        painter.restore()  # 结束图像坐标变换

        if self.void_add_status:
            font = QFont('Segoe UI', 12, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            tr = fm.boundingRect(self.void_add_status)
            tr.moveCenter(QPointF(self.width() / 2, 30).toPoint())
            tr.adjust(-12, -6, 12, 8)
            painter.fillRect(tr, QColor(180, 80, 80, 200))
            painter.setPen(QColor('white'))
            painter.drawText(tr, Qt.AlignmentFlag.AlignCenter, self.void_add_status)

        if self.void_rate_text:
            font = QFont('Segoe UI', 15, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            text_rect = fm.boundingRect(self.void_rate_text)
            rx = self.width() - text_rect.width() - 20
            ry = 10
            text_rect.moveTo(rx, ry)
            text_rect.adjust(-10, -4, 10, 4)
            painter.fillRect(text_rect, QColor(0, 0, 0, 160))
            painter.setPen(QColor('white'))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.void_rate_text)

        # ==== 局部笔刷标签（控件坐标） ====
        if self.lb_confirmed:
            font = QFont('Segoe UI', 9, QFont.Weight.Bold)
            painter.setFont(font)
            for reg in self.lb_confirmed:
                label = f"T:{reg['thresh']}"
                lbl_screen = self.img_to_widget(QPointF(reg['cx'], reg['cy'] + reg['radius']))
                fm = painter.fontMetrics()
                text_rect = fm.boundingRect(label)
                text_rect.moveCenter(lbl_screen.toPoint())
                text_rect.adjust(-4, -2, 4, 2)
                painter.fillRect(text_rect, QColor(0, 0, 0, 0))
                painter.setPen(QColor('white'))
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

        if self.draw_voids and self.show_labels:
            painter.setPen(QColor('white'))
            font = QFont('Segoe UI', 10, QFont.Weight.Bold)
            painter.setFont(font)
            for v in self.draw_voids:
                screen_pt = self.img_to_widget(QPointF(v['cx'], v['cy']))
                text = str(v['id'])
                fm = painter.fontMetrics()
                text_rect = fm.boundingRect(text)
                text_rect.moveCenter(screen_pt.toPoint())
                text_rect.adjust(-4, -2, 4, 2)
                painter.fillRect(text_rect, QColor(0, 0, 0, 0))
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

        if self.calib_line:
            p1, p2, txt = self.calib_line
            mid_img = (p1 + p2) / 2
            mid_scr = self.img_to_widget(mid_img)
            font = QFont('Segoe UI', 11, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            text_rect = fm.boundingRect(txt)
            text_rect.moveCenter(mid_scr.toPoint())
            text_rect.adjust(-6, -3, 6, 3)
            painter.fillRect(text_rect, QColor(0, 0, 0, 0))
            painter.setPen(QColor('white'))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, txt)