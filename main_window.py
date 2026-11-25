"""主窗口类"""

import copy
import logging
import os
import sys

import cv2
import numpy as np
from datetime import datetime

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QFileDialog, QTableWidget, QTableWidgetItem,
                             QHeaderView, QDialog, QInputDialog, QFrame,
                             QMessageBox, QScrollArea, QSizePolicy,
                             QLabel, QSlider, QPushButton, QButtonGroup,
                             QTabWidget, QSpinBox, QDoubleSpinBox, QSplitter,
                             QComboBox, QMenu)
from PyQt6.QtCore import QEvent, QPoint, Qt, QSettings, QTimer, QUrl
from PyQt6.QtGui import (QDesktopServices, QIcon, QImage,
                         QKeySequence, QPixmap, QShortcut)
from PyQt6.QtWidgets import QApplication

from app_paths import app_dir, resource_path
from csv_export import write_csv
from styles import STYLESHEET, DIALOG_STYLESHEET
from app_version import APP_VERSION
from help_dialogs import AboutDialog, MarkdownDialog
from ui_dialogs import show_info, show_toast, show_warning
from update_check import UpdateChecker, should_show_update
from canvas import ImageCanvas
from image import (extract_threshold_contour, contour_to_polygon,
                              polygon_to_mask, build_snap_edge_mask, detect_voids,
                              is_void_in_roi,calculate_roundness, detect_voids_local,create_local_region_around_void,
                              otsu_threshold)

from ui_components import (align_right, create_primary_button,
                           create_secondary_button, create_success_button,
                           create_danger_button, create_step_title,
                           create_info_label, create_success_label,
                           create_slider_with_label, create_checkbox,
                           create_groupbox, CollapsibleSection, TitleBar)
