"""图像拼接Tab — 标记水平线对齐拼接"""

import cv2
import numpy as np
import os
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                             QFrame, QScrollArea, QLabel, QTableWidget,
                             QTableWidgetItem, QHeaderView, QInputDialog,
                             QMessageBox, QSizePolicy,
                             QSpinBox, QSlider, QListWidget, QListWidgetItem,
                             QAbstractItemView, QSplitter)
from PyQt6.QtCore import Qt, QItemSelection

from ui_components import (confirm_action, create_primary_button,
                           create_secondary_button, create_success_button,
                           create_danger_button, create_step_title,
                           create_info_label, create_success_label,
                           create_slider_with_label, create_checkbox,
                           create_groupbox, CollapsibleSection)
from ui_dialogs import show_info, show_toast, show_warning
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
        self.canvas.empty_import.connect(self.import_images)
        lo.addWidget(self.canvas, 1)
        
        self._connect()
        self._refresh()
    
    def _build_sidebar(self):
        """构建侧边栏"""
        sidebar = QFrame()
        sidebar.setObjectName("SidebarCard")
        sidebar.setMinimumWidth(280)
        sidebar.setMaximumWidth(420)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(14)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # ---- 导入图像 ----
        v.addWidget(create_step_title("1. 导入图像"))
        
        import_row = QHBoxLayout()
        btn_import = create_primary_button("导入图片", self.import_images)
        btn_import_dir = create_secondary_button("导入文件夹", self.import_directory)
        import_row.addWidget(btn_import)
        import_row.addWidget(btn_import_dir)
        v.addLayout(import_row)
        
        self.lbl_image_count = create_info_label("已导入：0 张")
        v.addWidget(self.lbl_image_count)
        
        # 图像列表
        self.image_list = QListWidget()
        self.image_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.image_list.setMaximumHeight(120)
        self.image_list.currentRowChanged.connect(self.on_image_selected)
        v.addWidget(self.image_list)
        
        list_row = QHBoxLayout()
        btn_remove_selected = create_danger_button("移除", self.remove_selected)
        btn_clear_all = create_danger_button("清空", self.confirm_clear_all)
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
        
        btn_save = create_secondary_button("保存拼接图（并复制）", self.save_stitched)
        btn_save.setToolTip("导出 PNG/TIF 到磁盘，同时把拼接图放到剪贴板，"
                            "可直接 Ctrl+V 粘到 PPT/Word")
        v.addWidget(btn_save)
        btn_copy = create_secondary_button("仅复制到剪贴板", self.copy_to_clipboard)
        btn_copy.setToolTip("不落盘，直接把拼接图复制到剪贴板（Ctrl+V 即可粘贴）")
        v.addWidget(btn_copy)
        
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
        self.lbl_image_count.setText(f"已导入：{len(self.images)} 张")
        
        marked_count = sum(1 for img in self.canvas.images if img['marked'])
        total = len(self.canvas.images)
        self.lbl_mark_status.setText(f"已标记：{marked_count}/{total} 张")
        
        if self.canvas.stitched_image is not None:
            h, w = self.canvas.stitched_image.shape[:2]
            self.lbl_stitch_status.setText(f"拼接完成：{w} x {h} 像素")
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
            show_info(self, "提示", "所选文件夹中没有找到图像文件")
            return
        
        self._load_images(paths)
    
    def add_images(self, paths):
        """批量追加图片（拖拽导入与外部调用共用）。"""
        paths = [path for path in paths if os.path.isfile(path)]
        if paths:
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
            show_toast(self, f"已导入 {loaded} 张图像")
    
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
    
    def confirm_clear_all(self):
        if not self.images:
            return False
        if not confirm_action(
                self, '清空已导入图像',
                '将移除列表中的全部图像及当前拼接结果。\n此操作不可撤销。'):
            return False
        self.clear_all()
        return True

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
            show_info(self, "提示", "请先导入图像")
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
            show_toast(self, "所有图像已标记完成")
            self.canvas.stop_mark_mode()
            self.btn_mark.setText("开始标定")
            self.btn_mark.setChecked(False)
    
    # ========== 拼接 ==========
    
    def stitch_images(self):
        """开始拼接"""
        if not self.canvas.images:
            show_info(self, "提示", "请先导入图像")
            return
        
        marked_count = sum(1 for img in self.canvas.images if img['marked'])
        if marked_count < 2:
            show_info(self, "提示", "请至少标记两张图像")
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
            show_toast(self, "拼接完成")
    
    def on_stitch_completed(self):
        """拼接完成"""
        self._refresh()
    
    # ========== 发送到分析 ==========
    
    def send_to_analysis(self):
        """发送到空洞分析"""
        if self.canvas.stitched_image is None:
            show_info(self, "提示", "请先完成拼接")
            return
        
        main_window = self.window()
        if hasattr(main_window, 'set_stitching_result'):
            main_window.set_stitching_result(self.canvas.stitched_image, None)
            main_window.tab_widget.setCurrentWidget(main_window.analysis_tab)
            show_toast(self, "已发送到空洞分析模块")
    
    # ========== 导出 ==========
    
    def save_stitched(self):
        """保存拼接图"""
        if self.canvas.stitched_image is None:
            show_info(self, "提示", "请先完成拼接")
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

        # 导出成功 → **顺便复制到剪贴板**（可直接 Ctrl+V 粘到 PPT/Word ✗）
        ok_copy, why = self.copy_to_clipboard(silent=True)
        tip = f"已保存到：{path}"
        tip += ("\n并已复制到剪贴板，可直接 Ctrl+V 粘贴到 PPT/Word √"
                if ok_copy else f"\n（复制到剪贴板失败：{why}）")
        show_info(self, "成功", tip)

    def copy_to_clipboard(self, silent=False):
        """把拼接图复制到系统剪贴板（BGR/灰度 numpy → QImage）

        Returns: (是否成功, 失败原因)
        """
        img = self.canvas.stitched_image
        if img is None:
            if not silent:
                show_info(self, "提示", "请先完成拼接")
            return False, '尚未拼接'
        try:
            import numpy as np
            from PyQt6.QtGui import QImage
            from PyQt6.QtWidgets import QApplication
            a = img
            if a.ndim == 2:                                   # 灰度 → RGB
                a = np.repeat(a[:, :, None], 3, axis=2)
            elif a.shape[2] == 4:                             # BGRA → RGB
                a = a[:, :, :3]
            rgb = np.ascontiguousarray(a[:, :, ::-1])          # BGR → RGB
            h, w = rgb.shape[:2]
            q = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            cb = QApplication.clipboard()
            if cb is None:
                return False, '剪贴板不可用'
            cb.setImage(q)
            if not silent:
                show_info(
                    self, "已复制",
                    f"拼接图（{w}×{h}）已复制到剪贴板，可直接 Ctrl+V 粘贴 √")
            return True, ''
        except Exception as e:
            if not silent:
                show_warning(self, "提示", f"复制到剪贴板失败：{e}")
            return False, f'{type(e).__name__}: {e}'

