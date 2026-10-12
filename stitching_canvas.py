"""图像拼接画布组件 - 支持标记点对齐拼接"""

import cv2
import numpy as np
from PyQt6.QtWidgets import QWidget, QMessageBox
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QRect
from PyQt6.QtGui import QImage, QPainter, QPen, QColor, QBrush, QFont, QCursor


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
        """按标记点对齐并拼接图像
        
        标记规则：
        - 第一张图：标记金锡右端（尾部）
        - 中间图：标记金锡左端（头部）和右端（尾部）
        - 最后一张图：标记金锡左端（头部）
        
        对齐逻辑：前一张图的尾部金锡Y坐标 = 后一张图的头部金锡Y坐标
        """
        if not self.images:
            return None
        
        marked_images = [img for img in self.images if img['marked']]
        if len(marked_images) < 2:
            return None
        
        if progress_callback:
            progress_callback(10, "分析标记点...")
        
        # 提取每张图的关键点Y坐标
        end_ys = []
        start_ys = []
        
        for img_data in marked_images:
            if img_data['line_p1'] is not None and img_data['line_p2'] is not None:
                p1, p2 = img_data['line_p1'], img_data['line_p2']
                if p1.x() < p2.x():
                    start_ys.append(p1.y())
                    end_ys.append(p2.y())
                else:
                    start_ys.append(p2.y())
                    end_ys.append(p1.y())
            elif img_data['line_p1'] is not None:
                p = img_data['line_p1']
                img_idx = marked_images.index(img_data)
                if img_idx == 0:
                    end_ys.append(p.y())
                    start_ys.append(p.y())
                else:
                    start_ys.append(p.y())
                    end_ys.append(p.y())
        
        if progress_callback:
            progress_callback(30, "计算对齐偏移...")
        
        # 计算每张图的垂直偏移
        positions = [0]
        for i in range(len(marked_images) - 1):
            shift = int(end_ys[i] - start_ys[i + 1])
            positions.append(positions[-1] + shift)
        
        if progress_callback:
            progress_callback(50, "创建画布...")
        
        # 计算画布尺寸
        total_width = sum(img['image'].shape[1] for img in marked_images)
        max_height = max(img['image'].shape[0] for img in marked_images)
        
        min_top = min(positions)
        offset_y = -min_top if min_top < 0 else 0
        total_height = max(positions[i] + marked_images[i]['image'].shape[0] + offset_y 
                          for i in range(len(marked_images))) + 10
        total_height = max(total_height, max_height + 10)
        
        stitched = np.ones((total_height, total_width, 3), dtype=np.uint8) * 255
        
        if progress_callback:
            progress_callback(60, "拼接图像...")
        
        # 逐张放置图像
        x_offset = 0
        for i, img_data in enumerate(marked_images):
            img = img_data['image']
            h, w = img.shape[:2]
            y_pos = positions[i] + offset_y
            
            if len(img.shape) == 3:
                stitched[y_pos:y_pos+h, x_offset:x_offset+w] = img
            else:
                gray = img
                stitched[y_pos:y_pos+h, x_offset:x_offset+w] = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
            
            x_offset += w
            
            if progress_callback:
                pct = 60 + int(35 * (i + 1) / len(marked_images))
                progress_callback(pct, f"放置第 {i+1}/{len(marked_images)} 张图像...")
        
        if progress_callback:
            progress_callback(100, "完成")
        
        self.stitched_image = stitched
        self.fit_in_view()
        self.stitch_completed.emit()
        return stitched
    
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