# 距离测量已并入 ROI Tab，原独立 Tab 暂停挂载。
# from measure_tab import MeasureTab
from shear_tab import ShearTab
from counting_tab import CountingTab
from area_tab import DefectAreaTab
from stitching_tab import StitchingTab
from teach_batch_tab import TeachBatchTab
from recipe import (list_recipes, load_recipe, save_recipe,
                    delete_recipe, build_recipe)


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self._manual_check = False
        self.setWindowTitle(f"Aurascope {APP_VERSION}")
        # 去掉系统标题栏：标题、菜单、最小化/最大化/关闭统一由自绘 TitleBar 承担
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.resize(1000, 600)
        self.setAcceptDrops(True)

        # 设置窗口图标（兼容 PyInstaller 单文件解包目录）
        self.setWindowIcon(QIcon(resource_path('logo_1.ico')))

        # 核心数据
        self.pixel_scale = 0
        self.roi_mask = None
        self.solder_area_px = 0
        self.voids_data = []
        self.roi_polygon_pts = []
        self.snap_edge_mask = None
        self.void_edit_mode = 'none'
        self.roi_erosion_px = 3

        # 检测配方
        self.current_recipe_name = None

        # 一键自动 ROI（框选完成后自动走 Otsu + 轮廓提取）
        self.auto_roi_pending = False

        self.init_ui()

        self.update_checker = UpdateChecker(self)
        self.update_checker.update_found.connect(self._on_update_found)
        self.update_checker.check_finished.connect(self._on_check_finished)
        if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            QTimer.singleShot(1500, self.update_checker.check)

        # 统一修正下拉弹层（弹层是独立弹出窗口 ✗ 全局 QSS 命中不了 ✗）
        from ui_components import style_combo_popups
        style_combo_popups(self)

        self._restore_window_state()

    def init_ui(self):
        """初始化UI"""
        self.tab_widget = QTabWidget()
        central = QWidget()
        self._root_layout = QVBoxLayout(central)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self._root_layout.addWidget(self.tab_widget)
        self.setCentralWidget(central)

        # Tab 1: ROI（缺陷面积，默认首页）
        self.area_tab = DefectAreaTab()
        self.tab_widget.addTab(self.area_tab, 'ROI')

        # Tab 2: 空洞分析
        self.analysis_tab = analysis_tab = QWidget()
        analysis_layout = QHBoxLayout(analysis_tab)
        analysis_layout.setContentsMargins(16, 16, 16, 16)
        analysis_layout.setSpacing(0)

        self.analysis_splitter = splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = self._create_sidebar()
        splitter.addWidget(sidebar)
        self.canvas = ImageCanvas()
        self.canvas.empty_import.connect(self.load_image)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 640])
        analysis_layout.addWidget(splitter)

        self._connect_signals()

        self.tab_widget.addTab(analysis_tab, "空洞分析")

        # Tab 3: 示教与批量检测
        self.teach_batch_tab = TeachBatchTab()
        self.tab_widget.addTab(self.teach_batch_tab, "示教/批量")

        # Tab 4: 剪切力计算
        self.shear_tab = ShearTab()
        self.tab_widget.addTab(self.shear_tab, "剪切力计算")

        # Tab 5: 物料计数
        self.counting_tab = CountingTab()
        self.tab_widget.addTab(self.counting_tab, "物料计数")

        # Tab 6: 图像拼接
        self.stitching_tab = StitchingTab()
        self.tab_widget.addTab(self.stitching_tab, "图像拼接")

        self.title_bar = self._build_title_bar()
        self._root_layout.insertWidget(0, self.title_bar)
        self._build_menu()
        self.tab_widget.tabBar().hide()
        self._root_layout.insertWidget(1, self._build_app_header())

        # 初始禁用状态
        self.toggle_steps(False)
        
        # 撤销支持
        self.undo_stack = []
        self.undo_limit = 30

        # 面积过滤
        self.void_min_area = 1
        self.void_max_area = None  # None = 无上限

        # 增强检测
        self.enhanced_enabled = True
        self.enhanced_clahe = True
        self.enhanced_clahe_clip = 2.0
        self.enhanced_morph = True
        self.enhanced_min_roundness = 0.0
        self.enhanced_edge_verify = False

        # Ctrl+Z 快捷键
        shortcut_undo = QShortcut(QKeySequence('Ctrl+Z'), self)
        shortcut_undo.activated.connect(self.on_undo)

        # 新增：局部阈值调节相关
        self.local_regions = []  # 存储局部矩形区域及其阈值 (x, y, w, h, thresh)
        self.local_brush_regions = []  # 存储局部圆形笔刷区域 {cx, cy, radius, thresh}
        self.selected_void_for_local = None  # 当前选中用于局部调节的空洞ID
        self.local_brush_mode = False
        self.brush_radius = 60

    # ========== 标题栏 / 应用页头 / 菜单 ==========
    def _build_title_bar(self):
        """自绘标题栏：品牌 + 文件/帮助 + 最小化/最大化/关闭。"""
        return TitleBar(self, 'Aurascope', f'v{APP_VERSION}',
                        QPixmap(resource_path('logo.png')))

    def _build_app_header(self):
        """模块导航条：与标题栏形成「窗口 chrome → 功能模块」两层。"""
        header = QFrame()
        header.setObjectName('AppHeader')
        header.setFixedHeight(56)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)

        self.module_group = QButtonGroup(self)
        self.module_group.setExclusive(True)
        self.module_buttons = []
        for index in range(self.tab_widget.count()):
            button = QPushButton(self.tab_widget.tabText(index).strip())
            button.setObjectName('ModuleTab')
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(button.text())
            button.clicked.connect(
                lambda _=False, i=index: self.tab_widget.setCurrentIndex(i))
            self.module_group.addButton(button, index)
            self.module_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch()
        self.tab_widget.currentChanged.connect(self._sync_module_tabs)
        self._sync_module_tabs(self.tab_widget.currentIndex())
        return header

    def _sync_module_tabs(self, index):
        for i, button in enumerate(getattr(self, 'module_buttons', [])):
            button.setChecked(i == index)

    # ========== 菜单 / 最近打开 ==========
    def _build_menu(self):
        """菜单挂在自绘标题栏上，不再占用系统菜单栏。"""
        file_menu = QMenu(self)
        file_menu.addAction('打开图片…', self.open_image_in_roi)
        self.recent_menu = file_menu.addMenu('最近打开')
        file_menu.addSeparator()
        file_menu.addAction('退出', self.close)

        help_menu = QMenu(self)
        help_menu.addAction('使用说明', lambda: self._show_doc('使用说明', '说明书.md'))
        help_menu.addAction('更新日志', lambda: self._show_doc('更新日志', 'CHANGELOG.md'))
        help_menu.addSeparator()
        help_menu.addAction('检查更新…', self.check_updates_manual)
        help_menu.addAction('关于 Aurascope', self._show_about)

        self.title_bar.add_menu('文件', file_menu)
        self.title_bar.add_menu('帮助', help_menu)
        self._rebuild_recent_menu()

    def _show_doc(self, title, filename):
        MarkdownDialog(title, filename, self).exec()

    def _show_about(self):
        AboutDialog(self).exec()

    # ========== 无边框窗口：边缘缩放 / 最大化状态同步 ==========
    def changeEvent(self, event):
        if (event.type() == QEvent.Type.WindowStateChange
                and getattr(self, 'title_bar', None) is not None):
            self.title_bar.set_maximized(self.isMaximized())
        super().changeEvent(event)

    def nativeEvent(self, event_type, message):
        """无边框窗口的八向缩放：把四周 6px 交给系统 WM_NCHITTEST。

        注意：这里绝不能 `return super().nativeEvent(...)`——
        PyQt6 下基类返回的 sip.voidptr 会被重复处理，直接 access violation（已踩过）。
        """
        if (sys.platform == 'win32' and not self.isMaximized()
                and event_type == b'windows_generic_MSG'):
            import ctypes
            import ctypes.wintypes
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:
                    hit = self._hit_test(msg.lParam)
                    if hit is not None:
                        return True, hit
            except Exception:
                logging.getLogger('Aurascope').debug(
                    'WM_NCHITTEST 处理失败', exc_info=True)
        return False, 0

    def _hit_test(self, lparam):
        """WM_NCHITTEST 坐标是物理像素，转回窗口内逻辑坐标再判边界。"""
        import ctypes
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        screen = self.screen()
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        pos = self.mapFromGlobal(QPoint(int(round(x / ratio)),
                                        int(round(y / ratio))))
        border = 6
        left = pos.x() < border
        right = pos.x() >= self.width() - border
        top = pos.y() < border
        bottom = pos.y() >= self.height() - border
        if top and left:
            return 13   # HTTOPLEFT
        if top and right:
            return 14   # HTTOPRIGHT
        if bottom and left:
            return 16   # HTBOTTOMLEFT
        if bottom and right:
            return 17   # HTBOTTOMRIGHT
        if left:
            return 10   # HTLEFT
        if right:
            return 11   # HTRIGHT
        if top:
            return 12   # HTTOP
        if bottom:
            return 15   # HTBOTTOM
        return None

    def open_image_in_roi(self):
        self.tab_widget.setCurrentWidget(self.area_tab)
        self.area_tab.load_image()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """拖入图片 → ROI；多张图片 → 拼接；文件夹 → 批次检测。"""
        urls = [url.toLocalFile() for url in event.mimeData().urls()
                if url.isLocalFile()]
        if not urls:
            return
        exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')
        folders = [path for path in urls if os.path.isdir(path)]
        images = [path for path in urls
                  if os.path.isfile(path) and path.lower().endswith(exts)]
        if folders:
            folder = folders[0]
            self.tab_widget.setCurrentWidget(self.teach_batch_tab)
            if self.teach_batch_tab.load_folder(folder):
                show_toast(self, f'已载入批次：{os.path.basename(os.path.normpath(folder))}')
            event.acceptProposedAction()
            return
        if not images:
            show_warning(self, '无法导入', '请拖入图片文件（PNG/JPG/BMP/TIF）或批次文件夹。')
            return
        if len(images) == 1:
            self.tab_widget.setCurrentWidget(self.area_tab)
            self.area_tab.load_image(images[0])
        else:
            self.tab_widget.setCurrentWidget(self.stitching_tab)
            self.stitching_tab.add_images(images)
        event.acceptProposedAction()

    @staticmethod
    def _recent_list(settings, key):
        raw = settings.value(key, [])
        if isinstance(raw, str):
            return [raw] if raw else []
        return [str(value) for value in (raw or [])]

    def _push_recent(self, key, value, limit):
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
            return
        value = os.path.abspath(value)
        settings = QSettings('Aurascope', 'Aurascope')
        items = [item for item in self._recent_list(settings, key)
                 if os.path.normcase(item) != os.path.normcase(value)]
        items.insert(0, value)
        settings.setValue(key, items[:limit])
        self._rebuild_recent_menu()

    def remember_recent_image(self, path):
        self._push_recent('recent/images', path, 8)

    def remember_recent_batch(self, folder):
        self._push_recent('recent/batches', folder, 5)

    def _rebuild_recent_menu(self):
        menu = getattr(self, 'recent_menu', None)
        if menu is None:
            return
        menu.clear()
        settings = QSettings('Aurascope', 'Aurascope')
        images = self._recent_list(settings, 'recent/images')
        batches = self._recent_list(settings, 'recent/batches')
        if not images and not batches:
            action = menu.addAction('（暂无）')
            action.setEnabled(False)
            return
        for path in images:
            action = menu.addAction(os.path.basename(path))
            action.setToolTip(path)
            action.triggered.connect(
                lambda _=False, p=path: self._open_recent_image(p))
        if images and batches:
            menu.addSeparator()
        for folder in batches:
            action = menu.addAction(
                f'批次：{os.path.basename(os.path.normpath(folder))}')
            action.setToolTip(folder)
            action.triggered.connect(
                lambda _=False, p=folder: self._open_recent_batch(p))

    def _open_recent_image(self, path):
        if not os.path.isfile(path):
            show_warning(self, '打开失败', f'文件不存在：\n{path}')
            return
        self.tab_widget.setCurrentWidget(self.area_tab)
        if not self.area_tab.load_image(path):
            show_warning(self, '打开失败', f'无法打开图片：\n{path}')

    def _open_recent_batch(self, folder):
        self.tab_widget.setCurrentWidget(self.teach_batch_tab)
        if not self.teach_batch_tab.load_folder(folder):
            show_warning(self, '打开失败', f'批次文件夹不可用：\n{folder}')

    # ========== 窗口状态 ==========
    def _splitter_map(self):
        return {
            'analysis': getattr(self, 'analysis_splitter', None),
            'area': getattr(self.area_tab, 'splitter', None),
            'teach_h': getattr(self.teach_batch_tab, 'hsplit', None),
            'teach_v': getattr(self.teach_batch_tab, 'vsplit', None),
        }

    def _restore_window_state(self):
        settings = QSettings('Aurascope', 'Aurascope')
        geometry = settings.value('ui/geometry')
        if geometry is not None:
            self.restoreGeometry(geometry)
        window_state = settings.value('ui/window_state')
        if window_state is not None:
            self.restoreState(window_state)
        try:
            index = int(settings.value('ui/tab', 0))
        except (TypeError, ValueError):
            index = 0
        if 0 <= index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(index)
        for name, widget in self._splitter_map().items():
            if widget is None:
                continue
            data = settings.value(f'ui/splitter/{name}')
            if data is not None:
                widget.restoreState(data)

    def closeEvent(self, event):
        if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            settings = QSettings('Aurascope', 'Aurascope')
            settings.setValue('ui/geometry', self.saveGeometry())
            settings.setValue('ui/window_state', self.saveState())
            settings.setValue('ui/tab', self.tab_widget.currentIndex())
            for name, widget in self._splitter_map().items():
                if widget is not None:
                    settings.setValue(f'ui/splitter/{name}', widget.saveState())
            logging.getLogger('Aurascope').info('窗口状态已保存')
        super().closeEvent(event)

    def _create_sidebar(self):
        """创建侧边栏"""
        sidebar = QFrame()
        sidebar.setObjectName("SidebarCard")
        sidebar.setMinimumWidth(280)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # 扁平风格：层次靠 1px 描边 + 底色差，不加投影（投影会在分隔条旁形成脏灰竖带）

        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 内容容器
        sb_content = QWidget()
        sb_layout = QVBoxLayout(sb_content)
        sb_layout.setContentsMargins(16, 16, 16, 16)
        sb_layout.setSpacing(14)
        sb_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 组装
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(scroll_area)
        scroll_area.setWidget(sb_content)

        # 添加组件
        self._add_sidebar_components(sb_layout)

        return sidebar

    def _add_sidebar_components(self, layout):
        """添加侧边栏组件"""
        # 上传
        btn_load = create_primary_button("点击上传 SEM 图片", self.load_image)
        layout.addWidget(btn_load)

        # ── 标定 ──
        layout.addWidget(create_step_title("比例尺标定"))
        self.btn_calib = create_secondary_button("划线标定", self.start_calibration, checkable=True)
        self.btn_calib.setEnabled(False)
        layout.addWidget(self.btn_calib)
        self.lbl_scale_info = create_info_label("未标定！")
        layout.addWidget(self.lbl_scale_info)

        # ── 缺陷区域定义 ──
        layout.addWidget(create_step_title("缺陷区域定义"))
        # tool_row = QHBoxLayout()
        self.btn_poly = create_secondary_button("多边形框选", checkable=True)
        self.btn_rect = create_secondary_button("矩形框+阈值", checkable=True)
        self.btn_poly.clicked.connect(lambda: self.set_tool_mode('poly'))
        self.btn_rect.clicked.connect(lambda: self.set_tool_mode('rect'))
        # tool_row.addWidget(self.btn_poly)
        # tool_row.addWidget(self.btn_rect)
        # layout.addLayout(tool_row)

        self.grp_layer_thresh = create_groupbox("调节缺陷区域识别阈值")
        self._setup_layer_threshold_group()
        layout.addWidget(self.grp_layer_thresh)
        self.lbl_layer_info = create_success_label()
        layout.addWidget(self.lbl_layer_info)

        # ── 缺陷识别 ──
        layout.addWidget(create_step_title("缺陷识别"))
        self.grp_void = create_groupbox("空洞检测设置")
        self._setup_void_detection_group()
        layout.addWidget(self.grp_void)

        # ── 结果 ──
        self.result_box = QLabel("等待计算...")
        self.result_box.setObjectName("ResultBox")
        self.result_box.setWordWrap(True)
        layout.addWidget(self.result_box)

        # ── 操作 ──
        action_row = QHBoxLayout()
        btn_screenshot = create_secondary_button("截图复制", self.save_screenshot)
        btn_detail = create_secondary_button("导出数据", self.show_detail_table)
        action_row.addWidget(btn_screenshot)
        action_row.addWidget(btn_detail)
        layout.addLayout(action_row)

        layout.addStretch()

    def _setup_layer_threshold_group(self):
        """设置缺陷区域识别阈值组"""
        vbox = QVBoxLayout()

        # 区域阈值标题行 + 自动 Otsu
        layer_header = QHBoxLayout()
        layer_header.addWidget(QLabel("区域阈值："))
        layer_header.addStretch()
        btn_layer_otsu = create_secondary_button("自动 (Otsu)", self.auto_layer_otsu)
        btn_layer_otsu.setToolTip("对当前矩形框选区域自动计算识别阈值")
        layer_header.addWidget(btn_layer_otsu)
        vbox.addLayout(layer_header)

        self.slider_layer, self.lbl_layer_val = create_slider_with_label(
            0, 255, 100, self.update_layer_preview)

        btn_confirm = create_success_button("确认选区", self.confirm_layer_roi)
        btn_reset = create_danger_button("重置/清除选区", self.reset_roi)

        tool_row = QHBoxLayout()
        vbox.addWidget(self.lbl_layer_val)
        vbox.addWidget(self.slider_layer)
        vbox.addLayout(tool_row)
        tool_row.addWidget(self.btn_poly)
        tool_row.addWidget(self.btn_rect)
        vbox.addWidget(btn_confirm)
        vbox.addWidget(btn_reset)

        # 一键自动 ROI
        self.btn_auto_roi = create_primary_button("一键自动 ROI", self.start_auto_roi)
        self.btn_auto_roi.setToolTip("在图上拖出焊料大致区域，自动提取边界多边形，之后可微调顶点")
        vbox.addWidget(self.btn_auto_roi)
        self.lbl_auto_roi_tip = create_info_label("请在图上拖出焊料大致区域")
        self.lbl_auto_roi_tip.setVisible(False)
        vbox.addWidget(self.lbl_auto_roi_tip)

        # 高级选项
        adv = CollapsibleSection("多边形编辑")
        self.lbl_vertex_val = create_info_label("顶点数：24")
        self.lbl_vertex_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.slider_vertices, _ = create_slider_with_label(
            3, 120, 24, self.on_vertex_count_changed)
        self.chk_snap_edge = create_checkbox("吸附边缘", False, self.toggle_snap_edges)
        self.lbl_edit_tip = create_info_label("双击边新增顶点 · Delete 删除选中")
        self.chk_roi_overlay = create_checkbox("选区绿色蒙版", True, self.toggle_roi_overlay)

        adv.addWidget(self.lbl_vertex_val)
        adv.addWidget(self.slider_vertices)
        adv.addWidget(self.chk_snap_edge)
        adv.addWidget(self.lbl_edit_tip)
        adv.addWidget(self.chk_roi_overlay)
        vbox.addWidget(adv)

        self.grp_layer_thresh.setLayout(vbox)

    def _setup_void_detection_group(self):
        """设置空洞检测组"""
        vbox = QVBoxLayout()

        # 阈值
        thresh_header = QHBoxLayout()
        thresh_header.addWidget(QLabel("识别阈值："))
        thresh_header.addStretch()
        btn_otsu = create_secondary_button("自动 (Otsu)")
        btn_otsu.clicked.connect(self.auto_otsu_threshold)
        thresh_header.addWidget(btn_otsu)
        vbox.addLayout(thresh_header)

        self.slider_void, self.lbl_void_val = create_slider_with_label(
            0, 255, 80, self.calculate_voids)
        vbox.addWidget(self.lbl_void_val)
        vbox.addWidget(self.slider_void)

        # 显示选项
        display_row = QHBoxLayout()
        self.chk_labels = create_checkbox("编号", False, self.toggle_visuals)
        display_row.addWidget(self.chk_labels)
        self.chk_fill = create_checkbox("红色填充", True, self.toggle_visuals)
        display_row.addWidget(self.chk_fill)
        vbox.addLayout(display_row)

        # 面积过滤
        area_row = QHBoxLayout()
        area_row.addWidget(QLabel("面积过滤："))
        self.spin_min_area = QSpinBox()
        self.spin_min_area.setRange(0, 100000)
        self.spin_min_area.setValue(1)
        self.spin_min_area.valueChanged.connect(self.on_area_filter_changed)
        area_row.addWidget(self.spin_min_area, 1)
        area_row.addWidget(QLabel("~"))
        self.spin_max_area = QSpinBox()
        self.spin_max_area.setRange(0, 1000000)
        self.spin_max_area.setValue(0)
        self.spin_max_area.setSpecialValueText("不限")
        self.spin_max_area.valueChanged.connect(self.on_area_filter_changed)
        area_row.addWidget(self.spin_max_area, 1)
        vbox.addLayout(area_row)

        # 编辑按钮
        edit_row = QHBoxLayout()
        self.btn_void_del = create_secondary_button("删除", checkable=True)
        self.btn_void_del.clicked.connect(lambda: self.set_void_edit_mode('delete'))
        edit_row.addWidget(self.btn_void_del)
        self.btn_void_add = create_secondary_button("添加", checkable=True)
        self.btn_void_add.clicked.connect(lambda: self.set_void_edit_mode('add'))
        edit_row.addWidget(self.btn_void_add)
        self.btn_void_undo = create_secondary_button("撤销")
        self.btn_void_undo.clicked.connect(self.on_undo)
        edit_row.addWidget(self.btn_void_undo)
        vbox.addLayout(edit_row)

        self.lbl_add_tip = create_info_label(
            "点击空洞内部 → 局部 Otsu 自动检测\nCtrl+滚轮调阈值偏移 → 双击确认")
        self.lbl_add_tip.setVisible(False)
        vbox.addWidget(self.lbl_add_tip)

        # 高级设置(折叠)
        adv = CollapsibleSection("高级设置")

        erosion_row = QHBoxLayout()
        erosion_row.addWidget(QLabel("边界腐蚀（px）："))
        self.spin_erosion = QSpinBox()
        self.spin_erosion.setRange(0, 20)
        self.spin_erosion.setValue(self.roi_erosion_px)
        self.spin_erosion.setToolTip("将 ROI 边界向内腐蚀，断开边界伪影与空洞的连通")
        self.spin_erosion.valueChanged.connect(self.on_erosion_changed)
        erosion_row.addWidget(self.spin_erosion)
        erosion_row.addStretch()
        adv.addLayout(erosion_row)

        self.chk_enhanced = create_checkbox("启用增强检测", True, self.on_enhanced_toggled)
        adv.addWidget(self.chk_enhanced)

        self.enhanced_widgets = QWidget()
        ew = QVBoxLayout(self.enhanced_widgets)
        ew.setContentsMargins(0, 0, 0, 0)

        self.chk_clahe = create_checkbox("CLAHE 对比度增强", True, self.calculate_voids)
        ew.addWidget(self.chk_clahe)
        clip_row = QHBoxLayout()
        clip_row.addWidget(QLabel("对比度："))
        self.slider_clahe_clip = QSlider(Qt.Orientation.Horizontal)
        self.slider_clahe_clip.setRange(10, 40)
        self.slider_clahe_clip.setValue(20)
        self.slider_clahe_clip.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_clahe_clip.valueChanged.connect(self.calculate_voids)
        clip_row.addWidget(self.slider_clahe_clip)
        self.lbl_clahe_val = QLabel("2.0")
        self.lbl_clahe_val.setFixedWidth(30)
        clip_row.addWidget(self.lbl_clahe_val)
        ew.addLayout(clip_row)

        self.chk_morph = create_checkbox("形态学去噪", True, self.calculate_voids)
        ew.addWidget(self.chk_morph)

        round_row = QHBoxLayout()
        round_row.addWidget(QLabel("圆度过滤："))
        self.spin_roundness = QDoubleSpinBox()
        self.spin_roundness.setRange(0.0, 1.0)
        self.spin_roundness.setSingleStep(0.05)
        self.spin_roundness.setDecimals(2)
        self.spin_roundness.setValue(0.0)
        self.spin_roundness.setSpecialValueText("关闭")
        self.spin_roundness.valueChanged.connect(self.calculate_voids)
        round_row.addWidget(self.spin_roundness)
        ew.addLayout(round_row)

        self.chk_edge = create_checkbox("Canny 边缘验证", False, self.calculate_voids)
        ew.addWidget(self.chk_edge)

        self.enhanced_widgets.setVisible(True)
        adv.addWidget(self.enhanced_widgets)

        self.btn_void_local = create_secondary_button(
            "局部阈值调节", self.toggle_void_selection_mode, checkable=True)
        adv.addWidget(self.btn_void_local)

        self.lbl_local_tip = create_info_label(
            "单击放置 → 滚轮调半径 → 双击确认\nShift+滚轮调阈值 · 右键双击删除")
        adv.addWidget(self.lbl_local_tip)

        btn_restore = create_danger_button("恢复默认设置")
        btn_restore.clicked.connect(self.restore_void_defaults)
        adv.addWidget(btn_restore)

        vbox.addWidget(adv)

        self.grp_void.setLayout(vbox)

    def _connect_signals(self):
        """连接信号"""
        self.canvas.calib_drawn.connect(self.finish_calibration)
        self.canvas.roi_poly_finished.connect(self.finish_poly_roi)
        self.canvas.roi_rect_changed.connect(self.update_layer_preview)
        self.canvas.roi_rect_finished.connect(self.prepare_layer_threshold)
        self.canvas.roi_polygon_edited.connect(self.on_polygon_edited)
        self.canvas.void_delete_at.connect(self.on_void_delete_at)
        self.canvas.void_add_polygon.connect(self.on_void_add_polygon)
        self.canvas.void_selected_for_local.connect(self.on_void_selected_for_local)
        self.canvas.void_local_region_confirmed.connect(self.on_local_region_confirmed)
        self.canvas.void_local_threshold_changed.connect(self.on_local_threshold_changed)
        self.canvas.void_local_region_removed.connect(self.on_local_region_removed)

    def _skipped_update_version(self):
        settings = QSettings('Aurascope', 'Aurascope')
        return settings.value('update/skipped_version', '', str)

    def _on_update_found(self, info):
        if not self._manual_check and not should_show_update(
                info, self._skipped_update_version()):
            return
        self._show_update_dialog(info)

    def check_updates_manual(self):
        """帮助菜单的主动检查：失败/已最新也给出反馈。"""
        self._manual_check = True
        self.update_checker.check(manual=True)

    def _on_check_finished(self, info, error):
        self._manual_check = False
        if error:
            show_warning(self, '检查更新', f'检查更新失败：{error}')
        elif info is None:
            show_info(self, '检查更新', '当前已是最新版本。')

    def _show_update_dialog(self, info):
        notes = (info.get('notes') or '').strip()
        detail = f"发现新版本 {info.get('tag', '')}\n\n{notes}" if notes else \
            f"发现新版本 {info.get('tag', '')}"
        from updater import can_self_update
        asset = info.get('asset') or {}
        can_update = can_self_update() and bool(asset.get('url'))
        box = QMessageBox(self)
        box.setWindowTitle('发现新版本')
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(detail)
        update_btn = None
        if can_update:
            update_btn = box.addButton('下载并更新',
                                       QMessageBox.ButtonRole.AcceptRole)
            update_btn.setObjectName('PrimaryBtn')
        go = box.addButton('前往下载', QMessageBox.ButtonRole.ActionRole)
        skip = box.addButton('忽略本次更新', QMessageBox.ButtonRole.ActionRole)
        later = box.addButton('稍后', QMessageBox.ButtonRole.RejectRole)
        go.setObjectName('SecondaryBtn' if update_btn else 'PrimaryBtn')
        skip.setObjectName('SecondaryBtn')
        later.setObjectName('SecondaryBtn')
        box.exec()
        clicked = box.clickedButton()
        if update_btn is not None and clicked is update_btn:
            self._start_auto_update(info)
        elif clicked is go and info.get('url'):
            QDesktopServices.openUrl(QUrl(info['url']))
        elif clicked is skip:
            QSettings('Aurascope', 'Aurascope').setValue(
                'update/skipped_version', info.get('version'))

    # ========== 应用内自更新 ==========
    def _start_auto_update(self, info):
        """下载发布包并解压；完成后询问是否立即替换并重启。"""
        from PyQt6.QtWidgets import QProgressDialog
        from updater import UpdateDownloader

        asset = info.get('asset') or {}
        progress = QProgressDialog('正在下载更新…', '取消', 0, 100, self)
        progress.setWindowTitle('下载更新')
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        downloader = UpdateDownloader(self)
        self._update_downloader = downloader

        def on_progress(received, total):
            if total > 0:
                progress.setValue(int(received * 100 / total))
            else:
                progress.setLabelText(
                    f'正在下载更新… {received / 1048576:.0f} MB')

        def on_failed(message):
            progress.close()
            downloader.deleteLater()
            self._update_downloader = None
            show_warning(self, '更新失败',
                         f'{message}\n\n可改用「前往下载」手动更新。')

        def on_ready(exe_path):
            progress.close()
            downloader.deleteLater()
            self._update_downloader = None
            self._apply_update(exe_path)

        downloader.progress.connect(on_progress)
        downloader.failed.connect(on_failed)
        downloader.ready.connect(on_ready)
        progress.canceled.connect(downloader.cancel)
        downloader.start(asset['url'], info.get('version'))

    def _apply_update(self, exe_path):
        """退出后由脚本替换安装目录并重启（不需管理员权限）。"""
        from updater import launch_apply

        source_dir = os.path.dirname(exe_path)
        target_dir = app_dir()
        if os.path.normcase(source_dir) == os.path.normcase(target_dir):
            show_info(self, '更新', '当前已经是最新版本。')
            return
        box = QMessageBox(self)
        box.setWindowTitle('更新已就绪')
        box.setIcon(QMessageBox.Icon.Question)
        box.setText('更新包已下载完成。\n\n点击「立即重启更新」会关闭当前程序，'
                    '自动替换文件并重新打开。\n安装目录里的 recipes（示教配方）'
                    '不会被覆盖。')
        now = box.addButton('立即重启更新', QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton('稍后', QMessageBox.ButtonRole.RejectRole)
        now.setObjectName('PrimaryBtn')
        later.setObjectName('SecondaryBtn')
        box.exec()
        if box.clickedButton() is not now:
            show_info(self, '更新',
                      '更新包已保留，下次可从「帮助 → 检查更新」重新下载。')
            return
        try:
            # 用新包内的 exe 名启动：版本改了文件名时也能接上
            launch_apply(source_dir, target_dir, os.path.basename(exe_path))
        except Exception as exc:
            logging.getLogger('Aurascope').exception('启动更新脚本失败')
            show_warning(self, '更新失败', f'无法启动更新脚本：{exc}')
            return
        QApplication.instance().quit()

    def toggle_steps(self, enabled):
        """切换步骤启用状态"""
        self.btn_calib.setEnabled(enabled)
        self.btn_poly.setEnabled(enabled)
        self.btn_rect.setEnabled(enabled)
        self.btn_auto_roi.setEnabled(enabled)
        self.grp_void.setEnabled(enabled)

    # ========== 图片加载 ==========
    def load_image(self):
        """加载图片"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", 
            "图像文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;TIF文件 (*.tif *.tiff);;所有文件 (*)")
        if not path:
            return
        
        img = self._read_image(path)
        if img is None:
            logging.getLogger('Aurascope').warning('图片加载失败：%s', path)
            show_warning(self, "错误", "图片加载失败！请检查文件格式/路径")
            return

        self.canvas.set_image(img)
        self._reset_all_state()
        
        # UI重置
        self.lbl_scale_info.setText("未标定！")
        self.lbl_layer_info.setText("")
        self.result_box.setText("等待计算...")
        self.grp_layer_thresh.setVisible(True)
        self.toggle_steps(True)
        self.btn_poly.setEnabled(False)
        self.btn_rect.setEnabled(False)
        self.btn_auto_roi.setEnabled(False)
        self.grp_void.setEnabled(False)
        
        self.btn_calib.setChecked(False)
        self.btn_poly.setChecked(False)
        self.btn_rect.setChecked(False)
        self.remember_recent_image(path)
        logging.getLogger('Aurascope').info('空洞分析加载图片：%s', path)

    def _read_image(self, path):
        """读取图像文件（支持TIF）"""
        import os
        ext = os.path.splitext(path)[1].lower()
        
        # TIF 文件使用 tifffile 读取
        if ext in {'.tif', '.tiff'}:
            try:
                import tifffile
                img = tifffile.imread(path)
                
                # 处理多通道
                if len(img.shape) == 3:
                    if img.shape[2] == 3:
                        # RGB
                        if img.dtype != np.uint8:
                            img = (img / img.max() * 255).astype(np.uint8)
                        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                    elif img.shape[2] == 4:
                        # RGBA
                        if img.dtype != np.uint8:
                            img = (img / img.max() * 255).astype(np.uint8)
                        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
                    elif img.shape[0] == 3:
                        # CHW 格式
                        if img.dtype != np.uint8:
                            img = (img / img.max() * 255).astype(np.uint8)
                        img = np.transpose(img, (1, 2, 0))
                        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                elif len(img.shape) == 2:
                    # 灰度图
                    if img.dtype != np.uint8:
                        img = (img / img.max() * 255).astype(np.uint8)
                
                return img
            except Exception as e:
                print(f"tifffile 读取失败: {e}")
                # 尝试用 OpenCV 读取
                img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if img is not None:
                    if img.dtype != np.uint8:
                        img = (img / img.max() * 255).astype(np.uint8)
                    return img
                return None
        
        # 其他格式使用 OpenCV
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is not None:
            if img.dtype != np.uint8:
                img = (img / img.max() * 255).astype(np.uint8)
        return img

    def _reset_all_state(self):
        """重置所有状态"""
        self.pixel_scale = 0
        self.roi_mask = None
        self.roi_polygon_pts = []
        self.snap_edge_mask = None
        self.voids_data = []
        self.canvas.overlay_mask = None
        self.canvas.overlay_preview = None
        self.canvas.draw_voids = []
        self.canvas.calib_line = None
        self.canvas.mode = 'none'
        self.set_void_edit_mode('none')
        self.canvas.clear_roi_polygon()
        self.local_regions = []
        self.local_brush_regions = []
        self.canvas.set_local_brush_regions([])
        self.canvas.set_edge_snap_mask(None)
        self.canvas.set_roi_edit_enabled(False)

    def set_stitching_result(self, image, mask):
        """接收图像拼接结果，作为普通图片加载到空洞分析模块"""
        self.canvas.set_image(image)
        self._reset_all_state()
        
        # UI重置（和 load_image 一样）
        self.lbl_scale_info.setText("未标定！")
        self.lbl_layer_info.setText("")
        self.result_box.setText("等待计算...")
        self.grp_layer_thresh.setVisible(True)
        self.toggle_steps(True)
        self.btn_poly.setEnabled(True)
        self.btn_rect.setEnabled(True)
        self.btn_auto_roi.setEnabled(True)
        self.grp_void.setEnabled(False)
        
        self.btn_calib.setChecked(False)
        self.btn_poly.setChecked(False)
        self.btn_rect.setChecked(False)
        
        self.canvas.update()

    # ========== 标定 ==========
    def start_calibration(self):
        """开始标定"""
        self.canvas.mode = 'calibration'
        self.btn_calib.setChecked(True)
        self.btn_poly.setChecked(False)
        self.btn_rect.setChecked(False)
    
    def finish_calibration(self, p1, p2):
        """完成标定"""
        self.canvas.mode = 'none'
        self.btn_calib.setChecked(False)
        
        dist_px = np.sqrt((p1.x() - p2.x())**2 + (p1.y() - p2.y())**2)
        if dist_px < 5:
            show_warning(self, "错误", "标定线太短，请重试")
            return

        dialog = QInputDialog(self)
        dialog.setWindowTitle("标定")
        dialog.setLabelText("输入标尺实际长度 (μm):")
        dialog.setDoubleRange(0.1, 10000)
        dialog.setDoubleStep(0.1)
        dialog.setDoubleValue(50)
        
        try:
            dialog.setWindowIcon(QIcon(r"标尺.png"))
        except:
            pass
        
        if dialog.exec():
            real_len = dialog.doubleValue()
            if real_len > 0:
                self.pixel_scale = dist_px / real_len
                self.lbl_scale_info.setText(f"标定成功：1 μm = {self.pixel_scale:.2f} px")
                self.canvas.calib_line = (p1, p2, f"{real_len} μm")
                self.canvas.update()
                self.btn_poly.setEnabled(True)
                self.btn_rect.setEnabled(True)
                self.btn_auto_roi.setEnabled(True)

    # ========== 焊层定义 ==========
    def set_tool_mode(self, mode):
        """设置工具模式"""
        self.set_void_edit_mode('none')
        self.canvas.mode = mode
        self.canvas.set_roi_edit_enabled(False)
        self.canvas.selected_vertex_idx = -1
        self.canvas.active_edge_idx = -1
        self.canvas.drag_kind = None
        
        self.btn_poly.setChecked(mode == 'poly')
        self.btn_rect.setChecked(mode == 'rect')
        self.btn_calib.setChecked(False)
        
        if mode == 'poly':
            self.canvas.overlay_preview = None
            self.canvas.update()

    def finish_poly_roi(self, points):
        """多边形ROI完成"""
        self.canvas.mode = 'none'
        self.btn_poly.setChecked(False)
        
        h, w = self.canvas.img_cv.shape[:2]
        self.roi_mask = np.zeros((h, w), dtype=np.uint8)
        pts = np.array(points, dtype=np.int32)
        cv2.fillPoly(self.roi_mask, [pts], 255)
        self.roi_polygon_pts = [(float(x), float(y)) for x, y in points]
        self.canvas.set_roi_polygon(self.roi_polygon_pts)
        self.canvas.set_roi_edit_enabled(True)
        self.canvas.set_edge_snap_mask(None)
        
        self.finalize_roi()

    def prepare_layer_threshold(self, rect_tuple):
        """准备矩形阈值调整"""
        # 一键自动 ROI 的框选完成事件：走自动提取流程
        if getattr(self, 'auto_roi_pending', False):
            self._apply_auto_roi(rect_tuple)
            return

        self.grp_layer_thresh.setVisible(True)
        self.canvas.mode = 'rect'
        self.canvas.current_rect = rect_tuple
        self.canvas.set_roi_edit_enabled(False)
        self.canvas.clear_roi_polygon()
        self.canvas.overlay_mask = None
        self.roi_polygon_pts = []
        self.update_layer_preview()

    def update_layer_preview(self):
        """更新焊层预览"""
        if not self.canvas.current_rect:
            return

        val = self.slider_layer.value()
        self.lbl_layer_val.setText(str(val))

        rect_info, local_mask, _ = extract_threshold_contour(
            self.canvas.img_cv, self.canvas.current_rect, val)
        
        if rect_info is None:
            self.canvas.overlay_preview = None
            self.canvas.update()
            return

        x, y, w, h = rect_info
        preview_rgba = np.zeros((h, w, 4), dtype=np.uint8)
        preview_rgba[:, :, 0] = 16
        preview_rgba[:, :, 1] = 185
        preview_rgba[:, :, 2] = 129
        preview_rgba[:, :, 3] = np.where(local_mask > 0, 160, 0)

        self.canvas.overlay_preview = QImage(
            preview_rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        self.canvas.current_rect = rect_info
        self.canvas.update()

    def confirm_layer_roi(self):
        """确认焊层ROI"""
        if not self.canvas.current_rect:
            return

        val = self.slider_layer.value()
        rect_info, local_mask, contour = extract_threshold_contour(
            self.canvas.img_cv, self.canvas.current_rect, val)
        
        if contour is None:
            show_warning(self, '提示', '未检测到有效边界，请调整阈值或重新框选。')
            return

        target_vertices = self.slider_vertices.value()
        polygon = contour_to_polygon(contour, target_vertices)
        
        if len(polygon) < 3:
            show_warning(self, '提示', '边界多边形生成失败。')
            return

        self._apply_polygon_roi(polygon, rect_info, local_mask, layer_thresh=val)

    def _apply_polygon_roi(self, polygon, rect_info, local_mask, layer_thresh=None):
        """应用多边形 ROI（手动确认与一键自动 ROI 共用）"""
        self.roi_polygon_pts = [(float(px), float(py)) for px, py in polygon]
        self.roi_mask = polygon_to_mask(self.roi_polygon_pts, self.canvas.img_cv.shape)
        if rect_info is not None and local_mask is not None:
            self.snap_edge_mask = build_snap_edge_mask(
                rect_info, local_mask, self.canvas.img_cv.shape)
        else:
            self.snap_edge_mask = None

        self.canvas.set_edge_snap_mask(self.snap_edge_mask)
        self.canvas.set_snap_enabled(self.chk_snap_edge.isChecked())
        self.canvas.set_roi_polygon(self.roi_polygon_pts)
        self.canvas.set_roi_edit_enabled(True)

        self.canvas.mode = 'none'
        self.canvas.current_rect = None
        self.canvas.overlay_preview = None
        self.btn_rect.setChecked(False)
        self.btn_poly.setChecked(False)

        if layer_thresh is not None:
            self.slider_layer.setValue(int(layer_thresh))
            self.lbl_layer_val.setText(str(int(layer_thresh)))

        self.finalize_roi()

    # ========== 一键自动 ROI ==========

    def start_auto_roi(self):
        """进入一键自动 ROI 的框选状态"""
        if self.canvas.img_cv is None:
            show_info(self, '提示', '请先上传图片')
            return
        self.auto_roi_pending = True
        self.lbl_auto_roi_tip.setVisible(True)
        self.set_tool_mode('rect')

    def auto_layer_otsu(self):
        """对矩形框选区域自动计算识别阈值"""
        rect = getattr(self.canvas, 'current_rect', None)
        if not rect:
            show_info(self, '提示', '请先用「矩形框+阈值」在图上框选一个区域')
            return
        if self.canvas.img_cv is None:
            return
        if len(self.canvas.img_cv.shape) == 2:
            gray = self.canvas.img_cv
        else:
            gray = cv2.cvtColor(self.canvas.img_cv, cv2.COLOR_BGR2GRAY)
        x, y, w, h = [int(v) for v in rect]
        ih, iw = gray.shape
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(iw, x + w), min(ih, y + h)
        if x2 - x1 < 3 or y2 - y1 < 3:
            return
        thresh = otsu_threshold(gray[y1:y2, x1:x2])
        self.slider_layer.setValue(thresh)   # 触发 update_layer_preview

    def _apply_auto_roi(self, rect_tuple):
        """一键自动 ROI：Otsu 阈值 → 轮廓提取 → 多边形化 → 顶点微调"""
        self.auto_roi_pending = False
        self.lbl_auto_roi_tip.setVisible(False)
        if self.canvas.img_cv is None:
            return

        x, y, w, h = [int(v) for v in rect_tuple]
        ih, iw = self.canvas.img_cv.shape[:2]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(iw, x + w), min(ih, y + h)
        if x2 - x1 < 5 or y2 - y1 < 5:
            show_warning(self, '提示', '框选区域过小，请重新框选')
            return

        if len(self.canvas.img_cv.shape) == 2:
            gray = self.canvas.img_cv
        else:
            gray = cv2.cvtColor(self.canvas.img_cv, cv2.COLOR_BGR2GRAY)
        thresh = otsu_threshold(gray[y1:y2, x1:x2])

        rect_info, local_mask, contour = extract_threshold_contour(
            self.canvas.img_cv, (x, y, w, h), thresh)
        if contour is None:
            self._auto_roi_fallback((x, y, w, h), '未识别到焊层边界，已切回手动模式')
            return

        # 合理性检查：轮廓面积占框选面积的比例，防止框选偏斜导致识别结果无意义
        rect_area = (x2 - x1) * (y2 - y1)
        cnt_area = cv2.contourArea(contour)
        if cnt_area < 0.01 * rect_area or cnt_area > 0.98 * rect_area:
            self._auto_roi_fallback(
                (x, y, w, h),
                '自动识别结果异常（选区占比过小或接近满区），已切回手动模式')
            return

        polygon = contour_to_polygon(contour, self.slider_vertices.value())
        if len(polygon) < 3:
            self._auto_roi_fallback((x, y, w, h), '边界多边形生成失败，已切回手动模式')
            return

        self._apply_polygon_roi(polygon, rect_info, local_mask, layer_thresh=thresh)

    def _auto_roi_fallback(self, rect_tuple, msg):
        """自动识别失败时退回手动阈值模式（保留框选，用户自行调阈值）"""
        show_warning(self, '提示', msg)
        self.prepare_layer_threshold(rect_tuple)

    def on_polygon_edited(self, points):
        """多边形编辑回调"""
        if len(points) < 3:
            return
            
        self.roi_polygon_pts = [(float(x), float(y)) for x, y in points]
        self.roi_mask = polygon_to_mask(self.roi_polygon_pts, self.canvas.img_cv.shape)
        
        if self.roi_mask is None:
            return
            
        # 保存手动添加的空洞
        manual_voids = [v for v in self.voids_data if v.get('manual', False)]
        
        self.finalize_roi()
        
        # 恢复仍在ROI内的手动空洞
        for v in manual_voids:
            if is_void_in_roi(np.array(v['points']), self.roi_mask):
                self.voids_data.append(v)
        
        self._refresh_void_metrics()

    def on_vertex_count_changed(self, value):
        """顶点数量改变"""
        self.lbl_vertex_val.setText(f'Vertices: {value}')
        if self.roi_polygon_pts:
            self.canvas.set_polygon_vertex_count(value)

    def toggle_snap_edges(self, checked):
        """切换边缘吸附"""
        self.canvas.set_snap_enabled(checked)

    def finalize_roi(self):
        """ROI确定后的通用处理"""
        if self.roi_mask is None:
            return
        
        # 生成半透明绿色蒙版
        h, w = self.roi_mask.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[self.roi_mask == 255] = [16, 185, 129, 100]
        
        self.canvas.overlay_mask = QImage(
            rgba.data, w, h, w*4, QImage.Format.Format_RGBA8888).copy()
        
        self.solder_area_px = cv2.countNonZero(self.roi_mask)
        
        if self.pixel_scale > 0:
            area_um = self.solder_area_px / (self.pixel_scale ** 2)
            self.lbl_layer_info.setText(f"焊层面积：{area_um:.0f} μm²")
        else:
            self.lbl_layer_info.setText(f"焊层面积：{self.solder_area_px} 像素（未标定）")
        
        self.grp_void.setEnabled(True)
        self.auto_otsu_threshold()
        self.canvas.update()

    def reset_roi(self):
        """重置ROI"""
        self.set_void_edit_mode('none')
        self.roi_mask = None
        self.roi_polygon_pts = []
        self.snap_edge_mask = None
        self.canvas.overlay_mask = None
        self.canvas.overlay_preview = None
        self.canvas.current_rect = None
        self.canvas.draw_voids = []
        self.canvas.clear_roi_polygon()
        self.canvas.set_edge_snap_mask(None)
        self.canvas.set_roi_edit_enabled(False)
        self.voids_data = []
        self.local_regions = []
        self.local_brush_regions = []
        self.canvas.set_local_brush_regions([])

        self.grp_layer_thresh.setVisible(True)
        self.grp_void.setEnabled(False)
        self.result_box.setText("等待计算...")
        self.lbl_layer_info.setText("")
        self.lbl_void_val.setText(str(self.slider_void.value()))
        self.btn_poly.setChecked(False)
        self.btn_rect.setChecked(False)
        self.canvas.update()

    # ========== 空洞检测 ==========
    def calculate_voids(self):
        """计算空洞"""
        if self.roi_mask is None:
            return
        
        thresh_val = self.slider_void.value()
        self.lbl_void_val.setText(str(thresh_val))
        
        if len(self.canvas.img_cv.shape) == 2:
            gray = self.canvas.img_cv
        else:
            gray = cv2.cvtColor(self.canvas.img_cv, cv2.COLOR_BGR2GRAY)
        
        self.enhanced_clahe = self.chk_clahe.isChecked() if hasattr(self, 'chk_clahe') else True
        self.enhanced_clahe_clip = (self.slider_clahe_clip.value() / 10.0) if hasattr(self, 'slider_clahe_clip') else 2.0
        if hasattr(self, 'lbl_clahe_val'):
            self.lbl_clahe_val.setText(f"{self.enhanced_clahe_clip:.1f}")
        self.enhanced_morph = self.chk_morph.isChecked() if hasattr(self, 'chk_morph') else True
        self.enhanced_min_roundness = self.spin_roundness.value() if hasattr(self, 'spin_roundness') else 0.0
        self.enhanced_edge_verify = self.chk_edge.isChecked() if hasattr(self, 'chk_edge') else False
        self.voids_data = detect_voids(gray, self.roi_mask, thresh_val,
                                       min_area=self.void_min_area,
                                       max_area=self.void_max_area,
                                       enhanced=self.enhanced_enabled,
                                       clahe_enabled=self.enhanced_clahe,
                                       clahe_clip_limit=self.enhanced_clahe_clip,
                                       morph_enabled=self.enhanced_morph,
                                       min_roundness=self.enhanced_min_roundness,
                                       edge_verify=self.enhanced_edge_verify,
                                       roi_erosion_px=self.roi_erosion_px)
        self.canvas.draw_voids = self.voids_data
        self.canvas.update()
        
        total_void_px = sum(v['area_px'] for v in self.voids_data)
        
        if self.solder_area_px > 0:
            rate = (total_void_px / self.solder_area_px) * 100
        else:
            rate = 0
        
        if self.pixel_scale > 0:
            total_area_um = total_void_px / (self.pixel_scale ** 2)
            self.result_box.setText(
                f"空洞数量：{len(self.voids_data)}\n"
                f"空洞总面积：{total_area_um:.2f} μm²\n"
                f"空洞率：{rate:.2f}%"
            )
        else:
            self.result_box.setText(
                f"空洞数量：{len(self.voids_data)}\n"
                f"空洞总面积：{total_void_px} 像素（未标定）\n"
                f"空洞率：{rate:.2f}%"
            )

        self.canvas.void_rate_text = f"空洞率：{rate:.2f}%"

    def on_enhanced_toggled(self):
        """增强检测开关切换"""
        self.enhanced_enabled = self.chk_enhanced.isChecked()
        self.enhanced_widgets.setVisible(self.enhanced_enabled)
        self.calculate_voids()

    def auto_otsu_threshold(self):
        """用 Otsu 算法自动计算阈值"""
        if self.roi_mask is None:
            show_warning(self, '提示', '请先定义焊层 ROI')
            return
        if len(self.canvas.img_cv.shape) == 2:
            gray = self.canvas.img_cv
        else:
            gray = cv2.cvtColor(self.canvas.img_cv, cv2.COLOR_BGR2GRAY)
        thresh = otsu_threshold(gray, self.roi_mask)
        self.push_undo()
        self.slider_void.setValue(thresh)
        self.lbl_void_val.setText(str(thresh))
        self.calculate_voids()

    def on_area_filter_changed(self):
        """面积过滤条件改变时重新计算"""
        self.push_undo()
        self.void_min_area = self.spin_min_area.value()
        max_val = self.spin_max_area.value()
        self.void_max_area = max_val if max_val > 0 else None
        self.calculate_voids()

    def on_erosion_changed(self):
        """ROI 边界腐蚀量改变时重新计算"""
        self.push_undo()
        self.roi_erosion_px = self.spin_erosion.value()
        self.calculate_voids()

    def restore_void_defaults(self):
        self.push_undo()
        for w in (self.slider_void, self.spin_min_area, self.spin_max_area,
                  self.spin_erosion, self.slider_clahe_clip, self.spin_roundness):
            w.blockSignals(True)
        for w in (self.chk_labels, self.chk_fill, self.chk_enhanced,
                  self.chk_clahe, self.chk_morph, self.chk_edge):
            w.blockSignals(True)

        self.slider_void.setValue(80)
        self.chk_labels.setChecked(False)
        self.chk_fill.setChecked(True)
        self.spin_min_area.setValue(1)
        self.spin_max_area.setValue(0)
        self.spin_erosion.setValue(3)
        self.chk_enhanced.setChecked(True)
        self.chk_clahe.setChecked(True)
        self.slider_clahe_clip.setValue(20)
        self.chk_morph.setChecked(True)
        self.spin_roundness.setValue(0.0)
        self.chk_edge.setChecked(False)

        for w in (self.slider_void, self.spin_min_area, self.spin_max_area,
                  self.spin_erosion, self.slider_clahe_clip, self.spin_roundness):
            w.blockSignals(False)
        for w in (self.chk_labels, self.chk_fill, self.chk_enhanced,
                  self.chk_clahe, self.chk_morph, self.chk_edge):
            w.blockSignals(False)

        self.enhanced_widgets.setVisible(True)
        self.canvas.show_labels = False
        self.canvas.fill_voids = True
        self.toggle_visuals()
        self.calculate_voids()

    def push_undo(self):
        """保存当前空洞状态到撤销栈"""
        self.undo_stack.append(copy.deepcopy(self.voids_data))
        if len(self.undo_stack) > self.undo_limit:
            self.undo_stack.pop(0)

    def on_undo(self):
        """撤销到上一个状态"""
        if not self.undo_stack:
            show_info(self, '提示', '没有更多可撤销的操作')
            return
        self.voids_data = self.undo_stack.pop()
        self._refresh_void_metrics()

    def on_void_delete_at(self, x, y):
        """处理在画布上点击删除空洞"""
        if not self.voids_data:
            return
            
        # 将图像坐标转为numpy数组用于pointPolygonTest
        pt = (float(x), float(y))
        
        # 从后往前找，以便删除最上层的空洞（通常id最大，最后绘制）
        removed = False
        for i in range(len(self.voids_data) - 1, -1, -1):
            v = self.voids_data[i]
            pts = np.array(v['points'], dtype=np.int32)
            if len(pts) >= 3:
                # pointPolygonTest: 返回值>0表示在内部，=0在边上，<0在外部
                if cv2.pointPolygonTest(pts, pt, False) >= -1e-6:
                    self.push_undo()
                    del self.voids_data[i]
                    removed = True
                    break
        
        if removed:
            self._refresh_void_metrics()

    def on_void_add_polygon(self, points):
        """处理手动添加的空洞多边形"""
        if len(points) < 3:
            return
            
        # 计算新增空洞的属性
        pts_array = np.array(points, dtype=np.int32)
        area = cv2.contourArea(pts_array)
        if area < 1:
            return

        self.push_undo()
            
        x, y, w, h = cv2.boundingRect(pts_array)
        M = cv2.moments(pts_array)
        if M["m00"] != 0:
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
        else:
            cx, cy = x + w/2, y + h/2
            
        # 生成新的ID（当前最大ID + 1）
        new_id = 1
        if self.voids_data:
            new_id = max(v['id'] for v in self.voids_data) + 1
            
        new_void = {
            'id': new_id,
            'area_px': area,
            'rect': (x, y, w, h),
            'cx': cx,
            'cy': cy,
            'points': points,
            'manual': True  # 标记为手动添加
        }
        
        self.voids_data.append(new_void)
        self._refresh_void_metrics()

    def on_void_selected_for_local(self, void_id):
        """处理选中空洞进行局部阈值调节"""
        # 根据ID找到对应的空洞数据
        selected_void = None
        for v in self.voids_data:
            if v['id'] == void_id:
                selected_void = v
                break
                
        if selected_void is None:
            return
            
        self.selected_void_for_local = void_id
        
        # 创建围绕该空洞的局部区域
        local_rect = create_local_region_around_void(selected_void, padding=60)
        
        # 弹出对话框让用户设置局部阈值
        current_thresh = self.slider_void.value()
        thresh, ok = QInputDialog.getInt(
            self, 
            f"空洞 #{void_id} 局部阈值",
            f"请输入该区域的阈值 (0-255):",
            value=current_thresh,
            min=0, 
            max=255
        )
        
        if ok:
            self.push_undo()
            # 添加到局部区域列表
            local_region = (*local_rect, thresh)
            # 检查是否已存在该空洞的局部区域，有则更新
            updated = False
            for i, region in enumerate(self.local_regions):
                # 简单判断：如果新区域的中心在已存在区域内，则更新
                if (len(region) >= 5 and 
                    abs(region[0] + region[2]/2 - local_rect[0] - local_rect[2]/2) < 20 and
                    abs(region[1] + region[3]/2 - local_rect[1] - local_rect[3]/2) < 20):
                    self.local_regions[i] = local_region
                    updated = True
                    break
                    
            if not updated:
                self.local_regions.append(local_region)
                
            # 使用局部阈值重新检测空洞
            self.calculate_voids_with_local_regions()
    
    def calculate_voids_with_local_regions(self):
        """使用局部阈值区域重新计算空洞"""
        if self.roi_mask is None or self.canvas.img_cv is None:
            return
            
        if len(self.canvas.img_cv.shape) == 2:
            gray = self.canvas.img_cv
        else:
            gray = cv2.cvtColor(self.canvas.img_cv, cv2.COLOR_BGR2GRAY)
            
        global_thresh = self.slider_void.value()
        
        # 使用支持局部阈值的检测函数
        self.voids_data = detect_voids_local(
            gray, self.roi_mask, global_thresh, self.local_regions,
            min_area=self.void_min_area, max_area=self.void_max_area,
            enhanced=self.enhanced_enabled,
            clahe_enabled=self.enhanced_clahe,
            clahe_clip_limit=self.enhanced_clahe_clip,
            morph_enabled=self.enhanced_morph,
            min_roundness=self.enhanced_min_roundness,
            edge_verify=self.enhanced_edge_verify,
            roi_erosion_px=self.roi_erosion_px
        )
        
        self._refresh_void_metrics()


    def toggle_visuals(self):
        """切换视觉效果"""
        self.canvas.show_labels = self.chk_labels.isChecked()
        self.canvas.fill_voids = self.chk_fill.isChecked()
        self.canvas.update()

    def toggle_roi_overlay(self):
        """切换选区绿色蒙版"""
        self.canvas.show_roi_overlay = self.chk_roi_overlay.isChecked()
        self.canvas.update()

    def toggle_void_selection_mode(self):
        """切换局部阈值笔刷模式"""
        if self.void_edit_mode == 'local_brush':
            self.set_void_edit_mode('none')
            self.canvas.set_local_brush_regions([])  # 清除画布标注，保留阈值数据
        else:
            self.set_void_edit_mode('local_brush')
            self.canvas.set_local_brush_regions(self.local_brush_regions)

    def set_void_edit_mode(self, mode):
        """统一设置编辑模式（包含笔刷模式）"""
        if mode == self.void_edit_mode:
            mode = 'none'
        
        self.void_edit_mode = mode
        
        # 更新按钮选中状态
        self.btn_void_del.setChecked(mode == 'delete')
        self.btn_void_add.setChecked(mode == 'add')
        if hasattr(self, 'btn_void_local'):
            self.btn_void_local.setChecked(mode == 'local_brush')
        if hasattr(self, 'lbl_add_tip'):
            self.lbl_add_tip.setVisible(mode == 'add')
        
        # 通知 Canvas
        self.canvas.set_void_edit_mode(mode)
        
        # 笔刷模式处理
        self.local_brush_mode = (mode == 'local_brush')
        self.canvas.local_brush_mode = self.local_brush_mode
        if hasattr(self.canvas, 'brush_radius'):
            self.canvas.brush_radius = self.brush_radius
        
        # ROI 编辑状态控制
        if mode == 'none' and getattr(self, 'roi_polygon_pts', None):
            self.canvas.set_roi_edit_enabled(True)
        else:
            self.canvas.set_roi_edit_enabled(False)
        
        self.canvas.update()

    def on_local_region_confirmed(self, cx, cy, radius):
        """用户双击确认了一个局部笔刷区域"""
        self.push_undo()
        thresh = self.slider_void.value()
        region_id = len(self.local_brush_regions) + 1
        region = {
            'id': region_id,
            'cx': float(cx),
            'cy': float(cy),
            'radius': float(radius),
            'thresh': thresh
        }
        self.local_brush_regions.append(region)
        # 同步到画布显示（画布需要知道正确的阈值）
        self.canvas.set_local_brush_regions(self.local_brush_regions)
        self.calculate_voids_with_local()

    def on_local_threshold_changed(self, idx, new_thresh):
        """Shift+滚轮调节了某个已确认区域的阈值"""
        if 0 <= idx < len(self.local_brush_regions):
            self.push_undo()
            self.local_brush_regions[idx]['thresh'] = new_thresh
            self.calculate_voids_with_local()

    def on_local_region_removed(self, idx):
        """右键双击删除了某个局部笔刷区域"""
        if 0 <= idx < len(self.local_brush_regions):
            self.push_undo()
            del self.local_brush_regions[idx]
            self.calculate_voids_with_local()

    def calculate_voids_with_local(self):
        """使用局部笔刷阈值计算空洞"""
        if self.roi_mask is None or self.canvas.img_cv is None:
            return
        
        if len(self.canvas.img_cv.shape) == 2:
            gray = self.canvas.img_cv
        else:
            gray = cv2.cvtColor(self.canvas.img_cv, cv2.COLOR_BGR2GRAY)

        self.voids_data = detect_voids_local_brush(
            gray, self.roi_mask, self.slider_void.value(), self.local_brush_regions,
            min_area=self.void_min_area, max_area=self.void_max_area,
            enhanced=self.enhanced_enabled,
            clahe_enabled=self.enhanced_clahe,
            clahe_clip_limit=self.enhanced_clahe_clip,
            morph_enabled=self.enhanced_morph,
            min_roundness=self.enhanced_min_roundness,
            edge_verify=self.enhanced_edge_verify,
            roi_erosion_px=self.roi_erosion_px)
        
        self.canvas.draw_voids = self.voids_data
        self.canvas.update()
        self._refresh_void_metrics()

    def _refresh_void_metrics(self):
        """刷新空洞指标"""
        self.canvas.draw_voids = self.voids_data
        self.canvas.update()

        total_void_px = sum(float(v['area_px']) for v in self.voids_data)
        
        if self.solder_area_px > 0:
            rate = (total_void_px / self.solder_area_px) * 100
        else:
            rate = 0

        if self.pixel_scale > 0:
            total_area_um = total_void_px / (self.pixel_scale ** 2)
            self.result_box.setText(
                f"空洞数量：{len(self.voids_data)}\n"
                f"空洞总面积：{total_area_um:.2f} μm²\n"
                f"空洞率：{rate:.2f}%"
            )
        else:
            self.result_box.setText(
                f"空洞数量：{len(self.voids_data)}\n"
                f"空洞总面积：{total_void_px:.0f} 像素\n"
                f"空洞率：{rate:.2f}%"
            )

        self.canvas.void_rate_text = f"空洞率：{rate:.2f}%"

    # ========== 截图 ==========
    def save_screenshot(self):
        """一键截图复制到剪贴板"""
        pixmap = self.canvas.grab()
        QApplication.clipboard().setPixmap(pixmap)
        show_toast(self, "截图已复制到剪贴板")

    # ========== 数据导出 ==========
    def show_detail_table(self):
        """显示详细数据表格"""
        if not self.voids_data:
            show_info(self, "提示", "暂无空洞数据")
            return
            
        dlg = QDialog(self)
        dlg.setWindowTitle("空洞详细数据")
        dlg.resize(800, 600)
        dlg.setStyleSheet(DIALOG_STYLESHEET)
        
        layout = QVBoxLayout(dlg)
        
        btn_export = create_primary_button("导出 Excel (CSV)")
        btn_export.clicked.connect(lambda: self.export_csv(dlg))
        layout.addWidget(btn_export)
        
        table = QTableWidget()
        columns = ["序号", "面积 (μm²)", "最大长度 (μm)", "最大宽度 (μm)", "圆度 (0-1)"]
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setRowCount(len(self.voids_data))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        scale = self.pixel_scale if self.pixel_scale > 0 else 1.0
        
        for row, v in enumerate(self.voids_data):
            area_um = v['area_px'] / (scale ** 2)
            w_um = v['rect'][2] / scale
            h_um = v['rect'][3] / scale
            max_l = max(w_um, h_um)
            min_l = min(w_um, h_um)
            roundness = calculate_roundness(v['points'], v['area_px'])
            
            id_item = QTableWidgetItem(str(v['id']))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter |
                                     Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, 0, id_item)
            table.setItem(row, 1, align_right(QTableWidgetItem(f"{area_um:.2f}")))
            table.setItem(row, 2, align_right(QTableWidgetItem(f"{max_l:.2f}")))
            table.setItem(row, 3, align_right(QTableWidgetItem(f"{min_l:.2f}")))
            table.setItem(row, 4, align_right(QTableWidgetItem(f"{roundness:.3f}")))
            
        layout.addWidget(table)
        dlg.exec()

    def export_csv(self, parent_dlg):
        """导出CSV"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        path, _ = QFileDialog.getSaveFileName(
            self, "导出CSV", f"空洞分析_{timestamp}.csv", "CSV Files (*.csv)")
        
        if not path:
            return
            
        scale = self.pixel_scale if self.pixel_scale > 0 else 1.0
        data_export = []
        
        for v in self.voids_data:
            area_um = v['area_px'] / (scale ** 2)
            w_um = v['rect'][2] / scale
            h_um = v['rect'][3] / scale
            max_l = max(w_um, h_um)
            roundness = calculate_roundness(v['points'], v['area_px'])
            
            data_export.append({
                "序号": v['id'],
                "面积(μm²)": f"{area_um:.2f}",
                "最大长度(μm)": f"{max_l:.2f}",
                "圆度": f"{roundness:.3f}",
                "Center_X": int(v['cx']),
                "Center_Y": int(v['cy'])
            })
        
        write_csv(path, data_export)
        show_toast(parent_dlg, "文件导出成功")


