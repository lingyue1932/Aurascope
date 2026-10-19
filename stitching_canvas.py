"""图像拼接画布组件 - 支持标记点对齐拼接"""

import cv2
import numpy as np
from PyQt6.QtWidgets import QWidget, QMessageBox
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QRect
from PyQt6.QtGui import QImage, QPainter, QPen, QColor, QBrush, QFont, QCursor


# 拼接画布未被图像覆盖处的背景灰度（用户要求深灰 ✗；改这里即可）
STITCH_BG = 64

# 是否在标记对齐后再做"互相关自动微调"
# 实测（test_stitching.py 用例 A/B）：在真实 SEM 纹理上，这个微调会把**已经
# 完全对齐**的结果反而改坏（768px 宽 → 786px，加进去 18px ✗）→ 默认关闭 ✔
# 标记对齐本身已经足够准（缝带平均差 0.12/255 ✗ 全图 0.02/255 ✔）
STITCH_AUTO_REFINE = False


class StitchingCanvas(QWidget):
    """图像拼接画布 - 支持标记点对齐"""
    
    line_marked = pyqtSignal(int, QPointF, QPointF)  # 标记线完成信号 (image_index, p1, p2)
    stitch_completed = pyqtSignal()  # 拼接完成信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # 图像列表
        self.images = []  # list of dict: {image, name, line_p1, line_p2, marked}
        self.current_image_idx = 0
        
        # 画布变换
        self.scale = 1.0
        self.offset = QPointF(0, 0)
        self.last_mouse_pos = QPointF()
        
        # 标记模式
        self.mark_mode = False  # True = 正在标记模式
        self.temp_points = []  # 临时存储标记点
        
        # 拖拽模式
        self.is_dragging = False
        self.drag_point_idx = 0  # 0 = p1, 1 = p2
        
        # 平移
        self.is_panning = False
        self.pan_start = QPointF()
        
        # 拼接结果
        self.stitched_image = None
        
    def set_images(self, images):
        """设置图像列表"""
        self.images = []
        for i, img_data in enumerate(images):
            self.images.append({
                'image': img_data['image'],
                'name': img_data['name'],
                'line_p1': None,
                'line_p2': None,
                'marked': False
            })
        self.current_image_idx = 0
        self.stitched_image = None
        self.fit_in_view()
        self.update()
    
    def set_current_image(self, idx):
        """设置当前显示的图像"""
        if 0 <= idx < len(self.images):
            self.current_image_idx = idx
            self.temp_points = []
            self.update()
    
    def start_mark_mode(self):
        """开始标记模式"""
        self.mark_mode = True
        self.temp_points = []
        self.update()
    
    def stop_mark_mode(self):
        """停止标记模式"""
        self.mark_mode = False
        self.temp_points = []
        self.update()
    
    def next_image(self):
        """切换到下一张图"""
        if self.current_image_idx < len(self.images) - 1:
            self.current_image_idx += 1
            self.temp_points = []
            self.update()
            return True
        return False
    
    def prev_image(self):
        """切换到上一张图"""
        if self.current_image_idx > 0:
            self.current_image_idx -= 1
            self.temp_points = []
            self.update()
            return True
        return False
    
    def fit_in_view(self):
        """自适应视图"""
        if self.stitched_image is not None:
            img = self.stitched_image
        elif self.images:
            img = self.images[self.current_image_idx]['image']
        else:
            return
        
        h, w = img.shape[:2]
        
        w_ratio = self.width() / w
        h_ratio = self.height() / h
        self.scale = min(w_ratio, h_ratio) * 0.9
        
        cx = (self.width() - w * self.scale) / 2
        cy = (self.height() - h * self.scale) / 2
        self.offset = QPointF(cx, cy)
    
    def widget_to_img(self, pos):
        """控件坐标转图像坐标"""
        x = (pos.x() - self.offset.x()) / self.scale
        y = (pos.y() - self.offset.y()) / self.scale
        return QPointF(x, y)
    
    def img_to_widget(self, pos_img):
        """图像坐标转控件坐标"""
        x = pos_img.x() * self.scale + self.offset.x()
        y = pos_img.y() * self.scale + self.offset.y()
        return QPointF(x, y)
    
    def mousePressEvent(self, event):
        if not self.images:
            return
        
        self.setFocus()
        pos_widget = event.position()
        pos_img = self.widget_to_img(pos_widget)
        
        if event.button() == Qt.MouseButton.LeftButton:
            if self.mark_mode:
                img = self.images[self.current_image_idx]['image']
                h, w = img.shape[:2]
                
                x = max(0, min(w - 1, pos_img.x()))
                y = max(0, min(h - 1, pos_img.y()))
                
                if len(self.temp_points) == 0:
                    # 第一个点
                    self.temp_points.append(QPointF(x, y))
                    self.update()
                else:
                    # 第二个点，完成标记
                    p1 = self.temp_points[0]
                    p2 = QPointF(x, y)
                    
                    self.images[self.current_image_idx]['line_p1'] = p1
                    self.images[self.current_image_idx]['line_p2'] = p2
                    self.images[self.current_image_idx]['marked'] = True
                    
                    self.line_marked.emit(self.current_image_idx, p1, p2)
                    
                    self.temp_points = []
                    self.update()
            else:
                # 检查是否点击了已标记的点
                img_data = self.images[self.current_image_idx]
                if img_data['marked']:
                    # 检查是否点击了p1或p2
                    p1 = img_data['line_p1']
                    p2 = img_data['line_p2']
                    
                    # 将点转换为控件坐标进行距离检测
                    p1_widget = self.img_to_widget(p1)
                    p2_widget = self.img_to_widget(p2)
                    
                    # 点击阈值（像素）
                    threshold = 15
                    
                    dist_to_p1 = ((pos_widget.x() - p1_widget.x()) ** 2 + 
                                  (pos_widget.y() - p1_widget.y()) ** 2) ** 0.5
                    dist_to_p2 = ((pos_widget.x() - p2_widget.x()) ** 2 + 
                                  (pos_widget.y() - p2_widget.y()) ** 2) ** 0.5
                    
                    if dist_to_p1 < threshold:
                        self.is_dragging = True
                        self.drag_point_idx = 0
                        self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    elif dist_to_p2 < threshold:
                        self.is_dragging = True
                        self.drag_point_idx = 1
                        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        
        elif event.button() == Qt.MouseButton.RightButton:
            self.is_panning = True
            self.pan_start = pos_widget
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
    
    def mouseMoveEvent(self, event):
        pos_widget = event.position()
        
        if self.is_dragging:
            # 拖拽点
            pos_img = self.widget_to_img(pos_widget)
            img_data = self.images[self.current_image_idx]
            img = img_data['image']
            h, w = img.shape[:2]
            
            x = max(0, min(w - 1, pos_img.x()))
            y = max(0, min(h - 1, pos_img.y()))
            
            if self.drag_point_idx == 0:
                img_data['line_p1'] = QPointF(x, y)
            else:
                img_data['line_p2'] = QPointF(x, y)
            
            self.update()
        elif self.is_panning:
            delta = pos_widget - self.pan_start
            self.offset += delta
            self.pan_start = pos_widget
            self.update()
        else:
            # 检查鼠标是否在可拖拽的点附近，改变光标
            if not self.mark_mode and self.images:
                img_data = self.images[self.current_image_idx]
                if img_data['marked']:
                    p1 = img_data['line_p1']
                    p2 = img_data['line_p2']
                    
                    p1_widget = self.img_to_widget(p1)
                    p2_widget = self.img_to_widget(p2)
                    
                    threshold = 15
                    
                    dist_to_p1 = ((pos_widget.x() - p1_widget.x()) ** 2 + 
                                  (pos_widget.y() - p1_widget.y()) ** 2) ** 0.5
                    dist_to_p2 = ((pos_widget.x() - p2_widget.x()) ** 2 + 
                                  (pos_widget.y() - p2_widget.y()) ** 2) ** 0.5
                    
                    if dist_to_p1 < threshold or dist_to_p2 < threshold:
                        self.setCursor(Qt.CursorShape.OpenHandCursor)
                    else:
                        self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_dragging:
                self.is_dragging = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
                # 发送信号通知标定点已修改
                img_data = self.images[self.current_image_idx]
                self.line_marked.emit(self.current_image_idx, img_data['line_p1'], img_data['line_p2'])
        elif event.button() == Qt.MouseButton.RightButton:
            self.is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def wheelEvent(self, event):
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
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.stop_mark_mode()
        elif event.key() == Qt.Key.Key_Right:
            self.next_image()
        elif event.key() == Qt.Key.Key_Left:
            self.prev_image()
        super().keyPressEvent(event)
    
    def stitch_images(self, progress_callback=None):
        """按标记点对齐并拼接图像（X/Y 双轴对齐 + 重叠区羽化融合）

        标记规则（与界面提示一致）：
        - 第一张：标金锡**右端（尾部）**
        - 中间图：标金锡**左端（头部）** 与 **右端（尾部）**
        - 最后一张：标金锡**左端（头部）**

        对齐逻辑：第 i 张的"尾部点"与第 i+1 张的"头部点"是**同一处特征** ✗
        → 两张图的相对位置由这两个点的 **x 与 y 差值同时决定** ✔
        （旧实现只用了 y ✗ → 每张按整幅宽度硬接、重叠区被重复，既不齐也有缝 ✗✗）

        无缝：重叠区按**线性羽化**加权融合（不是硬贴），接缝不可见 ✔
        背景：未覆盖区域用深灰（STITCH_BG）✔
        """
        if not self.images:
            return None
        marked = [im for im in self.images if im['marked']
                  and im.get('line_p1') is not None]
        if len(marked) < 2:
            return None
        if progress_callback:
            progress_callback(10, "分析标记点...")

        # ---- ① 取每张图的"头点/尾点"（图像坐标；按 x 分辨头尾）----
        head_pts, tail_pts = [], []
        for im in marked:
            p1, p2 = im['line_p1'], im['line_p2']
            if p2 is None:                      # 只标了一个点：头尾同点
                head_pts.append((p1.x(), p1.y()))
                tail_pts.append((p1.x(), p1.y()))
                continue
            if p1.x() <= p2.x():
                head_pts.append((p1.x(), p1.y()))
                tail_pts.append((p2.x(), p2.y()))
            else:
                head_pts.append((p2.x(), p2.y()))
                tail_pts.append((p1.x(), p1.y()))

        # ---- ② 原点的 X/Y 偏移：让前一张尾点 ≡ 后一张头点 ----
        if progress_callback:
            progress_callback(30, "计算对齐偏移...")
        origins = [(0.0, 0.0)]
        for i in range(len(marked) - 1):
            dx = float(tail_pts[i][0]) - float(head_pts[i + 1][0])
            dy = float(tail_pts[i][1]) - float(head_pts[i + 1][1])
            origins.append((origins[-1][0] + dx, origins[-1][1] + dy))
        origins = [(int(round(x)), int(round(y))) for x, y in origins]

        # ---- ③ 自动微调（可选）：在重叠区做小范围互相关，修正标记的手抖 ----
        if STITCH_AUTO_REFINE:
            refined = self._refine_by_overlap(marked, origins, span=24)
            if refined is not None:
                origins = refined

        # ---- ④ 画布范围（含负偏移）+ 深灰底 ----
        if progress_callback:
            progress_callback(50, "创建画布...")
        xs = [origins[i][0] for i in range(len(marked))]
        ys = [origins[i][1] for i in range(len(marked))]
        ws = [marked[i]['image'].shape[1] for i in range(len(marked))]
        hs = [marked[i]['image'].shape[0] for i in range(len(marked))]
        min_x, min_y = min(xs), min(ys)
        max_x = max(xs[i] + ws[i] for i in range(len(marked)))
        max_y = max(ys[i] + hs[i] for i in range(len(marked)))
        W, H = max(1, max_x - min_x), max(1, max_y - min_y)

        acc = np.zeros((H, W, 3), np.float32)          # 加权累加
        wsum = np.zeros((H, W, 1), np.float32)

        # ---- ⑤ 逐张羽化融合 ----
        if progress_callback:
            progress_callback(60, "融合拼接...")
        total = len(marked)
        for i, im in enumerate(marked):
            img = im['image']
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            f = np.asarray(img, np.float32)
            h, w = f.shape[:2]
            # 左右各自的重叠宽度（决定羽化带；只在重叠侧羽化 ✗）
            ov_l = 0
            if i > 0:
                ov_l = max(0, (origins[i - 1][0] + ws[i - 1]) - origins[i][0])
            ov_r = 0
            if i < total - 1:
                ov_r = max(0, (origins[i][0] + w) - origins[i + 1][0])
            wm = self._feather_weight(h, w, min(ov_l, 80), min(ov_r, 80))
            x0, y0 = origins[i][0] - min_x, origins[i][1] - min_y
            acc[y0:y0 + h, x0:x0 + w] += f * wm
            wsum[y0:y0 + h, x0:x0 + w] += wm
            if progress_callback:
                progress_callback(60 + int(35 * (i + 1) / total),
                                  f"融合第 {i+1}/{total} 张图像...")

        # ---- ⑥ 归一化；没覆盖到的地方 = 深灰背景 ----
        bg = float(STITCH_BG)
        cov = wsum[:, :, 0] > 1e-6
        out = np.zeros((H, W, 3), np.float32)
        out[:] = bg
        for c in range(3):
            out[:, :, c] = np.where(cov, acc[:, :, c] / np.maximum(wsum[:, :, 0], 1e-6), bg)
        stitched = np.clip(out, 0, 255).astype(np.uint8)

        if progress_callback:
            progress_callback(100, "完成")
        self.stitched_image = stitched
        self.fit_in_view()
        self.stitch_completed.emit()
        return stitched

    @staticmethod
    def _feather_weight(h, w, fl=0, fr=0):
        """羽化权重图：**只在有重叠的那一侧**线性过渡

        fl/fr = 左右各自的重叠宽度（0 = 该侧不羽化）。
        关键：只有"和邻居重叠"的边才需要羽化 ✗ —— 如果两侧都羽化，
        整条拼图的最外缘会"淡出"到背景，出现暗边 ✗（实测过 ✗）
        """
        if fl <= 0 and fr <= 0:
            return np.ones((h, w, 1), np.float32)
        wm = np.ones(w, np.float32)
        if fl > 0:
            f = min(int(fl), max(1, w // 2))
            wm[:f] = np.linspace(0.05, 1.0, f, endpoint=True, dtype=np.float32)
        if fr > 0:
            f = min(int(fr), max(1, w // 2))
            wm[-f:] = np.linspace(1.0, 0.05, f, endpoint=True, dtype=np.float32)
        return wm.reshape(1, w, 1) * np.ones((h, 1, 1), np.float32)

    def _refine_by_overlap(self, marked, origins, span=24):
        """在重叠区做小范围灰度互相关，微调偏移（自动对齐到真实内容）

        只在"有重叠"的相邻对上尝试；找不到更好匹配就返回 None（保持标记结果）✔
        """
        if len(marked) < 2:
            return None
        out = [origins[0]]
        for i in range(len(marked) - 1):
            a = marked[i]['image']
            b = marked[i + 1]['image']
            ax, ay = out[i]
            bx, by = origins[i + 1]
            aw, ah = a.shape[1], a.shape[0]
            bw, bh = b.shape[1], b.shape[0]
            # 重叠区（以 a 的右缘与 b 的左缘为准）
            ov_w = aw + ax - bx
            ov_h = min(ah + ay, bh + by) - max(ay, by)
            if ov_w < 40 or ov_h < 40:
                out.append((bx, by))
                continue
            ga = a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
            gb = b if b.ndim == 2 else cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
            # 取 a 的右缘条带作为模板
            tw = min(ov_w, 120)
            y0a, y0b = max(ay, by), max(ay, by)
            ty0 = y0a - ay
            ty1 = ty0 + ov_h
            if ty0 < 0 or ty1 > ga.shape[0]:
                out.append((bx, by))
                continue
            templ = ga[ty0:ty1, max(0, aw - tw):aw]
            if templ.size < 400:
                out.append((bx, by))
                continue
            # 注意：得分是"负的平均绝对差"（越小越好 → 得分为负 ✗）
            # 初值必须是 -inf 而不是 0.0，否则永远不会接受任何修正 ✗（实测踩过 ✗）
            best = (-1e18, bx, by)
            for ddx in range(-span, span + 1, 2):
                for ddy in range(-span, span + 1, 2):
                    sx = (bx + ddx) - ax
                    sy = (by + ddy) - ay
                    x_in_b = aw - sx
                    y_in_b = ty0 - sy
                    if x_in_b < 0 or y_in_b < 0:
                        continue
                    patch = gb[y_in_b:y_in_b + templ.shape[0],
                               x_in_b:x_in_b + templ.shape[1]]
                    if patch.shape != templ.shape or patch.size < 400:
                        continue
                    d = float(np.mean(np.abs(patch.astype(np.float32)
                                             - templ.astype(np.float32))))
                    score = -d                      # 平均绝对差越小越好
                    if score > best[0]:
                        best = (score, bx + ddx, by + ddy)
            out.append((best[1], best[2]))
        return out

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#f0f4f8'))
        
        if not self.images:
            painter.setPen(QColor('#94a3b8'))
            font = QFont('Segoe UI', 14)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '导入图像后将显示在此处')
            return
        
        if self.stitched_image is not None:
            self._draw_stitched(painter)
            return
        
        self._draw_current_image(painter)
    
    def _draw_stitched(self, painter):
        """绘制拼接结果（支持缩放平移）"""
        img = self.stitched_image
        if len(img.shape) == 2:
            rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        h, w = rgb.shape[:2]
        bytes_per_line = 3 * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        painter.drawImage(0, 0, qimg)
        painter.restore()
        
        painter.setPen(QColor(0, 100, 0))
        font = QFont('Segoe UI', 14, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(10, 30, f"拼接完成 - {w} x {h} 像素")
        painter.setPen(QColor(100, 100, 100))
        painter.drawText(10, 55, "滚轮缩放 | 右键拖拽平移")
    
    def _draw_current_image(self, painter):
        """绘制当前图像"""
        img_data = self.images[self.current_image_idx]
        img = img_data['image']
        
        if len(img.shape) == 2:
            rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        h, w = rgb.shape[:2]
        bytes_per_line = 3 * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        painter.drawImage(0, 0, qimg)
        painter.restore()
        
        # 绘制所有已标记的线（包括当前图和其他图）
        for i, img_d in enumerate(self.images):
            if img_d['marked']:
                p1 = img_d['line_p1']
                p2 = img_d['line_p2']
                
                # 只有当前图像的点需要转换坐标
                if i == self.current_image_idx:
                    p1_widget = self.img_to_widget(p1)
                    p2_widget = self.img_to_widget(p2)
                else:
                    # 其他图像的线不显示（因为当前显示的是另一张图）
                    continue
                
                # 当前图像的标记线用绿色
                painter.setPen(QPen(QColor(0, 255, 0), 3))
                painter.drawLine(p1_widget, p2_widget)
                
                # 绘制可拖拽的点（更大的点击区域）
                painter.setBrush(QColor(0, 255, 0))
                painter.setPen(QPen(QColor(255, 255, 255), 2))
                painter.drawEllipse(p1_widget, 10, 10)
                painter.drawEllipse(p2_widget, 10, 10)
                
                # 绘制点中心
                painter.setBrush(QColor(0, 200, 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(p1_widget, 5, 5)
                painter.drawEllipse(p2_widget, 5, 5)
        
        # 绘制临时标记点
        for pt in self.temp_points:
            pt_widget = self.img_to_widget(pt)
            painter.setBrush(QColor(255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(pt_widget, 6, 6)
        
        # 显示信息
        painter.setPen(QColor(100, 100, 100))
        font = QFont('Segoe UI', 12)
        painter.setFont(font)
        
        # 图像信息
        status = "√ 已标记" if img_data['marked'] else "× 未标记"
        info = f"图像 {self.current_image_idx + 1}/{len(self.images)}: {img_data['name']} [{status}]"
        painter.drawText(10, 25, info)
        
        if self.mark_mode:
            painter.setPen(QColor(255, 0, 0))
            if len(self.temp_points) == 0:
                painter.drawText(10, 50, "请点击第一个标记点（金锡左侧最下方端点）")
            elif len(self.temp_points) == 1:
                painter.drawText(10, 50, "请点击第二个标记点（金锡右侧最下方端点）")
        
        # 显示导航提示
        painter.setPen(QColor(150, 150, 150))
        if img_data['marked']:
            painter.drawText(self.width() - 300, 25, "← → 切换图像 | 点击绿点拖拽调整位置")
        else:
            painter.drawText(self.width() - 250, 25, "← → 切换图像 | ESC 退出标定")
