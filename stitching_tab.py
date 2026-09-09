"""图像拼接Tab — 标记水平线对齐拼接"""

import cv2
import numpy as np
import os
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                             QFrame, QScrollArea, QLabel, QTableWidget,
                             QTableWidgetItem, QHeaderView, QInputDialog,
                             QMessageBox, QSizePolicy, QGraphicsDropShadowEffect,
                             QSpinBox, QSlider, QListWidget, QListWidgetItem,
                             QAbstractItemView, QSplitter)
from PyQt6.QtCore import Qt, QItemSelection
from PyQt6.QtGui import QColor

from ui_components import (create_primary_button, create_secondary_button,
                           create_success_button, create_danger_button,
                           create_step_title, create_info_label, create_success_label,
                           create_slider_with_label, create_checkbox, create_groupbox,
                           CollapsibleSection)
from stitching_canvas import StitchingCanvas


class StitchingTab(QWidget):
    """图像拼接 Tab"""
    
    def __init__(self):
        super().__init__()
        self.images = []  # 存储导入的图像: {path, image}
        self.init_ui()
    
    def init_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(16)
        
        lo.addWidget(self._build_sidebar())
        
        self.canvas = StitchingCanvas()
        lo.addWidget(self.canvas, 1)
        
        self._connect()
        self._refresh()
    
    def _build_sidebar(self):
        """构建侧边栏"""
        sidebar = QFrame()
        sidebar.setObjectName("SidebarCard")
        sidebar.setMinimumWidth(320)
        sidebar.setMaximumWidth(420)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 25))
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
        
        # ---- 导入图像 ----
        v.addWidget(create_step_title("1. 导入图像"))
        
        import_row = QHBoxLayout()
        btn_import = create_primary_button("导入图片", self.import_images)
        btn_import_dir = create_secondary_button("导入文件夹", self.import_directory)
        import_row.addWidget(btn_import)
        import_row.addWidget(btn_import_dir)
        v.addLayout(import_row)
        
        self.lbl_image_count = create_info_label("已导入: 0 张")
        v.addWidget(self.lbl_image_count)
        
        # 图像列表
        self.image_list = QListWidget()
        self.image_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.image_list.setMaximumHeight(120)
        self.image_list.currentRowChanged.connect(self.on_image_selected)
        v.addWidget(self.image_list)
        
        list_row = QHBoxLayout()
        btn_remove_selected = create_danger_button("移除", self.remove_selected)
        btn_clear_all = create_danger_button("清空", self.clear_all)
        list_row.addWidget(btn_remove_selected)
        list_row.addWidget(btn_clear_all)
        v.addLayout(list_row)
        
        # ---- 标记水平线 ----
        v.addWidget(create_step_title("2. 标记金锡水平线"))
        
        self.btn_mark = create_primary_button("开始标定", self.toggle_mark_mode)
        v.addWidget(self.btn_mark)
        
        self.lbl_mark_status = create_info_label("点击「开始标定」后，在图上点击两点标记金锡位置")
        v.addWidget(self.lbl_mark_status)
        
        # ---- 拼接 ----
        v.addWidget(create_step_title("3. 拼接图像"))
        
        btn_stitch = create_success_button("开始拼接", self.stitch_images)
        v.addWidget(btn_stitch)
        
        self.lbl_stitch_status = create_info_label("")
        v.addWidget(self.lbl_stitch_status)
        
        btn_analyze = create_primary_button("发送到空洞分析", self.send_to_analysis)
        btn_analyze.setEnabled(False)
        self.btn_analyze = btn_analyze
        v.addWidget(btn_analyze)
        
        # ---- 导出 ----
        v.addWidget(create_step_title("4. 导出"))
        
        btn_save = create_secondary_button("保存拼接图", self.save_stitched)
        v.addWidget(btn_save)
        
        v.addStretch()
        
        scroll.setWidget(content)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(scroll)
        
        return sidebar
    
    def _connect(self):
        """连接信号"""
        self.canvas.line_marked.connect(self.on_line_marked)
        self.canvas.stitch_completed.connect(self.on_stitch_completed)
    
    def _refresh(self):
        """刷新界面状态"""
        self.lbl_image_count.setText(f"已导入: {len(self.images)} 张")
        
        marked_count = sum(1 for img in self.canvas.images if img['marked'])
        total = len(self.canvas.images)
        self.lbl_mark_status.setText(f"已标记: {marked_count}/{total} 张")
        
        if self.canvas.stitched_image is not None:
            h, w = self.canvas.stitched_image.shape[:2]
            self.lbl_stitch_status.setText(f"拼接完成: {w} x {h} 像素")
            self.btn_analyze.setEnabled(True)
        else:
            self.lbl_stitch_status.setText("")
            self.btn_analyze.setEnabled(False)
    
    # ========== 图像导入 ==========
    
    def import_images(self):
        """导入多张图像"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图像文件", "",
            "图像文件 (*.tif *.tiff *.png *.jpg *.jpeg *.bmp);;TIF文件 (*.tif *.tiff);;所有文件 (*)")
        
        if not paths:
            return
        
        self._load_images(paths)
    
    def import_directory(self):
        """导入整个文件夹的图像"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择图像文件夹")
        if not dir_path:
            return
        
        extensions = {'.tif', '.tiff', '.png', '.jpg', '.jpeg', '.bmp'}
        
        paths = []
        for f in sorted(os.listdir(dir_path)):
            ext = os.path.splitext(f)[1].lower()
            if ext in extensions:
                paths.append(os.path.join(dir_path, f))
        
        if not paths:
            QMessageBox.information(self, "提示", "所选文件夹中没有找到图像文件")
            return
        
        self._load_images(paths)
    
    def _load_images(self, paths):
        """加载图像列表"""
        loaded = 0
        for path in paths:
            if any(img['path'] == path for img in self.images):
                continue
            
            img = self._read_image(path)
            if img is not None:
                self.images.append({
                    'path': path,
                    'name': os.path.basename(path),
                    'image': img
                })
                self.image_list.addItem(os.path.basename(path))
                loaded += 1
        
        if loaded > 0:
            self.canvas.set_images(self.images)
            self._refresh()
            QMessageBox.information(self, "成功", f"成功导入 {loaded} 张图像")
    
    def _read_image(self, path):
        """读取图像文件（支持TIF）"""
        ext = os.path.splitext(path)[1].lower()
        
        if ext in {'.tif', '.tiff'}:
            try:
                import tifffile
                img = tifffile.imread(path)
                
                if len(img.shape) == 3:
                    if img.shape[2] == 3:
                        if img.dtype != np.uint8:
                            img = (img / img.max() * 255).astype(np.uint8)
                        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                    elif img.shape[2] == 4:
                        if img.dtype != np.uint8:
                            img = (img / img.max() * 255).astype(np.uint8)
                        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
                    elif img.shape[0] == 3:
                        if img.dtype != np.uint8:
                            img = (img / img.max() * 255).astype(np.uint8)
                        img = np.transpose(img, (1, 2, 0))
                        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                elif len(img.shape) == 2:
                    if img.dtype != np.uint8:
                        img = (img / img.max() * 255).astype(np.uint8)
                
                return img
            except Exception as e:
                print(f"tifffile 读取失败: {e}")
                img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if img is not None:
                    if img.dtype != np.uint8:
                        img = (img / img.max() * 255).astype(np.uint8)
                    return img
                return None
        
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is not None:
            if img.dtype != np.uint8:
                img = (img / img.max() * 255).astype(np.uint8)
        return img
    
    def remove_selected(self):
        """移除选中的图像"""
        row = self.image_list.currentRow()
        if row < 0:
            return
        
        self.image_list.takeItem(row)
        del self.images[row]
        self.canvas.set_images(self.images)
        self._refresh()
    
    def clear_all(self):
        """清空所有图像"""
        self.images.clear()
        self.image_list.clear()
        self.canvas.images.clear()
        self.canvas.stitched_image = None
        self.canvas.update()
        self._refresh()
    
    def on_image_selected(self, row):
        """图像列表选中改变"""
        if row >= 0:
            self.canvas.set_current_image(row)
    
    # ========== 标记水平线 ==========
    
    def toggle_mark_mode(self):
        """切换标定模式"""
        if not self.canvas.images:
            QMessageBox.information(self, "提示", "请先导入图像")
            return
        
        if self.canvas.mark_mode:
            # 退出标定模式
            self.canvas.stop_mark_mode()
            self.btn_mark.setText("开始标定")
            self.btn_mark.setChecked(False)
        else:
            # 进入标定模式
            self.canvas.start_mark_mode()
            self.btn_mark.setText("结束标定")
            self.btn_mark.setChecked(True)
    
    def on_line_marked(self, image_idx, p1, p2):
        """标记线完成"""
        self._refresh()
        # 自动切换到下一张图
        if not self.canvas.next_image():
            # 如果已经是最后一张，提示完成
            QMessageBox.information(self, "完成", "所有图像已标记完成！")
            self.canvas.stop_mark_mode()
            self.btn_mark.setText("开始标定")
            self.btn_mark.setChecked(False)
    
    # ========== 拼接 ==========
    
    def stitch_images(self):
        """开始拼接"""
        if not self.canvas.images:
            QMessageBox.information(self, "提示", "请先导入图像")
            return
        
        marked_count = sum(1 for img in self.canvas.images if img['marked'])
        if marked_count < 2:
            QMessageBox.information(self, "提示", "请至少标记两张图像")
            return
        
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        
        progress = QProgressDialog("正在拼接图像...", "取消", 0, 100, self)
        progress.setWindowTitle("拼接中")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        
        def update_progress(value, text):
            progress.setValue(value)
            progress.setLabelText(text)
            QApplication.processEvents()
        
        result = self.canvas.stitch_images(progress_callback=update_progress)
        
        progress.setValue(100)
        progress.close()
        
        if result is not None:
            self._refresh()
            QMessageBox.information(self, "成功", "拼接完成")
    
    def on_stitch_completed(self):
        """拼接完成"""
        self._refresh()
    
    # ========== 发送到分析 ==========
    
    def send_to_analysis(self):
        """发送到空洞分析"""
        if self.canvas.stitched_image is None:
            QMessageBox.information(self, "提示", "请先完成拼接")
            return
        
        main_window = self.window()
        if hasattr(main_window, 'set_stitching_result'):
            main_window.set_stitching_result(self.canvas.stitched_image, None)
            main_window.tab_widget.setCurrentIndex(0)
            QMessageBox.information(self, "成功", "已发送到空洞分析模块")
    
    # ========== 导出 ==========
    
    def save_stitched(self):
        """保存拼接图"""
        if self.canvas.stitched_image is None:
            QMessageBox.information(self, "提示", "请先完成拼接")
            return
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        path, _ = QFileDialog.getSaveFileName(
            self, "保存拼接图", f"stitched_{timestamp}.png",
            "PNG文件 (*.png);;TIF文件 (*.tif *.tiff);;所有文件 (*)")
        
        if not path:
            return
        
        ext = os.path.splitext(path)[1].lower()
        if ext in {'.tif', '.tiff'}:
            import tifffile
            tifffile.imwrite(path, self.canvas.stitched_image)
        else:
            cv2.imencode('.png', self.canvas.stitched_image)[1].tofile(path)
        
        QMessageBox.information(self, "成功", f"已保存到: {path}")