# ====================== 局部阈值支持函数 ======================

def create_local_region_around_void(void_data, padding=60):
    """创建一个围绕空洞的局部矩形区域"""
    if not void_data:
        return (0, 0, 100, 100)
    
    x, y, w, h = void_data['rect']
    cx, cy = int(void_data.get('cx', x + w/2)), int(void_data.get('cy', y + h/2))
    
    new_x = max(0, cx - padding)
    new_y = max(0, cy - padding)
    new_w = 2 * padding
    new_h = 2 * padding
    
    return (new_x, new_y, new_w, new_h)


def detect_voids_local(gray_img, roi_mask, global_thresh, local_regions,
                       min_area=1, max_area=None,
                       enhanced=False, clahe_enabled=True,
                       clahe_clip_limit=2.0,
                       morph_enabled=True, morph_kernel=3,
                       min_roundness=0.0, edge_verify=False):
    """支持局部阈值的空洞检测"""
    if len(gray_img.shape) == 3:
        gray = cv2.cvtColor(gray_img, cv2.COLOR_BGR2GRAY)
    else:
        gray = gray_img.copy()

    if enhanced and clahe_enabled:
        clahe = cv2.createCLAHE(clipLimit=clahe_clip_limit, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

    _, bin_inv = cv2.threshold(gray, global_thresh, 255, cv2.THRESH_BINARY_INV)

    if enhanced and morph_enabled and morph_kernel > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel, morph_kernel))
        bin_inv = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, kernel)

    final_mask = cv2.bitwise_and(bin_inv, bin_inv, mask=roi_mask)

    for region in local_regions:
        if len(region) < 5:
            continue
        x = int(region[0])
        y = int(region[1])
        w = int(region[2])
        h = int(region[3])
        local_thresh = int(region[4])
        
        if w <= 0 or h <= 0:
            continue
            
        roi = gray[y:y+h, x:x+w]
        if roi.size == 0:
            continue
            
        _, local_bin = cv2.threshold(roi, local_thresh, 255, cv2.THRESH_BINARY_INV)
        
        local_full = np.zeros_like(gray)
        local_full[y:y+h, x:x+w] = local_bin
        
        local_mask = np.zeros_like(roi_mask)
        local_mask[y:y+h, x:x+w] = 255
        
        final_mask = cv2.bitwise_and(final_mask, final_mask, mask=cv2.bitwise_not(local_mask))
        final_mask = cv2.bitwise_or(final_mask, cv2.bitwise_and(local_full, local_mask))

    contours, _ = cv2.findContours(final_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    edge_map = None
    if enhanced and edge_verify:
        blurred = cv2.GaussianBlur(gray, (5, 5), 1.0)
        edge_map = cv2.Canny(blurred, 30, 100)
        edge_map = cv2.bitwise_and(edge_map, edge_map, mask=roi_mask)
    
    voids_data = []
    void_id = 1
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue
        if enhanced and min_roundness > 0:
            perimeter = cv2.arcLength(cnt, True)
            if perimeter > 0:
                r = (4 * np.pi * area) / (perimeter ** 2)
                if min(r, 1.0) < min_roundness:
                    continue
        if enhanced and edge_verify and edge_map is not None:
            contour_mask = np.zeros_like(edge_map)
            cv2.drawContours(contour_mask, [cnt], -1, 255, 1)
            overlap = cv2.bitwise_and(contour_mask, contour_mask, mask=edge_map)
            ep = cv2.countNonZero(overlap)
            tp = cv2.countNonZero(contour_mask)
            if tp > 0 and (ep / tp) < 0.3:
                continue
        x, y, w, h = cv2.boundingRect(cnt)
        M = cv2.moments(cnt)
        cx = M["m10"] / M["m00"] if M["m00"] != 0 else x + w/2.0
        cy = M["m01"] / M["m00"] if M["m00"] != 0 else y + h/2.0
        pts = cnt.reshape(-1, 2).tolist()
        
        voids_data.append({
            'id': void_id,
            'area_px': area,
            'rect': (x, y, w, h),
            'cx': cx,
            'cy': cy,
            'points': pts,
            'manual': False
        })
        void_id += 1
    return voids_data


def detect_voids_local_brush(gray_img, roi_mask, global_thresh, local_regions, min_area=1, max_area=None, enhanced=False, clahe_enabled=True, clahe_clip_limit=2.0, morph_enabled=True, morph_kernel=3, min_roundness=0.0, edge_verify=False, roi_erosion_px=3):
    if len(gray_img.shape) == 3:
        gray = cv2.cvtColor(gray_img, cv2.COLOR_BGR2GRAY)
    else:
        gray = gray_img.copy()

    if enhanced and clahe_enabled:
        clahe = cv2.createCLAHE(clipLimit=clahe_clip_limit, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

    _, bin_inv = cv2.threshold(gray, global_thresh, 255, cv2.THRESH_BINARY_INV)

    if enhanced and morph_enabled and morph_kernel > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel, morph_kernel))
        bin_inv = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, kernel)

    if roi_erosion_px > 0:
        kernel_erode = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (roi_erosion_px * 2 + 1, roi_erosion_px * 2 + 1))
        interior_mask = cv2.erode(roi_mask, kernel_erode, iterations=1)
    else:
        interior_mask = roi_mask
    final_mask = cv2.bitwise_and(bin_inv, bin_inv, mask=interior_mask)

    for region in local_regions:
        cx = region['cx']
        cy = region['cy']
        radius = region['radius']
        thresh = region['thresh']

        x1 = max(0, int(cx - radius))
        y1 = max(0, int(cy - radius))
        x2 = min(gray.shape[1], int(cx + radius))
        y2 = min(gray.shape[0], int(cy + radius))

        if x2 <= x1 or y2 <= y1:
            continue

        roi = gray[y1:y2, x1:x2]
        _, local_bin = cv2.threshold(roi, thresh, 255, cv2.THRESH_BINARY_INV)

        local_full = np.zeros_like(gray)
        local_full[y1:y2, x1:x2] = local_bin

        circle_mask = np.zeros_like(roi_mask, dtype=np.uint8)
        cv2.circle(circle_mask, (int(cx), int(cy)), int(radius), 255, -1)

        final_mask = cv2.bitwise_and(final_mask, final_mask, mask=cv2.bitwise_not(circle_mask))
        final_mask = cv2.bitwise_or(final_mask, cv2.bitwise_and(local_full, circle_mask))

    contours, _ = cv2.findContours(final_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    edge_map = None
    voids_data = []
    void_id = 1
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue
        if enhanced and min_roundness > 0:
            perimeter = cv2.arcLength(cnt, True)
            if perimeter > 0:
                r = (4 * np.pi * area) / (perimeter ** 2)
                if min(r, 1.0) < min_roundness:
                    continue
        if enhanced and edge_verify:
            if edge_map is None:
                blurred = cv2.GaussianBlur(gray, (5, 5), 1.0)
                edge_map = cv2.Canny(blurred, 30, 100)
                edge_map = cv2.bitwise_and(edge_map, edge_map, mask=interior_mask)
            contour_mask = np.zeros_like(edge_map)
            cv2.drawContours(contour_mask, [cnt], -1, 255, 1)
            overlap = cv2.bitwise_and(contour_mask, contour_mask, mask=edge_map)
            ep = cv2.countNonZero(overlap)
            tp = cv2.countNonZero(contour_mask)
            if tp > 0 and (ep / tp) < 0.3:
                continue
        x, y, w, h = cv2.boundingRect(cnt)
        M = cv2.moments(cnt)
        cx = M["m10"] / M["m00"] if M["m00"] != 0 else x + w/2.0
        cy = M["m01"] / M["m00"] if M["m00"] != 0 else y + h/2.0
        pts = cnt.reshape(-1, 2).tolist()
        
        voids_data.append({
            'id': void_id,
            'area_px': area,
            'rect': (x, y, w, h),
            'cx': cx,
            'cy': cy,
            'points': pts,
            'manual': False
        })
        void_id += 1
        
    return voids_data