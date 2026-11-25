"""示教与批量检测 Tab

流程（设计文档 §13）：
  ① 上传样板图 → ② 点选典型空洞 → ③ 示范焊层区域（空洞锚定自动识别 /
  多边形手绘 + 顶点微调）→ ④ 划比例尺 → ⑤ 学习 + 预览 + 保存为示教配方
  → 批量：选择示教配方 + 文件夹 → 逐图全自动检测 → 汇总统计 + CSV

为什么点选空洞在定义焊层区域之前：空洞必在焊层带内部，是焊层带的定位
锚点。纯亮度判据分不开"亮基质+暗孔"的焊层带与均匀亮的邻近区，而用
空洞核心周围的环形带做焊层类、远处做背景类求分离阈值，可以直接圈出焊层带。

焊层区域每张图形状/位置都不同，因此本 Tab 不存固定 ROI 多边形，
只存"示教模型"（焊层/空洞灰度统计 + 分离阈值 + 比例尺模板），
批量时逐图自适应定位焊层带。
"""

import os
import numpy as np
import cv2
from datetime import datetime

from PyQt6.QtWidgets import (QDialog,QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                             QFrame, QScrollArea, QLabel, QTableWidget,
                             QTableWidgetItem, QHeaderView, QInputDialog,
                             QMessageBox, QSizePolicy,
                             QProgressBar, QProgressDialog, QComboBox,
                             QListWidget, QListWidgetItem, QAbstractItemView, QGridLayout,
                             QSpinBox, QSplitter, QStackedWidget, QToolButton,
                             QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
                             QApplication)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QColor, QImage, QPixmap, QIcon, QPainter

from canvas import ImageCanvas
from csv_export import write_csv
from image import (polygon_to_mask, otsu_threshold, locate_solder_band,
                   grab_local_dark_blob, learn_taught_model, apply_taught_model,
                   read_scale_bar, resample_polygon_points, two_class_threshold,
                   annotate_result, make_thumb, render_summary_sheet,
                   render_solder_strip)
from recipe import (list_recipes, load_recipe, save_taught, load_bar_template,
                    _recipe_root)
from ui_components import (NumericItem, align_right, attach_empty_hint,
                           confirm_action, create_primary_button,
                           create_secondary_button, create_success_button,
                           create_danger_button, create_nav_button,
                           create_success_label, create_success_value,
                           create_step_title, create_info_label,
                           create_checkbox, enable_click_sort,
                           CollapsibleSection)
from ui_dialogs import show_info, show_toast, show_warning

IMG_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')


def read_image_file(path):
    """读取图像文件（支持 TIF，含 16bit 归一化）

    与 stitching_tab._read_image / main_window._read_image 逻辑一致，
    批量线程中需要独立函数（不依赖任何 Tab 实例）。
    """
    ext = os.path.splitext(path)[1].lower()
    img = None
    if ext in {'.tif', '.tiff'}:
        try:
            import tifffile
            img = tifffile.imread(path)
            if img.ndim == 3 and img.shape[0] in (3, 4):
                img = np.transpose(img, (1, 2, 0))
        except Exception:
            img = None
    if img is None:
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.dtype != np.uint8:
        mx = float(img.max()) if img.size else 0.0
        img = (img / mx * 255).astype(np.uint8) if mx > 0 else img.astype(np.uint8)
    return img


class BatchWorker(QThread):
    """批量检测工作线程：顺序处理，带进度与取消

    信号里只传"轻量结果"（剥掉 band_mask / voids 点集）——几十张 4K 图
    的掩码常驻内存会到几百 MB（违反设计文档 D2）。需要叠加图时按需重算。
    """

    progress = pyqtSignal(int, int, str)      # idx, total, filename
    tile_done = pyqtSignal(dict)              # 单图轻量结果
    finished = pyqtSignal(list)               # 全部轻量结果
    failed = pyqtSignal(str)

    HEAVY_KEYS = ('band_mask', 'voids')

    def __init__(self, image_paths, model, bar_template=None):
        super().__init__()
        self.image_paths = list(image_paths)
        self.model = model
        self.bar_template = bar_template
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        results = []
        total = len(self.image_paths)
        try:
            for i, path in enumerate(self.image_paths):
                if self._cancel:
                    break
                self.progress.emit(i, total, os.path.basename(path))
                fname = os.path.basename(path)
                img = read_image_file(path)
                if img is None:
                    results.append({'ok': False, 'filename': fname, 'path': path,
                                    'warnings': ['图片读取失败']})
                    self.tile_done.emit(results[-1])
                    continue
                gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

                # 比例尺逐图自动识别；失败/存疑退回示范值
                bar_cfg = self.model.get('scale_bar') or {}
                px_um, bar_info = read_scale_bar(
                    gray, self.bar_template, bar_cfg,
                    fallback_px_per_um=self.model.get('px_per_um', 0.0))
                bar_ok = bool(bar_info.get('found')) and not bar_info.get('reason')

                r = apply_taught_model(gray, self.model)
                light = {k: v for k, v in r.items() if k not in self.HEAVY_KEYS}
                # 结果缩略图（供结果区胶片条；带焊层/空洞叠加，便于一眼看出问题）
                if r.get('ok'):
                    try:
                        light['thumb'] = make_thumb(img, r['band_mask'], r['voids'])
                    except Exception:
                        light['thumb'] = None
                light['filename'] = fname
                light['path'] = path
                light['px_per_um_used'] = px_um
                light['bar_found'] = bar_ok
                warns = light.setdefault('warnings', [])
                if self.bar_template is not None:
                    reason = bar_info.get('reason')
                    if reason == 'length_implausible':
                        warns.append(
                            f"比例尺长度异常(测{bar_info.get('length_px')}px vs "
                            f"示范{bar_info.get('taught_px', 0):.0f}px)，已用示范值")
                    elif reason:
                        warns.append('比例尺识别/测量失败，已用示范值')
                    elif not bar_info.get('found'):
                        warns.append('比例尺未识别，已用示范值')
                results.append(light)
                self.tile_done.emit(light)
            self.progress.emit(total, total, '完成')
            self.finished.emit(results)
        except Exception as e:
            self.failed.emit(str(e))


class _StripView(QGraphicsView):
    """金锡拼接图预览控件：滚轮缩放、拖动平移、双击适应窗口"""

    def __init__(self, rgb, parent=None):
        super().__init__(parent)
        rgb = np.ascontiguousarray(rgb)
        qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
                      QImage.Format.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(qimg)
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem(self._pix)
        self._scene.addItem(self._item)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(20, 20, 20))
        self._fitted = False
        self.setMinimumHeight(220)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._fitted:
            self._fit_view()
            self._fitted = True

    def _fit_view(self):
        """整图适应窗口（宽图也能一眼看全，再滚轮放大看细节）"""
        self.resetTransform()
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, e):
        factor = 1.25 if e.angleDelta().y() > 0 else 1 / 1.25
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, e):
        self._fit_view()


class TeachBatchTab(QWidget):
    """示教学习 + 批量检测"""

    def __init__(self):
        super().__init__()
        # 示教状态
        self.img_cv = None
        self.gray = None
        self.sample_path = None
        self.roi_mask = None
        self.roi_polygon_pts = []
        self.void_marks = []          # [(cx, cy), ...] 点选中心
        self.void_blobs = []          # 对应的全图暗核掩码
        self.pixel_scale = 0.0
        self.bar_info = None          # {'template','length_px','real_um','horizontal','dark'}
        self.model = None
        self.recipe_name = None
        # 批量状态
        self.batch_paths = []
        self.batch_results = []
        self.worker = None
        self.preview_row = None
        self._batch_canceled = False
        self._last_model = None            # 最近一次批量的模型（预览/导出时按需重算）
        self.quick_cfg = None              # 「快速设定」的设定值（复用整批）
        self._model_source = None          # 当前生效模型来源：teach / quick
        self._last_bar_template = None
        # 单图核对与修正
        self.result_edits = {}             # row -> {'mask','polygon','voids','caliber'}
        self._edit_polygon = []            # 当前预览图的编辑态焊层多边形（显示/编辑用）
        self._edit_mask = None             # 当前预览图的区域掩码（面积口径的权威来源）
        self._poly_touched = False         # 是否拖过顶点（决定面积口径）
        self._edit_voids = []              # 当前预览图的编辑态空洞
        self._baseline_voids = []          # 预览载入时的空洞快照（判断有无改动）
        self._preview_gray = None
        self._add_void_mode = False        # 预览「添加空洞」模式（与示教点选区分）
        self._del_void_mode = False        # 预览「删除空洞」模式
        self.init_ui()

    # ================== 当前示教模型（单一事实源） ==================

    @property
    def quick_model(self):
        """兼容旧接口：快速示教模型即当前生效模型。"""
        return self.model if self._model_source == 'quick' else None

    @quick_model.setter
    def quick_model(self, model):
        if model is None:
            if self._model_source == 'quick':
                self._adopt_teach_model(None, None)
        else:
            self._adopt_teach_model(model, 'quick')

    def _adopt_teach_model(self, model, source):
        """快速/完整示教统一在此写入当前模型，避免两套状态互相覆盖。"""
        self.model = model
        self._model_source = source if model is not None else None
        if hasattr(self, 'btn_save_recipe'):
            self.btn_save_recipe.setEnabled(model is not None)
        try:
            self._refresh_step_states()
        except Exception:
            pass

    def _select_recipe(self, name):
        """按配方名选中下拉项（数据名优先，再按显示名）。"""
        if not name:
            return False
        idx = self.combo_recipe.findData(f'{name}.taught.json')
        if idx < 0:
            idx = self.combo_recipe.findText(name)
        if idx < 0:
            return False
        self.combo_recipe.setCurrentIndex(idx)
        return True

    # ================== UI ==================

    STEP_TITLES = ("样板图", "点选空洞", "焊层区域", "比例尺", "学习")

    def init_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(12)

        # ── 主区：上=工作区（左面板 + 画布），下=结果区（批量后出现）──
        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.hsplit = QSplitter(Qt.Orientation.Horizontal)
        self.splitter = self.hsplit          # 兼容旧名
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self._build_batch_panel())
        self.hsplit.addWidget(self.left_stack)
        self.canvas = ImageCanvas()
        self.hsplit.addWidget(self.canvas)
        self.hsplit.setStretchFactor(0, 0)
        self.hsplit.setStretchFactor(1, 1)
        self.vsplit.addWidget(self.hsplit)

        self.results = self._build_results_panel()
        self.results.setVisible(False)
        self.vsplit.addWidget(self.results)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setStretchFactor(1, 0)
        self.vsplit.setSizes([420, 240])
        lo.addWidget(self.vsplit)

        self._sb_min = self._compute_left_min_width()
        self.left_stack.setMinimumWidth(self._sb_min)
        start = min(460, max(340, self._sb_min))
        self.hsplit.setSizes([start, max(560, 1100 - start)])
        self._set_mode_batch()
        self.results.setVisible(False)
        self._connect()

    # ---------- 面板骨架 ----------

    @staticmethod
    def _panel_frame(obj_name="SidebarCard"):
        f = QFrame()
        f.setObjectName(obj_name)
        f.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        # ✗ 这里原来加了 QGraphicsDropShadowEffect(blur 30 / offset 0,4 / 黑 25)
        #   结果是：面板紧挨分隔条时，投影在浅色底上变成一条**脏灰竖带**（用户截图里那条 ✗）
        #   扁平风格的面板层次靠 1px 描边 + 底色差就够了 → 不再加投影 ✔
        return f

    @staticmethod
    def _scroll_into(frame, content):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return frame

    def _compute_left_min_width(self):
        """按批量面板全部内容可见的真实需求算左栏最小宽度。"""
        self._batch_content.adjustSize()
        QApplication.processEvents()
        hint = self._batch_content.sizeHint().width()
        return max(300, min(520, hint + 12))

    # ---------- 示教页 ----------

    def _build_teach_panel(self):
        content = QWidget()
        self._teach_content = content
        v = QVBoxLayout(content)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(14)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.addWidget(create_info_label(
            "高级流程：仅在快速示教不适用时使用。日常建议回批量页用“快速示教（两步）”。"))

        strip = QVBoxLayout()
        strip.setSpacing(4)
        self.step_buttons = []
        for i, t in enumerate(self.STEP_TITLES):
            b = create_nav_button(
                t, lambda _=False, i=i: self.set_teach_step(i))
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            strip.addWidget(b)
            self.step_buttons.append(b)
        v.addLayout(strip)

        self._step_containers = []

        def _new_step():
            c = QWidget()
            lay = QVBoxLayout(c)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            self._step_containers.append(c)
            v.addWidget(c)
            return lay

        # ── ① 上传样板图 ──
        s = _new_step()
        s.addWidget(create_primary_button("上传样板图", self.load_sample))

        # ── ② 点选典型空洞 ──
        s = _new_step()
        row = QHBoxLayout()
        self.btn_teach_void = create_secondary_button("点选空洞", self.toggle_teach_void,
                                                      checkable=True)
        self.btn_teach_void.setToolTip("在图上点几个明显的空洞（大小有代表性即可）")
        row.addWidget(self.btn_teach_void)
        s.addLayout(row)
        self.list_marks = QListWidget()
        self.list_marks.setMaximumHeight(64)
        self.list_marks.setMinimumWidth(150)
        self.list_marks.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.list_marks.setToolTip("已点选的空洞，可删除选错的那一个")
        s.addWidget(self.list_marks)
        row = QHBoxLayout()
        self.btn_del_mark = create_secondary_button("删除选中", self.delete_selected_mark)
        row.addWidget(self.btn_del_mark)
        self.btn_clear_marks = create_danger_button("清除全部", self.confirm_clear_marks)
        row.addWidget(self.btn_clear_marks)
        s.addLayout(row)
        self.lbl_void = create_info_label("已点选 0 个")
        s.addWidget(self.lbl_void)

        # ── ③ 示范焊层区域 ──
        s = _new_step()
        row = QHBoxLayout()
        self.btn_auto_band = create_secondary_button("自动识别焊层带", self.auto_draft_roi)
        self.btn_auto_band.setToolTip("按点选的暗斑反推阈值，自动圈出焊层带")
        row.addWidget(self.btn_auto_band)
        self.btn_poly = create_secondary_button("多边形手绘", self.start_poly_roi,
                                                checkable=True)
        self.btn_poly.setToolTip("自动识别不准时，自己沿焊层边界画一圈")
        row.addWidget(self.btn_poly)
        s.addLayout(row)
        self.btn_edit_roi = create_secondary_button("编辑顶点", self.toggle_edit_roi,
                                                    checkable=True)
        self.btn_edit_roi.setToolTip(
            "光标移到边界，最近的顶点会高亮，拖动它移动；双击边加点；Delete 删点")
        s.addWidget(self.btn_edit_roi)
        self.lbl_roi = create_info_label("未定义")
        s.addWidget(self.lbl_roi)

        # ── ④ 标定比例尺 ──
        s = _new_step()
        self.btn_calib = create_secondary_button("在比例尺上划线", self.start_calib,
                                                 checkable=True)
        self.btn_calib.setToolTip("在图上 SEM 的比例尺上划一条线，再输入实际 μm 值")
        s.addWidget(self.btn_calib)
        self.lbl_calib = create_info_label("未标定")
        s.addWidget(self.lbl_calib)

        # ── ⑤ 学习并保存 ──
        s = _new_step()
        self.btn_learn = create_primary_button("开始学习", self.on_learn)
        s.addWidget(self.btn_learn)
        self.btn_save_recipe = create_success_button("保存为示教配方", self.on_save_recipe)
        self.btn_save_recipe.setEnabled(False)
        s.addWidget(self.btn_save_recipe)
        self.lbl_learn = create_info_label("完成 ①~④ 后点「开始学习」")
        s.addWidget(self.lbl_learn)

        v.addStretch()
        return self._scroll_into(self._panel_frame(), content)

    # ---------- 批量页（左栏：控制项）----------

    def _build_batch_panel(self):
        content = QWidget()
        self._batch_content = content
        v = QVBoxLayout(content)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(14)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.combo_recipe = QComboBox()
        self.combo_recipe.setMinimumWidth(120)
        self.combo_recipe.setToolTip("已保存的示教配方")
        v.addWidget(self.combo_recipe)

        self.btn_folder = create_secondary_button("选择批次文件夹", self.pick_folder)
        v.addWidget(self.btn_folder)
        self.lbl_folder = create_info_label("未选择文件夹")
        v.addWidget(self.lbl_folder)

        # 快速示教（两步·操作最少）：① 焊层区域（打开即自动识别） ② 点选空洞（点完自动学习）
        self.btn_quick_teach = create_primary_button("快速示教（两步）", self.on_quick_teach)
        self.btn_quick_teach.setToolTip(
            "自动挑一张代表性图打开：① 焊层区域已自动识别好（不对可手绘/拖顶点）\n"
            "② 左键点 2~3 个典型空洞，点完自动学习并实时显示结果；点错按 Delete 删除。\n"
            "算法与完整示教完全同源，学出的模型直接用于整批检测。")
        v.addWidget(self.btn_quick_teach)
        self.lbl_quick_teach = create_success_label("")
        v.addWidget(self.lbl_quick_teach)

        row = QHBoxLayout()
        self.btn_run = create_primary_button("开始批量", self.start_batch)
        row.addWidget(self.btn_run)
        self.btn_cancel = create_danger_button("取消", self.cancel_batch)
        self.btn_cancel.setEnabled(False)
        row.addWidget(self.btn_cancel)
        v.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        v.addWidget(self.progress)
        self.lbl_current = create_info_label("")
        v.addWidget(self.lbl_current)

        # 空洞判定：默认收起（需要放宽时再展开），避免默认视图堆满控件
        sens = CollapsibleSection("空洞判定（漏检多才需要改）")
        self.sens_section = sens
        sens.container.setVisible(False)
        sens.toggle_btn.setToolTip(
            '展开后填面积下限/上限与深度容差；勾"自动"即按带面积定')
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)

        self.chk_min_auto = create_checkbox("自动", True, self._on_sens_changed)
        self.chk_min_auto.setToolTip("按焊层带面积自动定（0.02%，下限 12px²）")
        self.spin_min = QSpinBox()
        self.spin_min.setRange(1, 200000)
        self.spin_min.setValue(12)
        self.spin_min.setSuffix(" px²")
        self.spin_min.setEnabled(False)
        self.spin_min.setToolTip("小于它的暗斑不计入（挡噪点）")
        grid.addWidget(QLabel("面积下限"), 0, 0)
        grid.addWidget(self.chk_min_auto, 0, 1)
        grid.addWidget(self.spin_min, 0, 2)

        self.chk_max_auto = create_checkbox("自动", True, self._on_sens_changed)
        self.chk_max_auto.setToolTip("按焊层带面积自动定（30%，仅作分割失败兜底）")
        self.spin_max = QSpinBox()
        self.spin_max.setRange(50, 10 ** 7)
        self.spin_max.setValue(2000)
        self.spin_max.setSuffix(" px²")
        self.spin_max.setEnabled(False)
        self.spin_max.setToolTip("大于它的暗斑不计入——调太小会把大空洞漏掉")
        grid.addWidget(QLabel("面积上限"), 1, 0)
        grid.addWidget(self.chk_max_auto, 1, 1)
        grid.addWidget(self.spin_max, 1, 2)

        self.spin_depth = QSpinBox()
        self.spin_depth.setRange(-60, 60)
        self.spin_depth.setValue(0)
        self.spin_depth.setSuffix(" 灰阶")
        self.spin_depth.setToolTip(
            "空洞阈值偏移：正值更包容，能把偏浅的暗斑也算作空洞")
        grid.addWidget(QLabel("深度容差"), 2, 0)
        grid.addWidget(self.spin_depth, 2, 1, 1, 2)
        sens.addLayout(grid)
        v.addWidget(sens)
        v.addStretch()
        return self._scroll_into(self._panel_frame(), content)

    # ---------- 结果区（批量后出现，横跨画布下方）----------

    def _build_results_panel(self):
        f = self._panel_frame()
        v = QVBoxLayout(f)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(6)

        # 汇总（3 行，小字号，避免长串换行错乱）
        head = QHBoxLayout()
        head.setSpacing(10)
        self.lbl_total = create_success_value("总空洞率：—")
        head.addWidget(self.lbl_total)
        self.lbl_stats = create_info_label("")
        head.addWidget(self.lbl_stats, 1)
        self.btn_collapse_results = create_secondary_button(
            "收起结果区", self._toggle_results_collapse)
        head.addWidget(self.btn_collapse_results)
        v.addLayout(head)

        # 缩略图胶片条（点小图 → 画布放大；异常描红边）
        self.thumb_scroll = QScrollArea()
        self.thumb_scroll.setWidgetResizable(True)
        self.thumb_scroll.setFixedHeight(72)
        self.thumb_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumb_host = QWidget()
        self.thumb_row = QHBoxLayout(self.thumb_host)
        self.thumb_row.setContentsMargins(2, 2, 2, 2)
        self.thumb_row.setSpacing(6)
        self.thumb_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.thumb_scroll.setWidget(self.thumb_host)
        v.addWidget(self.thumb_scroll)

        self.lbl_preview = create_info_label("预览：未选择")
        v.addWidget(self.lbl_preview)

        body = QHBoxLayout()
        body.setSpacing(10)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["图片", "金锡面积(px²)", "空洞数", "空洞率(%)", "警告"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(90)
        self.table.setMinimumWidth(170)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        attach_empty_hint(self.table, '尚无批量结果；选择批次后点击开始批量')
        enable_click_sort(
            self.table, locked=lambda: getattr(self, 'worker', None) is not None)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        body.addWidget(self.table, 1)

        # 单图核对与修正：2 列网格，按钮不会被挤到重叠
        fix = QFrame()
        fix.setObjectName("InnerCard")
        fix.setMinimumWidth(360)
        fl = QVBoxLayout(fix)
        fl.setContentsMargins(10, 8, 10, 8)
        fl.setSpacing(5)
        fl.addWidget(create_step_title("单图核对与修正"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        self.btn_edit_band = create_secondary_button("编辑金锡区域",
                                                     self.toggle_edit_band, checkable=True)
        self.btn_edit_band.setToolTip(
            "光标移到边界，最近顶点高亮后拖动；双击边加点；Delete 删点")
        self.btn_add_void = create_secondary_button("添加空洞", self.toggle_add_void,
                                                    checkable=True)
        self.btn_add_void.setToolTip("点图上空白处添加空洞（暗核自动抓取）")
        self.btn_del_void = create_secondary_button("删除空洞", self.toggle_del_void,
                                                    checkable=True)
        self.btn_del_void.setToolTip("点图上要删的空洞（悬停高亮）")
        grid.addWidget(self.btn_edit_band, 0, 0)
        grid.addWidget(self.btn_add_void, 1, 0)
        grid.addWidget(self.btn_del_void, 1, 1)
        self.chk_labels = create_checkbox("显示序号", True, self.toggle_void_display)
        self.chk_labels.setToolTip("是否在图上显示空洞编号")
        grid.addWidget(self.chk_labels, 3, 1)
        self.chk_fill = create_checkbox("红色填充", True, self.toggle_void_display)
        self.chk_fill.setToolTip("空洞是否用红色填充（关掉只画红框）")
        grid.addWidget(self.chk_fill, 3, 0)
        self.btn_apply_edit = create_success_button("应用修改", self.apply_result_edit)
        self.btn_apply_edit.setToolTip("把修正写进结果表与汇总")
        self.btn_revert_edit = create_danger_button("还原自动", self.confirm_revert_edit)
        self.btn_revert_edit.setToolTip("放弃本图的修正，回到自动检测结果")
        grid.addWidget(self.btn_apply_edit, 2, 0)
        grid.addWidget(self.btn_revert_edit, 2, 1)
        fl.addLayout(grid)
        body.addWidget(fix, 0)
        v.addLayout(body, 1)

        exp = QHBoxLayout()
        exp.setSpacing(8)
        self.btn_export = create_secondary_button("导出 CSV", self.export_csv)
        self.btn_export.setEnabled(False)
        exp.addWidget(self.btn_export)
        self.btn_exp_cur = create_secondary_button("导出当前标注图",
                                                   self.export_annotated_current)
        exp.addWidget(self.btn_exp_cur)
        self.btn_exp_all = create_secondary_button("导出全部标注图",
                                                   self.export_annotated_all)
        exp.addWidget(self.btn_exp_all)
        self.btn_exp_sheet = create_success_button("导出汇总大图",
                                                   self.export_summary_sheet)
        exp.addWidget(self.btn_exp_sheet)
        self.btn_exp_strip = create_success_button("导出金锡拼接图",
                                                   self.export_solder_strip)
        self.btn_exp_strip.setToolTip(
            "把每张图的金锡区域抠出、按顺序横向拼成一张大图\n"
            "区域外填黑，空洞仍用红色掩膜填充")
        exp.addWidget(self.btn_exp_strip)
        self.btn_view_strip = create_secondary_button("查看金锡拼接图",
                                                       self.view_solder_strip)
        self.btn_view_strip.setToolTip(
            "在窗口内预览金锡拼接图（黑底，空洞红色填充）\n"
            "支持缩放查看，也可另存为 PNG")
        exp.addWidget(self.btn_view_strip)
        self.combo_sheet = QComboBox()
        self.combo_sheet.addItem("排版：纵向堆叠", "vertical")
        self.combo_sheet.addItem("排版：横向一行", "horizontal")
        self.combo_sheet.addItem("排版：网格 2 列", "grid2")
        self.combo_sheet.addItem("排版：网格 3 列", "grid3")
        self.combo_sheet.setToolTip(
            "汇总大图的排列方式：\n"
            "纵向堆叠——每张占满整幅宽，从上往下排（宽图最清晰）\n"
            "横向一行——统一高度、从左到右排（适合张数少）\n"
            "网格——按列平铺，一屏看全（适合张数多）")
        exp.addWidget(self.combo_sheet)
        exp.addStretch()
        v.addLayout(exp)
        return f

    def _toggle_results_collapse(self):
        """收起/展开结果区（小屏幕上给画布让位）"""
        self._results_collapsed = not getattr(self, '_results_collapsed', False)
        if self._results_collapsed:
            self._results_heights = tuple(self.vsplit.sizes())
            self.thumb_scroll.setVisible(False)
            self.lbl_preview.setVisible(False)
            self.table.setVisible(False)
            self.btn_collapse_results.setText("展开结果区")
            self.vsplit.setSizes([max(1, self.vsplit.height() - 120), 120])
        else:
            self.thumb_scroll.setVisible(True)
            self.lbl_preview.setVisible(True)
            self.table.setVisible(True)
            self.btn_collapse_results.setText("收起结果区")
            h = max(260, int(self.vsplit.height() * 0.40))
            self.vsplit.setSizes([max(1, self.vsplit.height() - h), h])

    # ---------- 模式 ----------

    def _set_mode_teach(self):
        """完整示教已移除；保留旧调用入口，统一回批量模式。"""
        self._set_mode_batch()

    def _set_mode_batch(self):
        self._mode = 'batch'
        self.left_stack.setCurrentIndex(0)
        self.results.setVisible(True)
        self.refresh_recipe_combo()
        if self.batch_results and not getattr(self, '_results_collapsed', False):
            self._reset_results_split()

    def _reset_results_split(self):
        """结果区占约 38% 高度（小窗口下也给画布留出空间）"""
        h = max(230, int(self.vsplit.height() * 0.38))
        self.vsplit.setSizes([max(1, self.vsplit.height() - h), h])

    def _step_done(self, i):
        """该步是否已完成（用于步骤条打勾）"""
        try:
            if i == 0:
                return self.gray is not None
            if i == 1:
                return bool(self.void_marks)
            if i == 2:
                return self.roi_mask is not None
            if i == 3:
                return (self.px_per_um or 0) > 0
            if i == 4:
                return self.model is not None
        except Exception:
            return False
        return False

    def _refresh_step_states(self):
        """步骤条显示 ›当前 / √已完成"""
        cur = getattr(self, '_teach_step', 0)
        for i, b in enumerate(getattr(self, 'step_buttons', [])):
            mark = '› ' if i == cur else ('√ ' if self._step_done(i) else '·  ')
            b.setText(f"{mark}{self.STEP_TITLES[i]}")

    def set_teach_step(self, i):
        """切到示教第 i 步（只展开该步）"""
        self._teach_step = int(i)
        for k, b in enumerate(self.step_buttons):
            b.setChecked(k == self._teach_step)
        self._apply_step_visibility()
        self._refresh_step_states()
        if getattr(self, '_mode', 'teach') != 'teach':
            self._set_mode_teach()

    def _apply_step_visibility(self):
        cur = getattr(self, '_teach_step', 0)
        for k, c in enumerate(getattr(self, '_step_containers', [])):
            c.setVisible(k == cur)

    def _connect(self):
        self.canvas.roi_poly_finished.connect(self.on_poly_roi)
        self.canvas.roi_polygon_edited.connect(self.on_poly_edited)
        self.canvas.calib_drawn.connect(self.on_calib_drawn)
        self.canvas.teach_void_at.connect(self._on_canvas_void_click)
        self.canvas.void_delete_at.connect(self._on_canvas_void_delete)

    def _on_canvas_void_click(self, x, y):
        """画布点选分流：批量核对模式 → 往当前预览图加空洞；否则 → 示教点选"""
        if self._add_void_mode:
            self._preview_add_void(x, y)
        else:
            self.on_teach_void(x, y)

    def _on_canvas_void_delete(self, x, y):
        """画布删除分流：批量核对模式下点空洞即删"""
        if self._del_void_mode:
            self._preview_delete_void(x, y)

    # ================== ① 上传样板图 ==================

    def load_sample(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择样板图", "",
            "图像文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;所有文件 (*)")
        if not path:
            return
        img = read_image_file(path)
        if img is None:
            show_warning(self, "错误", "图片加载失败")
            return
        self.img_cv = img
        self.gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self.sample_path = path
        self.canvas.set_image(img)

        # 重置示教状态
        self.roi_mask = None
        self.roi_polygon_pts = []
        self.void_marks = []
        self.void_blobs = []
        self.pixel_scale = 0.0
        self.bar_info = None
        self._adopt_teach_model(None, None)
        self.recipe_name = None
        self.btn_save_recipe.setEnabled(False)
        self.btn_poly.setChecked(False)
        self.btn_teach_void.setChecked(False)
        self.btn_calib.setChecked(False)
        self.canvas.set_teach_void_mode(False)
        self.canvas.set_roi_edit_enabled(False)
        self.canvas.clear_roi_polygon()
        self.canvas.overlay_mask = None
        self.canvas.draw_voids = []
        self.canvas.void_rate_text = ""
        self.canvas.calib_line = None      # 清掉上一张图的标定线，避免误读为已标定
        self.canvas.update()
        self.btn_edit_roi.setChecked(False)
        self._refresh_marks_list()
        self._refresh_labels()

    # ================== ② 焊层区域 ==================

    def auto_draft_roi(self):
        """由空洞点选锚定，自动草拟焊层带，用户再微调

        原理：用户点选的空洞必在焊层带内部。以空洞核心外扩的环形带为
        "焊层类"、远处像素为"背景类"，求两类分离阈值（与示教模型同一
        逻辑），再按该阈值定位焊层带。纯亮度判据分不开"亮基质+暗孔"的
        焊层带与均匀亮的邻近区，而空洞锚点可以。
        """
        if self.gray is None:
            show_info(self, "提示", "请先上传样板图")
            return
        self.btn_poly.setChecked(False)
        self.canvas.mode = 'none'

        if not self.void_blobs:
            show_info(
                self, "提示",
                "请先在图上点选 2 个以上典型空洞（②）——程序据此圈定焊层带；\n"
                "也可以直接用「多边形手绘」。")
            return

        cores = np.zeros(self.gray.shape, dtype=np.uint8)
        for blob in self.void_blobs:
            cores = cv2.bitwise_or(cores, blob)
        k_ring = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (51, 51))
        k_far = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (121, 121))
        ring = cv2.bitwise_and(cv2.dilate(cores, k_ring),
                               cv2.bitwise_not(cores))
        far = cv2.dilate(cores, k_far)
        bg = cv2.bitwise_and(cv2.bitwise_not(far),
                             np.full(self.gray.shape, 255, dtype=np.uint8))
        hist_ring = np.bincount(self.gray[ring > 0].ravel(), minlength=256)[:256]
        hist_bg = np.bincount(self.gray[bg > 0].ravel(), minlength=256)[:256]
        t_anchor = two_class_threshold(hist_ring, hist_bg)

        band = None
        if t_anchor is not None:
            band, diag = locate_solder_band(self.gray, t_anchor)
        if band is None:
            # 锚点阈值失效时退回到多候选尝试
            h, w = self.gray.shape
            best = None
            for t in [otsu_threshold(self.gray),
                      float(np.percentile(self.gray, 90)),
                      float(np.percentile(self.gray, 93))]:
                b, d = locate_solder_band(self.gray, t)
                if b is None:
                    continue
                frac = cv2.countNonZero(b) / float(h * w)
                if 0.01 <= frac <= 0.60:
                    best = b
                    break
            band = best
        if band is None:
            show_warning(
                self, "提示", "未找到焊层带，请用「多边形手绘」框选")
            return
        pts = self._mask_to_polygon(band)
        if len(pts) < 3:
            show_warning(self, "提示", "轮廓提取失败，请改用手绘")
            return
        self._set_roi(pts, band)

    def start_poly_roi(self):
        if self.gray is None:
            show_info(self, "提示", "请先上传样板图")
            self.btn_poly.setChecked(False)
            return
        self.btn_teach_void.setChecked(False)
        self.btn_calib.setChecked(False)
        self.canvas.set_teach_void_mode(False)
        self.canvas.mode = 'poly'
        self.canvas.current_points = []
        self.canvas.set_roi_edit_enabled(False)
        self.canvas.update()

    def _set_roi(self, pts, mask=None):
        """设置焊层区域（多边形 + 掩码），进入顶点编辑态"""
        self.roi_polygon_pts = [(float(x), float(y)) for x, y in pts]
        if mask is not None:
            self.roi_mask = mask
        else:
            self.roi_mask = polygon_to_mask(self.roi_polygon_pts, self.gray.shape)
        self.canvas.set_roi_polygon(self.roi_polygon_pts)
        self.canvas.set_roi_edit_enabled(True)
        self._render_roi_overlay()
        self._refresh_labels()

    def on_poly_roi(self, points):
        """手绘多边形完成"""
        if len(points) < 3:
            return
        self.btn_poly.setChecked(False)
        self.canvas.mode = 'none'
        self._set_roi(points)

    def on_poly_edited(self, points):
        """顶点编辑后同步（示教焊层区域 / 批量单图修正 两种上下文）"""
        if len(points) < 3 or self.gray is None:
            return
        pts = [(float(x), float(y)) for x, y in points]
        if self.preview_row is not None and self.btn_edit_band.isChecked():
            # 批量单图修正：改的是该张图的焊层区域（改为人工轮廓口径）
            self._edit_polygon = pts
            self._edit_mask = polygon_to_mask(pts, self._preview_gray.shape)
            self._poly_touched = True
            self._render_edit_band_overlay()
            return
        self.roi_polygon_pts = pts
        self.roi_mask = polygon_to_mask(self.roi_polygon_pts, self.gray.shape)
        self._render_roi_overlay()
        self._refresh_labels()

    def toggle_edit_roi(self):
        """示教焊层区域进入/退出顶点编辑（自动草拟与手绘共用）"""
        if self.gray is None or self.roi_mask is None:
            show_info(self, "提示", "请先自动识别或手绘焊层区域")
            self.btn_edit_roi.setChecked(False)
            return
        on = self.btn_edit_roi.isChecked()
        if on:
            self.btn_poly.setChecked(False)
            self.btn_teach_void.setChecked(False)
            self.btn_calib.setChecked(False)
            self.canvas.set_teach_void_mode(False)
            self.canvas.mode = 'none'
        self.canvas.set_roi_edit_enabled(on)

    def _render_mask_overlay(self, mask, alpha=90):
        """把二值掩码渲染成画布绿色蒙版"""
        if mask is None:
            return
        h, w = mask.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[mask == 255] = [16, 185, 129, alpha]
        self.canvas.overlay_mask = QImage(
            rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        self.canvas.update()

    def _render_roi_overlay(self):
        self._render_mask_overlay(self.roi_mask)

    # ================== ③ 点选空洞 ==================

    def toggle_teach_void(self):
        if self.gray is None:
            show_info(self, "提示", "请先上传样板图")
            self.btn_teach_void.setChecked(False)
            return
        on = self.btn_teach_void.isChecked()
        if on:
            self.btn_poly.setChecked(False)
            self.btn_calib.setChecked(False)
            self.canvas.mode = 'none'
            self.canvas.set_roi_edit_enabled(False)
        self.canvas.set_teach_void_mode(on)

    def on_teach_void(self, x, y):
        """点击抓取局部暗核，加入示范集合

        不需要先定义焊层区域——空洞点选是焊层带的定位锚点（见 auto_draft_roi）。
        参考阈值取点击处局部 patch 的 p85（该处焊层亮度）。
        """
        if self.gray is None:
            return
        h_img, w_img = self.gray.shape
        x1, y1 = max(0, int(x) - 40), max(0, int(y) - 40)
        x2, y2 = min(w_img, int(x) + 40), min(h_img, int(y) + 40)
        if x2 - x1 < 5 or y2 - y1 < 5:
            return
        t_ref = float(np.percentile(self.gray[y1:y2, x1:x2], 85))
        blob, area = grab_local_dark_blob(self.gray, x, y, t_ref)
        if blob is None:
            show_info(self, "提示", "该位置未抓到暗核，请点空洞中心")
            return
        self.void_marks.append((float(x), float(y)))
        self.void_blobs.append(blob)
        self._render_teach_marks()
        self._refresh_marks_list()
        self._refresh_labels()

    def _refresh_marks_list(self):
        """刷新已点选空洞列表（显示序号与面积，便于删掉选错的那个）"""
        self.list_marks.clear()
        for i, blob in enumerate(self.void_blobs):
            area = int(cv2.countNonZero(blob))
            it = QListWidgetItem(f"空洞 {i + 1}  ·  {area} px²")
            it.setData(Qt.ItemDataRole.UserRole, i)
            self.list_marks.addItem(it)
        self.btn_del_mark.setEnabled(bool(self.void_blobs))

    def delete_selected_mark(self):
        """删除列表中选中的那一个点选（防选错）"""
        item = self.list_marks.currentItem()
        if item is None:
            show_info(self, "提示", "请先在列表中选择要删除的空洞")
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if not (0 <= idx < len(self.void_blobs)):
            return
        del self.void_marks[idx]
        del self.void_blobs[idx]
        self._render_teach_marks()
        self._refresh_marks_list()
        self._refresh_labels()

    def _render_teach_marks(self):
        """把已点选暗核按 draw_voids 格式渲染（红块+编号）"""
        draw = []
        for i, blob in enumerate(self.void_blobs):
            cnts, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                continue
            cnt = max(cnts, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(cnt)
            draw.append({
                'id': i + 1,
                'area_px': float(cv2.contourArea(cnt)),
                'rect': (int(x), int(y), int(w), int(h)),
                'cx': float(x + w / 2), 'cy': float(y + h / 2),
                'points': cnt.reshape(-1, 2).tolist(),
            })
        self.canvas.draw_voids = draw
        self.canvas.show_labels = True
        self.canvas.fill_voids = self.chk_fill.isChecked()
        self.canvas.update()

    def confirm_clear_marks(self):
        if self.void_marks and not confirm_action(
                self, '清除全部点选',
                '将删除全部已点选的空洞标记，并重新学习。\n此操作不可撤销。'):
            return False
        self.clear_void_marks()
        return True

    def clear_void_marks(self):
        self.void_marks = []
        self.void_blobs = []
        self.canvas.draw_voids = []
        self.canvas.update()
        self._refresh_marks_list()
        self._refresh_labels()

    # ================== ④ 标定比例尺 ==================

    def start_calib(self):
        if self.gray is None:
            show_info(self, "提示", "请先上传样板图")
            self.btn_calib.setChecked(False)
            return
        self.btn_poly.setChecked(False)
        self.btn_teach_void.setChecked(False)
        self.canvas.set_teach_void_mode(False)
        self.canvas.mode = 'calibration'

    def on_calib_drawn(self, p1, p2):
        """比例尺划线完成：输入实际值 → 记录 px/μm + 条棒模板 patch"""
        self.btn_calib.setChecked(False)
        self.canvas.mode = 'none'
        dist_px = float(np.hypot(p2.x() - p1.x(), p2.y() - p1.y()))
        if dist_px < 5:
            show_warning(self, "提示", "标定线太短，请重画")
            return
        dialog = QInputDialog(self)
        dialog.setWindowTitle("标定比例尺")
        dialog.setLabelText("输入该线段代表的实际长度 (μm):")
        dialog.setDoubleRange(0.01, 100000)
        dialog.setDoubleStep(0.1)
        dialog.setDoubleValue(10.0)
        if not dialog.exec():
            return
        real_um = dialog.doubleValue()
        if real_um <= 0:
            return
        self.pixel_scale = dist_px / real_um

        # 条棒模板：以划线为中心取 patch（比例尺自动识别用）
        h, w = self.gray.shape
        horizontal = abs(p2.y() - p1.y()) <= abs(p2.x() - p1.x())
        x1, x2 = sorted([p1.x(), p2.x()])
        y1, y2 = sorted([p1.y(), p2.y()])
        pad_x, pad_y = 12, 14
        tx1 = max(0, int(x1) - pad_x)
        ty1 = max(0, int(y1) - pad_y)
        tx2 = min(w, int(x2) + pad_x)
        ty2 = min(h, int(y2) + pad_y)
        template = self.gray[ty1:ty2, tx1:tx2].copy()
        # 条棒明暗：划线中点附近像素与全图中位数比较
        mx, my = int((x1 + x2) / 2), int((y1 + y2) / 2)
        sample = self.gray[max(0, my - 3):my + 4, max(0, mx - 3):mx + 4]
        img_med = float(np.median(self.gray))
        dark = bool(sample.size and float(np.median(sample)) <= img_med)
        self.bar_info = {
            'template': template,
            'length_px': dist_px,
            'real_um': real_um,
            'horizontal': horizontal,
            'dark': dark,
        }
        self.canvas.calib_line = (p1, p2, f"{real_um} μm")
        self.canvas.update()
        self._refresh_labels()

    # ================== ⑤ 学习与保存 ==================

    def on_learn(self):
        if self.gray is None or self.roi_mask is None:
            show_info(self, "提示", "请先完成 ① 上传 和 ③ 焊层区域示范")
            return
        if not self.void_marks:
            show_info(self, "提示", "请先点选至少 1 个典型空洞（②）")
            return
        # 一致性过滤：主体在焊层带外的点选（误点到邻区）不计入空洞类
        kept_marks, kept_blobs, dropped = [], [], 0
        for mark, blob in zip(self.void_marks, self.void_blobs):
            overlap = cv2.countNonZero(cv2.bitwise_and(blob, self.roi_mask))
            total = cv2.countNonZero(blob)
            if total > 0 and overlap >= total * 0.5:
                kept_marks.append(mark)
                kept_blobs.append(blob)
            else:
                dropped += 1
        if not kept_marks:
            show_warning(
                self, "提示", "所有点选都不在焊层带内，请检查 ② 的点选位置")
            return
        if dropped:
            show_info(
                self, "提示", f"有 {dropped} 个点选不在焊层带内，已忽略")
        model = learn_taught_model(
            self.gray, self.roi_mask, kept_marks,
            px_per_um=self.pixel_scale,
            bar_length_px=(self.bar_info or {}).get('length_px', 0.0),
            bar_real_um=(self.bar_info or {}).get('real_um', 0.0),
            bar_horizontal=(self.bar_info or {}).get('horizontal', True),
            bar_dark=(self.bar_info or {}).get('dark', True),
            void_blobs=kept_blobs)
        if model is None:
            show_warning(self, "错误", "学习失败，请检查焊层区域示范是否有效")
            return
        model['name'] = self.recipe_name or "未命名示教"
        self._adopt_teach_model(model, 'teach')

        # 预览：在样板图上回放
        res = apply_taught_model(self.gray, model)
        if not res.get('ok'):
            show_warning(self, "提示",
                                f"学习完成，但在样板图上未定位到焊层带：{res.get('warnings')}")
            return
        self._render_preview(res)
        self.btn_save_recipe.setEnabled(True)
        sep = model['diagnostics'].get('solder_bg_separability') or 0
        sol = model['solder']
        same_frac = model['diagnostics'].get('bg_same_gray_frac') or 0
        tip = (f"焊层亮度≈{sol['median']:.0f}（{sol['p5']:.0f}~{sol['p95']:.0f}）  "
               f"t_焊层={sol['threshold']:.0f}  "
               f"t_空洞={model['void']['threshold']:.0f}  "
               f"可分性={sep:.1f}")
        if sep < 1.5:
            tip += "（可分性偏低，示范可能不充分）"
        if same_frac > 0.5:
            tip += "（周边过半像素与焊料同灰度，已自动剔除；若识别仍不准，请把示范区域画得更贴合焊层）"
        self.lbl_learn.setText(f"学习完成：{tip}")
        self.set_teach_step(4)      # 学习完成后停在 ⑤
        self._refresh_step_states()
        # 展示"学习过程"窗口（做了什么、得到什么参数）
        try:
            from learn_dialog import LearnReportDialog, build_learn_items
            preview = self.canvas.grab()
            dlg = LearnReportDialog(build_learn_items(model), preview=preview,
                                    title="学习过程与参数", parent=self)
            dlg.exec()
        except Exception as e:
            show_info(self, "学习完成",
                                    f"学习完成（过程窗口打开失败：{e}）")

    def _render_preview(self, res):
        """样板图上回放：绿掩码 + 空洞标注 + 空洞率"""
        self._render_mask_overlay(res['band_mask'])
        draw = []
        for v in res['voids']:
            draw.append({'id': v['id'], 'area_px': v['area_px'],
                         'rect': v['rect'], 'cx': v['cx'], 'cy': v['cy'],
                         'points': v['points']})
        self.canvas.draw_voids = draw
        self.canvas.show_labels = True
        self.canvas.fill_voids = self.chk_fill.isChecked()
        self.canvas.void_rate_text = f"空洞率：{res['void_rate'] * 100:.2f}%"
        self.canvas.update()

    def on_save_recipe(self):
        if self.model is None:
            return
        name, ok = QInputDialog.getText(
            self, "保存示教配方", "配方名称:", text=self.recipe_name or "")
        if not ok:
            return
        name = name.strip()
        if not name:
            show_warning(self, "提示", "配方名称不能为空")
            return
        self.recipe_name = name
        self.model['name'] = name
        self.model['note'] = (f"样板图：{os.path.basename(self.sample_path)}"
                              if self.sample_path else "")
        self.model['updated'] = datetime.now().isoformat(timespec='seconds')
        try:
            save_taught(self.model,
                        bar_template=(self.bar_info or {}).get('template'))
        except Exception as e:
            show_warning(self, "错误", f"保存失败：{e}")
            return
        self.refresh_recipe_combo()
        self._select_recipe(name)
        show_toast(self, f"示教配方「{name}」已保存")

    # ================== 批量检测 ==================

    def refresh_recipe_combo(self):
        current = self.combo_recipe.currentData()
        self.combo_recipe.blockSignals(True)
        self.combo_recipe.clear()
        for disp, fn in list_recipes(kind='taught'):
            self.combo_recipe.addItem(disp, fn)
        if current:
            idx = self.combo_recipe.findData(current)
            if idx >= 0:
                self.combo_recipe.setCurrentIndex(idx)
        self.combo_recipe.blockSignals(False)

    def pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择批次文件夹")
        if folder:
            self.load_folder(folder)

    def load_folder(self, folder):
        """载入批次文件夹（选择对话框与「最近打开」共用）。"""
        if not os.path.isdir(folder):
            return False
        paths = []
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return False
        for fn in names:
            if fn.lower().endswith(IMG_EXTS):
                paths.append(os.path.join(folder, fn))
        if not paths:
            show_info(self, "提示", "该文件夹下没有图片文件")
            return False
        self.batch_paths = paths
        self.batch_dir = folder
        self.lbl_folder.setText(f"已选择 {len(paths)} 张：{os.path.basename(folder)}")
        # 换批次文件夹 → 清掉上一次的快速示教模型（避免误用到别的器件上）
        self.quick_cfg = None
        if self._model_source == 'quick':
            self._adopt_teach_model(None, None)
        self.lbl_quick_teach.setText("")
        # 复用：若配方库里已有"与该文件夹同名"的配方，自动选中并提示（省去重新示教）
        name = os.path.basename(os.path.normpath(folder))
        if self._select_recipe(name):
            self.lbl_quick_teach.setText(
                f"已自动带出同名配方「{name}」——可直接开始批量；"
                f"要重做就点上方「快速示教（两步）」")
        window = self.window()
        if hasattr(window, 'remember_recent_batch'):
            window.remember_recent_batch(folder)
        return True

    # ================== 快速设定（免示教路径） ==================

    def _pick_setup_image(self, max_probe=12):
        """挑一张代表性图用于快速示教：p90 最接近整批中位数的那张

        直接取第一张有坑：批次里常有"总览/空白"图（p90 明显偏低），
        拿它示教出来的阈值套整批会严重偏低。抽样比较 p90，取最接近中位数的那张；
        并**优先纯数字命名的切片**（N-1.jpg / A.jpg 这类变体或总览图不作基准）。
        """
        paths = self.batch_paths
        if not paths:
            return None
        if len(paths) <= 1:
            return paths[0]
        numeric = [p for p in paths
                   if os.path.splitext(os.path.basename(p))[0].isdigit()]
        if len(numeric) >= 3:
            paths = numeric
        step = max(1, len(paths) // int(max_probe))
        sample = paths[::step][:int(max_probe)]
        vals = []
        for p in sample:
            img = read_image_file(p)
            if img is None:
                continue
            g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            vals.append((float(np.percentile(g, 90)), p))
        if not vals:
            return paths[0]
        med = float(np.median([v for v, _ in vals]))
        vals.sort(key=lambda t: abs(t[0] - med))
        return vals[0][1]

    def _teach_candidates(self, cap=80):
        """本批次可用于示教的图（优先纯数字切片；最多 cap 张）"""
        paths = list(self.batch_paths or [])
        numeric = [p for p in paths
                   if os.path.splitext(os.path.basename(p))[0].isdigit()]
        return (numeric or paths)[:int(cap)]

    def on_quick_teach(self):
        """快速示教（两步）：自动挑代表性图 → 弹窗（焊层区域已自动识别 + 点选空洞）→ 整批复用"""
        if not self.batch_paths:
            show_info(self, "提示", "请先选择批次文件夹")
            return
        setup_path = self._pick_setup_image()
        if not setup_path:
            show_warning(self, "错误", "无法选出用于示教的图片")
            return
        img = read_image_file(setup_path)
        if img is None:
            show_warning(self, "错误", f"图片读取失败：{os.path.basename(setup_path)}")
            return
        gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        try:
            from quick_teach_dialog import QuickTeachDialog
        except Exception as e:
            show_warning(self, "错误", f"快速示教模块不可用：{e}")
            return
        suggest = os.path.basename(os.path.normpath(getattr(self, 'batch_dir', '') or ''))
        candidates = self._teach_candidates()
        # 允许用户"更换示教图片"：换完重开对话框（约定返回码 Accepted+100）
        SWITCH = QDialog.DialogCode.Accepted + 100
        while True:
            img_i = read_image_file(setup_path)
            if img_i is None:
                show_warning(self, "错误", "图片读取失败：" + setup_path)
                return
            gray_i = img_i if img_i.ndim == 2 else cv2.cvtColor(img_i, cv2.COLOR_BGR2GRAY)
            dlg = QuickTeachDialog(
                gray_i, sample_name=os.path.basename(setup_path), parent=self,
                title=f"快速示教：{os.path.basename(setup_path)}"
                      f"（整批共 {len(self.batch_paths)} 张）",
                suggest_name=suggest, candidates=candidates,
                current_path=setup_path)
            rc = dlg.exec()
            if rc == SWITCH and getattr(dlg, 'picked_path', None):
                setup_path = dlg.picked_path          # 用户换了基准图 → 用新图重开
                continue
            break
        if rc != QDialog.DialogCode.Accepted or dlg.get_model() is None:
            return
        self.quick_cfg = None
        self._adopt_teach_model(dlg.get_model(), 'quick')
        # 存过配方就刷新下拉框并选中它，方便以后一键复用
        if getattr(dlg, 'saved_name', None):
            self.refresh_recipe_combo()
            self._select_recipe(dlg.saved_name)
            self.lbl_quick_teach.setText(
                f"已学并保存为配方「{dlg.saved_name}」——以后选同一批次文件夹会自动带出，"
                f"也可在下拉框直接选用；本次已直接用于整批 √")
        else:
            self._show_quick_label()

    def _show_quick_label(self):
        """底部提示条：显示当前快速示教模型的阈值与示例图统计"""
        m = self.quick_model
        if not m:
            self.lbl_quick_teach.setText("")
            return
        sol = (m.get('solder') or {}).get('threshold', 0)
        voi = (m.get('void') or {}).get('threshold', 0)
        n_pick = 0
        try:
            n_pick = int((m.get('note') or '').split('点选')[1].split('个')[0])
        except Exception:
            pass
        self.lbl_quick_teach.setText(
            f"快速示教已生效：t_焊层={sol:.0f}　t_空洞={voi:.0f}　点选 {n_pick} 个空洞"
            f"　（点上方按钮可重做）")

    def start_batch(self):
        # 当前示教模型优先（快速/完整示教统一到 self.model）：有模型就不再要求配方
        if self.model is not None:
            fn, model, bar_template = None, self.model, None
        else:
            fn = self.combo_recipe.currentData()
            if not fn:
                show_info(
                    self, "提示",
                    "请先选择示教配方，或点「快速示教（弹窗）」/「快速设定（免示教）」")
                return
            model = load_recipe(fn)
            if model is None or model.get('type') != 'taught':
                show_warning(self, "错误", "配方读取失败或不是示教配方")
                self.refresh_recipe_combo()
                return
            bar_template = load_bar_template(fn)
        if not self.batch_paths:
            show_info(self, "提示", "请先选择批次文件夹")
            return

        self.batch_results = []
        self.result_edits = {}
        self.preview_row = None
        self._reset_edit_modes()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._clear_thumbs()
        self.lbl_total.setText("总空洞率：—")
        self.lbl_stats.setText("块均值：—")
        self.btn_export.setEnabled(False)
        self.progress.setValue(0)
        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.preview_row = None
        self._batch_canceled = False
        self.lbl_preview.setText("预览：批量进行中…（点缩略图或表格行查看）")
        # 缓存本次批量的模型与比例尺模板，预览/导出标注图时按需重算
        self._last_model = model
        self._last_bar_template = bar_template
        # 空洞判定设置：派生模型（不改原配方）
        model = self._sens_model() or model
        if getattr(self, '_sens_changed', None):
            self.lbl_current.setText("已调整：" + "、".join(self._sens_changed))
        # 结果区就位（批量模式下可见）
        self._set_mode_batch()

        self.worker = BatchWorker(self.batch_paths, model, bar_template)
        self.worker.progress.connect(self.on_progress)
        self.worker.tile_done.connect(self.on_tile_done)
        self.worker.finished.connect(self.on_batch_finished)
        self.worker.failed.connect(self.on_batch_failed)
        self.worker.start()

    def cancel_batch(self):
        if self.worker is not None:
            self._batch_canceled = True
            self.worker.cancel()
            self.lbl_current.setText("正在取消...")

    def on_progress(self, idx, total, filename):
        self.progress.setValue(int(idx / max(total, 1) * 100))
        self.lbl_current.setText(f"{idx}/{total}  {filename}")

    def on_tile_done(self, r):
        row = self.table.rowCount()
        self.table.insertRow(row)
        rate = (f"{r['void_rate'] * 100:.2f}" if r.get('ok') else '—')
        area = (f"{r['solder_area_px']}" if r.get('ok') else '—')
        cnt = (f"{r['void_count']}" if r.get('ok') else '—')
        warn = '；'.join(r.get('warnings') or [])
        values = (r.get('filename', ''), area, cnt, rate, warn)
        sort_values = (row,
                       r.get('solder_area_px', -1) if r.get('ok') else -1,
                       r.get('void_count', -1) if r.get('ok') else -1,
                       r.get('void_rate', -1) if r.get('ok') else -1,
                       warn)
        for column, value in enumerate(values):
            if column in (1, 2, 3):
                item = NumericItem(value, sort_values[column])
                align_right(item)
            else:
                item = QTableWidgetItem(value)
            if warn:
                item.setBackground(QColor(254, 249, 195))
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(row, column, item)
        self._add_thumb(row, r)

    def _view_row(self, original):
        """原始结果序号 → 当前视图行（用户按列排序后仍能定位）。"""
        for view in range(self.table.rowCount()):
            item = self.table.item(view, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == original:
                return view
        return original if 0 <= original < self.table.rowCount() else -1

    def _on_table_cell_clicked(self, view_row, _column):
        item = self.table.item(view_row, 0)
        try:
            original = int(item.data(Qt.ItemDataRole.UserRole))
        except (AttributeError, TypeError, ValueError):
            original = view_row
        self.preview_result(original)

    def on_batch_finished(self, results):
        self.batch_results = results
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_export.setEnabled(bool(results))
        self.progress.setValue(100)
        self.lbl_current.setText(
            f"{'已取消，' if self._batch_canceled else '完成'} "
            f"{len(results)}/{len(self.batch_paths)} 张")

        ok = [r for r in results if r.get('ok') and r.get('solder_area_px')]
        if ok:
            self._update_summary()
        if getattr(self, '_results_collapsed', False):
            self._toggle_results_collapse()
        else:
            self._reset_results_split()

        # 自动跳到最该核查的一张：优先第一张异常，其次第一张正常
        target = None
        for i, r in enumerate(results):
            if not (r.get('ok') and not (r.get('warnings') or [])):
                target = i
                break
        if target is None and results:
            target = 0
        if target is not None:
            self.preview_result(target)

        if self._batch_canceled:
            show_info(
                self, "已取消",
                f"批量已取消，已完成 {len(results)}/{len(self.batch_paths)} 张\n"
                f"（结果在下方结果区：点缩略图或表格行可逐张核对）")
        else:
            show_info(
                self, "完成",
                f"批量检测完成：{len(results)} 张\n"
                f"结果在下方结果区：点缩略图（异常描红边）或表格行即可放大核对与修正；\n"
                f"汇总信息见结果区顶部，可导出 CSV / 单图标注 / 汇总大图。")

    def _sens_text(self):
        """当前空洞判设置的紧凑描述（用于折叠区标题与汇总大图）"""
        parts = [
            '下限' + ('自动' if self.chk_min_auto.isChecked()
                      else f"{self.spin_min.value()}px²"),
            '上限' + ('自动' if self.chk_max_auto.isChecked()
                      else f"{self.spin_max.value()}px²"),
            f"容差{self.spin_depth.value():+d}",
        ]
        return '　'.join(parts)

    def _on_sens_changed(self):
        """自动勾选联动：勾上自动就禁用数值框，状态显示在折叠区标题上"""
        auto_min = self.chk_min_auto.isChecked()
        auto_max = self.chk_max_auto.isChecked()
        self.spin_min.setEnabled(not auto_min)
        self.spin_max.setEnabled(not auto_max)
        sec = getattr(self, 'sens_section', None)
        if sec is not None:
            sec.toggle_btn.setText(f"空洞判定：{self._sens_text()}")

    def _sens_model(self):
        """按左栏的空洞判定设置派生模型（不修改原配方）

        三项都可由用户用数值指定：面积下限/上限（各有"自动"档，按带面积定）、
        深度容差（空洞阈值偏移，正值更包容）。用于"明明有空洞却检不出"时放宽。
        """
        base = self._last_model or self.model
        if base is None:
            return None
        m = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
        vcfg = dict(m.get('void') or {})
        changed = []
        if self.chk_min_auto.isChecked():
            vcfg['min_area'] = 0
        else:
            vcfg['min_area'] = int(self.spin_min.value())
            changed.append(f"下限{self.spin_min.value()}px²")
        if self.chk_max_auto.isChecked():
            vcfg['max_area'] = None
        else:
            vcfg['max_area'] = int(self.spin_max.value())
            changed.append(f"上限{self.spin_max.value()}px²")
        depth = float(self.spin_depth.value())
        vcfg['depth_offset'] = depth
        if depth:
            changed.append(f"深度容差{depth:+.0f}")
        m['void'] = vcfg
        self._sens_changed = changed
        return m

    def _add_thumb(self, row, r=None):
        """给结果区胶片条追加一个缩略图按钮

        批量进行中 self.batch_results 还没赋值，所以结果由调用方传入。
        """
        if r is None:
            if not (0 <= row < len(self.batch_results)):
                return
            r = self.batch_results[row]
        btn = QToolButton()
        btn.setObjectName("ThumbBtn")
        btn.setCheckable(True)
        btn.setAutoRaise(True)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        thumb = r.get('thumb')
        if thumb is not None and getattr(thumb, 'size', 0):
            arr = np.ascontiguousarray(thumb)
            qimg = QImage(arr.data, arr.shape[1], arr.shape[0], arr.strides[0],
                          QImage.Format.Format_BGR888).copy()
            btn.setIcon(QIcon(QPixmap.fromImage(qimg)))
            btn.setIconSize(QSize(arr.shape[1], arr.shape[0]))
        rate = f"{r.get('void_rate', 0) * 100:.1f}%" if r.get('ok') else '失败'
        btn.setText(f"{row + 1} · {rate}")
        btn.setToolTip(
            f"第 {row + 1} 张：{r.get('filename', '')}\n"
            f"空洞率 {rate}　空洞 {r.get('void_count', '—')} 个\n"
            f"{'；'.join(r.get('warnings') or []) or '无警告'}")
        if (not r.get('ok')) or r.get('warnings'):
            btn.setProperty('warn', True)
        btn.clicked.connect(lambda _=False, i=row: self.preview_result(i))
        self.thumb_row.addWidget(btn)

    def _mark_thumb_selected(self, row):
        for i in range(self.thumb_row.count()):
            w = self.thumb_row.itemAt(i).widget()
            if isinstance(w, QToolButton):
                w.setChecked(False)
        w = self.thumb_row.itemAt(row).widget() if row < self.thumb_row.count() else None
        if isinstance(w, QToolButton):
            w.setChecked(True)

    def _clear_thumbs(self):
        while self.thumb_row.count():
            it = self.thumb_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def on_batch_failed(self, msg):
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        show_warning(self, "错误", f"批量处理出错：{msg}")

    # ---------- 汇总 ----------

    def _summary_lines(self, for_sheet=False):
        """汇总统计（结果区与汇总大图共用）"""
        ok = [r for r in self.batch_results
              if r.get('ok') and r.get('solder_area_px')]
        if not ok:
            return []
        tot_solder = sum(r['solder_area_px'] for r in ok)
        tot_void = sum(float(r.get('void_area_px') or 0) for r in ok)
        rates = [r['void_rate'] * 100 for r in ok]
        cnts = [r['void_count'] for r in ok]
        px_um = next((r.get('px_per_um_used') for r in ok
                      if r.get('px_per_um_used')), 0.0) or 0.0
        f_um = (lambda a: f"（{a / (px_um ** 2):.0f} μm²）") if px_um > 0 else (lambda a: "")
        head = (f"总空洞率 {tot_void / tot_solder * 100:.2f}%　"
                f"共 {len(self.batch_results)} 张"
                f"（成功 {len(ok)}，异常 {len(self.batch_results) - len(ok)}"
                + (f"，人工修正 {len(self.result_edits)} 张）" if self.result_edits else "）"))
        mid = (f"块均值 {float(np.mean(rates)):.2f}% ± {float(np.std(rates)):.2f}　"
               f"空洞率范围 {min(rates):.2f}% ~ {max(rates):.2f}%　"
               f"空洞数 {min(cnts)} ~ {max(cnts)} 个")
        tail = (f"总焊锡面积 {tot_solder} px²{f_um(tot_solder)}　"
                f"总空洞面积 {tot_void:.0f} px²{f_um(tot_void)}　"
                f"最大单个空洞 {max(float(r.get('max_void_px') or 0) for r in ok):.0f} px²")
        if not for_sheet:
            return [head, mid, tail]
        return [head, mid, tail,
                f"配方：{self.combo_recipe.currentText() or '—'}　"
                f"空洞判定：{self._sens_text()}　"
                f"面积口径：检测掩码（人工修正的用人工轮廓）",
                f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"]

    def _sheet_layout_args(self):
        """汇总大图排版参数（来自界面上的排版下拉框）"""
        mode = self.combo_sheet.currentData() if hasattr(self, 'combo_sheet') else 'vertical'
        if mode == 'horizontal':
            return {'layout': 'horizontal'}
        if mode in ('grid2', 'grid3'):
            return {'layout': 'grid', 'cols': int(mode[-1])}
        return {'layout': 'vertical'}

    def export_summary_sheet(self):
        """导出"所有图纵向堆叠"的汇总大图，顶部带汇总统计"""
        if not self.batch_results:
            show_info(self, "提示", "请先完成批量检测")
            return
        if not any(r.get('ok') for r in self.batch_results):
            show_warning(self, "提示", "没有可导出的成功结果")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出汇总大图",
            # 默认名用中性 ASCII：部分公司加密/DLP 会按文件名关键词
            # （汇总/报表/报告…）自动加密，输出成"打不开的锁文件"
            f"Aurascope_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
            "PNG 图片 (*.png)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            entries = []
            for i, r in enumerate(self.batch_results):
                img, res = self._rerun_result(i)
                if img is None or res is None:
                    continue
                lines = [f"[{i + 1}] "] + self._annotated_lines(r, res)
                entries.append({
                    'img': img, 'band_mask': res['band_mask'],
                    'voids': res['voids'], 'lines': lines,
                    'warn': bool(r.get('warnings')) or not r.get('ok'),
                })
            sheet = render_summary_sheet(
                entries, self._summary_lines(for_sheet=True),
                sheet_width=1600, **self._sheet_layout_args())
            if sheet is None:
                show_warning(self, "提示", "汇总图生成失败")
                return
            if not self._save_png(path, sheet):
                show_warning(self, "汇总大图导出失败",
                                    self._last_save_error or "写入失败")
                return
        finally:
            QApplication.restoreOverrideCursor()
        real = path if path.lower().endswith('.png') else path + '.png'
        msg = (f"已导出汇总大图（{sheet.shape[1]}×{sheet.shape[0]}）\n{real}\n"
               f"大小 {self._kb(real)}")
        if getattr(self, '_last_save_warning', ''):
            msg += "\n\n" + self._last_save_warning
        show_info(self, "完成", msg)

    def _build_solder_strip(self):
        """重算每张图的金锡抠图并拼成横向大图；返回 (strip, err)"""
        if not self.batch_results:
            return None, "请先完成批量检测"
        if not any(r.get('ok') for r in self.batch_results):
            return None, "没有可导出的成功结果"
        entries = []
        for i, r in enumerate(self.batch_results):
            img, res = self._rerun_result(i)
            if img is None or res is None:
                continue
            entries.append({'img': img, 'band_mask': res['band_mask'],
                            'voids': res['voids']})
        strip = render_solder_strip(entries, self._summary_lines(for_sheet=True))
        if strip is None:
            return None, "金锡拼接图生成失败"
        return strip, ''

    def export_solder_strip(self):
        """把每张图的金锡区域抠出、按顺序横向拼接成一张大图

        区域外填黑（金锡多为浅色，黑底对比清晰），空洞仍用红色掩膜填充，
        左上角标注与汇总大图一致的统计信息。
        """
        if not self.batch_results:
            show_info(self, "提示", "请先完成批量检测")
            return
        if not any(r.get('ok') for r in self.batch_results):
            show_warning(self, "提示", "没有可导出的成功结果")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出金锡拼接图",
            f"Aurascope_solder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
            "PNG 图片 (*.png)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            strip, err = self._build_solder_strip()
            if strip is None:
                show_warning(self, "提示", err)
                return
            if not self._save_png(path, strip):
                show_warning(self, "金锡拼接图导出失败",
                                    self._last_save_error or "写入失败")
                return
        finally:
            QApplication.restoreOverrideCursor()
        real = path if path.lower().endswith('.png') else path + '.png'
        # 导出成功 → **顺便复制到剪贴板**（可直接 Ctrl+V 粘到 PPT/Word ✗）
        from ui_components import copy_bgr_to_clipboard
        ok_copy, why = copy_bgr_to_clipboard(strip, silent=True)
        msg = (f"已导出金锡拼接图（{strip.shape[1]}×{strip.shape[0]}）\n{real}\n"
               f"大小 {self._kb(real)}")
        msg += ("\n并已复制到剪贴板，可直接 Ctrl+V 粘贴 √" if ok_copy
                else f"\n（复制到剪贴板失败：{why}）")
        if getattr(self, '_last_save_warning', ''):
            msg += "\n\n" + self._last_save_warning
        show_info(self, "完成", msg)

    def view_solder_strip(self):
        """在窗口内预览金锡拼接图（可缩放 / 可另存）"""
        if not self.batch_results:
            show_info(self, "提示", "请先完成批量检测")
            return
        if not any(r.get('ok') for r in self.batch_results):
            show_warning(self, "提示", "没有可预览的成功结果")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            strip, err = self._build_solder_strip()
        finally:
            QApplication.restoreOverrideCursor()
        if strip is None:
            show_warning(self, "提示", err)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("金锡拼接图预览")
        dlg.resize(1040, 640)
        lo = QVBoxLayout(dlg)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(12)
        bar = QHBoxLayout()
        cap = create_info_label(
            f"{strip.shape[1]} × {strip.shape[0]} px　"
            f"（共 {sum(1 for r in self.batch_results if r.get('ok'))} 张）"
            f"　滚轮缩放 · 拖动平移 · 双击适应窗口")
        bar.addWidget(cap)
        bar.addStretch()
        btn_save = create_success_button("另存为 PNG")
        bar.addWidget(btn_save)
        lo.addLayout(bar)
        view = _StripView(cv2.cvtColor(strip, cv2.COLOR_BGR2RGB))
        lo.addWidget(view, 1)

        def _save():
            path, _ = QFileDialog.getSaveFileName(
                dlg, "另存金锡拼接图",
                f"Aurascope_solder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                "PNG 图片 (*.png)")
            if not path:
                return
            if self._save_png(path, strip):
                real = path if path.lower().endswith('.png') else path + '.png'
                show_info(dlg, "完成", f"已保存\n{real}")
            else:
                show_warning(dlg, "保存失败",
                                    self._last_save_error or "写入失败")

        btn_save.clicked.connect(_save)
        dlg.exec()

    def export_csv(self):
        if not self.batch_results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV",
            f"批量空洞率_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV (*.csv)")
        if not path:
            return
        rows = []
        for r in self.batch_results:
            if r.get('ok'):
                px_um = r.get('px_per_um_used') or 0.0
                area_um2 = (r['solder_area_px'] / (px_um ** 2)) if px_um > 0 else ''
                rows.append({
                    '图片': r.get('filename', ''),
                    '金锡面积(px²)': int(r['solder_area_px']),
                    '金锡面积(μm²)': round(area_um2, 1) if area_um2 != '' else '',
                    '空洞数': int(r['void_count']),
                    '空洞面积(px²)': round(r['void_area_px'], 1),
                    '空洞率(%)': round(r['void_rate'] * 100, 3),
                    't_空洞': round(r.get('t_void_used', 0), 1),
                    '空洞面积下限(px²)': r.get('min_area_used', ''),
                    '空洞面积上限(px²)': r.get('max_area_used', ''),
                    '未计入大暗斑数': r.get('above_max_area_count', 0),
                    '未计入小暗斑数': r.get('below_min_area_count', 0),
                    '比例尺识别': '是' if r.get('bar_found') else '否(用示范值)',
                    '厚度过滤剔除(%)': round(
                        (r.get('diagnostics') or {}).get('thin_removed_frac', 0) * 100, 3),
                    '面积口径': r.get('caliber') or '检测掩码',
                    '警告': '；'.join(r.get('warnings') or []),
                })
            else:
                rows.append({'图片': r.get('filename', ''),
                             '警告': '；'.join(r.get('warnings') or ['处理失败'])})
        ok = [r for r in self.batch_results if r.get('ok') and r.get('solder_area_px')]
        if ok:
            tot_solder = sum(r['solder_area_px'] for r in ok)
            tot_void = sum(r['void_area_px'] for r in ok)
            rates = [r['void_rate'] * 100 for r in ok]
            rows.append({'图片': '【汇总】',
                         '金锡面积(px²)': int(tot_solder),
                         '空洞面积(px²)': round(tot_void, 1),
                         '空洞率(%)': round(tot_void / tot_solder * 100, 3) if tot_solder else '',
                         '警告': f"均值{np.mean(rates):.2f}%±{np.std(rates):.2f}%"})
        write_csv(path, rows)
        show_toast(self, f"已导出 {len(rows)} 行")

    # ================== 结果预览与标注图导出 ==================

    def _rerun_result(self, row):
        """取某行的检测叠加（轻量结果里不含掩码/空洞点集）

        该行若被人工修正过，直接用修正后的区域掩码与空洞；否则按模型重算。
        面积口径始终 = 区域掩码的像素数（与你看到的绿色区域完全一致）。

        Returns:
            (img, res)；img 为原图，res 为含 band_mask/voids 的完整结果
        """
        if not (0 <= row < len(self.batch_results)):
            return None, None
        r = self.batch_results[row]
        path = r.get('path')
        if not path or not r.get('ok') or self._last_model is None:
            return None, None
        img = read_image_file(path)
        if img is None:
            return None, None
        gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edit = self.result_edits.get(row)
        if edit:
            band = edit.get('mask')
            if band is None:
                band = polygon_to_mask(edit.get('polygon') or [], gray.shape)
            voids = edit['voids']
            void_area = float(sum(v['area_px'] for v in voids))
            solder_area = int(cv2.countNonZero(band)) if band is not None else 0
            return img, {
                'ok': True, 'band_mask': band, 'voids': voids,
                'void_count': len(voids), 'void_area_px': void_area,
                'solder_area_px': solder_area,
                'void_rate': (void_area / solder_area) if solder_area else 0.0,
                't_void_used': r.get('t_void_used', 0.0),
                'deviation': r.get('deviation'),
                'warnings': r.get('warnings') or [], 'edited': True,
                'caliber': edit.get('caliber'),
            }
        res = apply_taught_model(gray, self._last_model)
        if not res.get('ok'):
            return img, None
        return img, res

    def preview_result(self, row, col=0):
        """在画布上预览某张批次图的检测叠加，并置为可编辑（人工核对/修正）"""
        if not self.batch_results or not (0 <= row < len(self.batch_results)):
            return
        r = self.batch_results[row]
        self.preview_row = row
        view_row = self._view_row(row)
        if view_row >= 0:
            self.table.selectRow(view_row)
        self._mark_thumb_selected(row)
        self._reset_edit_modes()
        if not r.get('ok'):
            self.lbl_preview.setText(
                f"预览：{r.get('filename', '')} — 处理失败"
                f"（{'；'.join(r.get('warnings') or [])}）")
            return
        img, res = self._rerun_result(row)
        if img is None:
            self.lbl_preview.setText("预览：图片读取失败或模型不可用")
            return
        if res is None:
            self.lbl_preview.setText(f"预览：{r['filename']} — 未能定位焊层带")
            return
        self._preview_gray = img if img.ndim == 2 else cv2.cvtColor(
            img, cv2.COLOR_BGR2GRAY)
        self.canvas.set_image(img)
        self.canvas.show_labels = self.chk_labels.isChecked()
        self.canvas.fill_voids = self.chk_fill.isChecked()
        # 区域掩码为面积口径权威来源；多边形仅供显示/拖拽编辑
        edit = self.result_edits.get(row)
        if edit:
            self._edit_mask = (edit.get('mask').copy()
                               if edit.get('mask') is not None else None)
            if self._edit_mask is None:
                self._edit_mask = polygon_to_mask(
                    edit.get('polygon') or [], self._preview_gray.shape)
            self._edit_voids = [dict(v) for v in edit['voids']]
        else:
            self._edit_mask = res['band_mask'].copy()
            self._edit_voids = [dict(v) for v in res['voids']]
        self._edit_polygon = self._mask_to_polygon(self._edit_mask)
        self._poly_touched = False
        self._baseline_voids = [(v['id'], round(float(v['area_px']), 3))
                                for v in self._edit_voids]
        self.canvas.set_roi_polygon(self._edit_polygon)
        self.canvas.set_roi_edit_enabled(False)     # 需用户点「编辑金锡区域」
        self._render_edit_band_overlay()
        self._render_edit_voids()
        self.canvas.void_rate_text = (
            f"空洞率 {res['void_rate'] * 100:.2f}%   ·   "
            f"空洞 {res['void_count']} 个   ·   金锡 {res['solder_area_px']}px²")
        self.canvas.update()
        self._refresh_preview_label(row, res)

    @staticmethod
    def _mask_to_polygon(mask, max_pts=120, eps=2.0):
        """掩码 → 显示/编辑用多边形

        用 Douglas-Peucker 按曲率布点：直线段少给点、弯折处多给点，
        比等弧长均分更省顶点且更保真；再套一个上限，避免边界起伏时顶点爆炸
        （焊层带边界有上百个起伏是常态）。顶点手柄在画布上按需显示
        （只高亮光标最近的），所以数量多也不影响可读性与抓取。
        """
        if mask is None:
            return []
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return []
        cnt = max(cnts, key=cv2.contourArea)
        approx = cv2.approxPolyDP(cnt, float(eps), True)
        pts = approx.reshape(-1, 2).astype(float).tolist()
        if len(pts) < 3:
            pts = cnt.reshape(-1, 2).astype(float).tolist()
        if len(pts) > max_pts:
            pts = resample_polygon_points(pts, max_pts)
        return pts

    def _refresh_preview_label(self, row, res):
        r = self.batch_results[row]
        parts = [f"预览：{r['filename']}   空洞率 {res['void_rate'] * 100:.2f}%"]
        if r.get('edited'):
            parts.append(f"【已人工修正 · 面积口径:{r.get('caliber') or '人工修正轮廓'}】")
        else:
            parts.append("面积口径:检测掩码")
        dev = r.get('deviation')
        if dev:
            parts.append(f"vs示教：偏移{dev['center_shift'] * 100:.0f}% "
                         f"面积×{dev['area_ratio']:.2f} 长宽×{dev['aspect_ratio']:.2f}")
        below = r.get('below_min_area_count') or 0
        above = r.get('above_max_area_count') or 0
        if below:
            parts.append(f"另有 {below} 个小暗斑未计入(<{r.get('min_area_used')}px²)")
        if above:
            parts.append(f"另有 {above} 个大暗斑未计入(>{r.get('max_area_used')}px²)")
        warn = '；'.join(r.get('warnings') or [])
        if warn:
            parts.append(f"! {warn}")
        self.lbl_preview.setText('   '.join(parts))

    def _render_edit_band_overlay(self):
        if self._edit_mask is None:
            return
        self._render_mask_overlay(self._edit_mask)

    def _render_edit_voids(self):
        self.canvas.draw_voids = [dict(v) for v in self._edit_voids]
        self.canvas.show_labels = self.chk_labels.isChecked()
        self.canvas.fill_voids = self.chk_fill.isChecked()
        self.canvas.update()

    # ---------- 单图核对与修正：模式开关 ----------

    def _reset_edit_modes(self):
        for b in (self.btn_edit_band, self.btn_add_void, self.btn_del_void):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self._add_void_mode = False
        self._del_void_mode = False
        self.canvas.set_teach_void_mode(False)
        self.canvas.set_void_edit_mode('none')
        self.canvas.set_roi_edit_enabled(False)

    def _require_preview(self):
        if self.preview_row is None or not self.batch_results:
            show_info(self, "提示", "请先点击结果表选中一行")
            return False
        return True

    def toggle_edit_band(self):
        if not self._require_preview():
            self.btn_edit_band.setChecked(False)
            return
        on = self.btn_edit_band.isChecked()
        if on:
            self.btn_add_void.setChecked(False)
            self.btn_del_void.setChecked(False)
            self._add_void_mode = False
            self._del_void_mode = False
            self.canvas.set_teach_void_mode(False)
            self.canvas.set_void_edit_mode('none')
        self.canvas.set_roi_edit_enabled(on)

    def toggle_add_void(self):
        if not self._require_preview():
            self.btn_add_void.setChecked(False)
            return
        on = self.btn_add_void.isChecked()
        if on:
            self.btn_edit_band.setChecked(False)
            self.btn_del_void.setChecked(False)
            self.canvas.set_roi_edit_enabled(False)
            self.canvas.set_void_edit_mode('none')
        self._add_void_mode = on
        self._del_void_mode = False
        self.canvas.set_teach_void_mode(on)


    def toggle_del_void(self):
        if not self._require_preview():
            self.btn_del_void.setChecked(False)
            return
        on = self.btn_del_void.isChecked()
        if on:
            self.btn_edit_band.setChecked(False)
            self.btn_add_void.setChecked(False)
            self.canvas.set_roi_edit_enabled(False)
            self.canvas.set_teach_void_mode(False)
        self._del_void_mode = on
        self._add_void_mode = False
        self.canvas.set_void_edit_mode('delete' if on else 'none')


    def toggle_void_display(self):
        self.canvas.show_labels = self.chk_labels.isChecked()
        self.canvas.fill_voids = self.chk_fill.isChecked()
        self.canvas.update()

    # ---------- 单图核对与修正：增删空洞 ----------

    def _preview_add_void(self, x, y):
        if self._preview_gray is None:
            return
        band = (polygon_to_mask(self._edit_polygon, self._preview_gray.shape)
                if self._edit_polygon else None)
        t_ref = 128.0
        if self._last_model is not None:
            t_ref = self._last_model['solder']['threshold']
        blob, area = grab_local_dark_blob(self._preview_gray, x, y, t_ref,
                                          region_mask=band)
        if blob is None:
            show_info(self, "提示", "该位置未抓到暗核（可能不在焊层带内）")
            return
        cnts, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return
        cnt = max(cnts, key=cv2.contourArea)
        x0, y0, w0, h0 = cv2.boundingRect(cnt)
        new_id = max([v['id'] for v in self._edit_voids], default=0) + 1
        self._edit_voids.append({
            'id': new_id, 'area_px': float(cv2.contourArea(cnt)),
            'rect': (int(x0), int(y0), int(w0), int(h0)),
            'cx': float(x0 + w0 / 2), 'cy': float(y0 + h0 / 2),
            'points': cnt.reshape(-1, 2).tolist(),
        })
        self._render_edit_voids()

    def _preview_delete_void(self, x, y):
        pt = (float(x), float(y))
        for i in range(len(self._edit_voids) - 1, -1, -1):
            pts = np.array(self._edit_voids[i]['points'], dtype=np.int32)
            if len(pts) >= 3 and cv2.pointPolygonTest(pts, pt, False) >= 0:
                del self._edit_voids[i]
                self._render_edit_voids()
                return

    # ---------- 单图核对与修正：应用 / 还原 ----------

    def apply_result_edit(self):
        """应用人工修正

        面积口径：**未拖过顶点**时用检测掩码（不受多边形近似影响）；
        **拖过顶点**时用人工轮廓，并在界面标注口径。
        """
        if not self._require_preview():
            return
        row = self.preview_row
        if not self._edit_polygon or len(self._edit_polygon) < 3:
            show_info(self, "提示", "焊层区域无效（至少 3 个顶点）")
            return
        band = self._edit_mask
        if band is None or cv2.countNonZero(band) == 0:
            show_info(self, "提示", "焊层区域无效")
            return
        r = self.batch_results[row]
        cur_voids = [(v['id'], round(float(v['area_px']), 3)) for v in self._edit_voids]
        base_voids = self._baseline_voids
        unchanged = (not self._poly_touched) and (cur_voids == base_voids)
        if unchanged:
            show_info(
                self, "提示",
                "没有改动（面积口径：检测掩码，与自动检测一致）")
            return
        caliber = '人工修正轮廓' if self._poly_touched else '检测掩码'
        if '_auto' not in r:      # 首次修正：留存自动结果快照，供「还原」用
            r['_auto'] = {k: r.get(k) for k in
                          ('solder_area_px', 'void_count', 'void_area_px',
                           'void_rate', 'caliber')}
        self.result_edits[row] = {
            'mask': band.copy(),
            'polygon': [(float(px), float(py)) for px, py in self._edit_polygon],
            'voids': [dict(v) for v in self._edit_voids],
            'caliber': caliber,
        }
        solder_area = int(cv2.countNonZero(band))
        void_area = float(sum(v['area_px'] for v in self._edit_voids))
        r['solder_area_px'] = solder_area
        r['void_count'] = len(self._edit_voids)
        r['void_area_px'] = void_area
        r['void_rate'] = (void_area / solder_area) if solder_area else 0.0
        r['edited'] = True
        r['caliber'] = caliber
        warns = r.setdefault('warnings', [])
        if '人工修正' not in warns:
            warns.append('人工修正')
        self._baseline_voids = cur_voids
        self._update_table_row(row)
        self._update_summary()
        res = {'void_rate': r['void_rate'], 'void_count': r['void_count'],
               'solder_area_px': solder_area, 'caliber': caliber}
        self._refresh_preview_label(row, res)
        show_info(
            self, "已应用",
            f"已应用修正：空洞率 {r['void_rate'] * 100:.2f}%\n"
            f"面积口径：{caliber}（表格与汇总已更新）")

    def confirm_revert_edit(self):
        if not self._require_preview():
            return False
        if self.preview_row not in self.result_edits:
            show_info(self, "提示", "该图没有人工修正")
            return False
        if not confirm_action(
                self, '还原自动结果',
                '将放弃本图的人工修正，恢复为自动检测结果。\n此操作不可撤销。'):
            return False
        self.revert_result_edit()
        return True

    def revert_result_edit(self):
        if not self._require_preview():
            return
        row = self.preview_row
        if row not in self.result_edits:
            show_info(self, "提示", "该图没有人工修正")
            return
        self.result_edits.pop(row, None)
        r = self.batch_results[row]
        snap = r.pop('_auto', None)
        if snap:
            for k, v in snap.items():
                r[k] = v
        r.pop('edited', None)
        r.pop('caliber', None)
        if r.get('warnings'):
            r['warnings'] = [w for w in r['warnings'] if w != '人工修正']
        self._update_table_row(row)
        self._update_summary()
        self.preview_result(row)
        show_toast(self, "已还原为自动检测结果")

    def _update_table_row(self, row):
        r = self.batch_results[row]
        view = self._view_row(row)
        if view < 0:
            return
        vals = [r.get('filename', ''),
                f"{r['solder_area_px']}" if r.get('ok') else '—',
                f"{r['void_count']}" if r.get('ok') else '—',
                f"{r['void_rate'] * 100:.2f}" if r.get('ok') else '—',
                '；'.join(r.get('warnings') or [])]
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        sort_vals = (row,
                     r.get('solder_area_px', -1) if r.get('ok') else -1,
                     r.get('void_count', -1) if r.get('ok') else -1,
                     r.get('void_rate', -1) if r.get('ok') else -1,
                     vals[4])
        for c, val in enumerate(vals):
            if c in (1, 2, 3):
                it = NumericItem(val, sort_vals[c])
                align_right(it)
            else:
                it = QTableWidgetItem(val)
            if r.get('warnings'):
                it.setBackground(QColor(254, 249, 195))
            if c == 0:
                it.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(view, c, it)
        self.table.setSortingEnabled(sorting)

    def _update_summary(self):
        lines = self._summary_lines()
        if not lines:
            return
        # 第一行拆开：大字只放"总空洞率"，其余小字放右侧（3 行，不换行错乱）
        head = lines[0].split('　', 1)
        self.lbl_total.setText(head[0])
        rest = (head[1] + '\n' if len(head) > 1 else '')
        self.lbl_stats.setText(rest + '\n'.join(lines[1:3]))

    def _save_png(self, path, img_bgr):
        """写 PNG 并做三重校验（绕开 cv2.imwrite 中文路径问题）

        1. 另存为对话框不会自动补扩展名——用户输入不带 .png 时 Qt 照原样存成
           无扩展名文件，Windows 便当作未知/损坏文件；
        2. 先写临时文件再原子替换，避免中途失败留下半截文件；
        3. 写完回读校验：能解码 + **文件头确实是该格式的签名**。
        第 3 条里的签名校验专门用来识别"文件被外部程序改写"的情况——
        公司加密/DLP/杀软透明加密时，落盘内容的头几个字节会变，
        Windows 就会报文件损坏。这种情况必须明确告诉用户，而不是静默成功。
        """
        self._last_save_error = ''
        self._last_save_warning = ''
        if img_bgr is None or getattr(img_bgr, 'size', 0) == 0:
            self._last_save_error = '图像为空'
            return False
        if img_bgr.ndim == 2:
            img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
        root, ext = os.path.splitext(path)
        if ext.lower() not in ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp'):
            path = path + '.png'
            ext = '.png'
        ext = ext.lower() or '.png'
        try:
            ok, buf = cv2.imencode(ext, img_bgr)
            if not ok:
                self._last_save_error = '图像编码失败'
                return False
            tmp = path + '.part'
            with open(tmp, 'wb') as f:
                f.write(buf.tobytes())
            os.replace(tmp, path)                 # 原子替换，不留半截文件
        except Exception as e:
            self._last_save_error = f'写入失败：{e}'
            return False
        # 回读校验（顺序很关键：先认第三方加密容器，再验格式签名，最后才解码）
        self._last_save_warning = ''
        try:
            if os.path.getsize(path) <= 0:
                self._last_save_error = '写入后文件为空'
                return False
            with open(path, 'rb') as fh:      # 显式关闭：避免句柄残留把文件"锁住"
                raw = fh.read(4096)
            head = raw[:8]
            # ① 第三方加密容器（亿赛通 E-SafeNet 等 DLP 会在文件头写厂商标记，
            #    整份文件被包进加密容器：既不是 PNG，也没有标准 ENCRYPTED 属性）
            vendor = ''
            for mark, name in ((b'E-SafeNet', 'E-SafeNet（亿赛通）'),
                               (b'ESafeNet', 'E-SafeNet（亿赛通）'),
                               (b'DSMEncr', '亿赛通 DSM')):
                if mark in raw:
                    vendor = name
                    break
            if vendor:
                self._last_save_error = (
                    f'⛔ 该文件已被「{vendor}」数据防泄漏软件加密——'
                    '不是程序写坏的，是 DLP 策略命中了本程序。\n'
                    '本机部分程序能打开，发给别人或换机器会显示损坏。\n'
                    '解决：请 IT 把本程序加入其「信任进程白名单」，'
                    '或把输出目录加入「不加密目录」。')
                return False
            # ② 格式签名
            sigs = {'.png': (b'\x89PNG\r\n\x1a\n',),
                    '.jpg': (b'\xff\xd8\xff',), '.jpeg': (b'\xff\xd8\xff',),
                    '.bmp': (b'BM',),
                    '.tif': (b'II*\x00', b'MM\x00*'),
                    '.tiff': (b'II*\x00', b'MM\x00*')}.get(ext, ())
            if sigs and not any(head.startswith(s) for s in sigs):
                self._last_save_error = (
                    '写入后文件头不是 ' + ext.lstrip('.').upper() +
                    f'（实际 {head[:4].hex(" ")}）——文件被外部程序改写了，'
                    '常见于公司加密/DLP 或安全软件；'
                    '请把本程序/保存目录加入其白名单')
                return False
            # ③ 能否解码
            back = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if back is None:
                self._last_save_error = '写入后无法解码（文件可能已损坏）'
                return False
            # ④ 标准加密属性（EFS 等）
            try:
                st = os.stat(path)
                attrs = getattr(st, 'st_file_attributes', 0) or 0
                if attrs & 0x4000:      # FILE_ATTRIBUTE_ENCRYPTED
                    self._last_save_warning = (
                        '注意：该文件被系统标记为「加密」（ENCRYPTED 属性）。'
                        '本机能打开，换机器或发给别人可能打不开，'
                        '需要把保存目录加入加密软件白名单')
                elif attrs & 0x1:       # FILE_ATTRIBUTE_READONLY
                    self._last_save_warning = '注意：该文件带只读属性'
            except Exception:
                pass
        except Exception as e:
            self._last_save_error = f'校验失败：{e}'
            return False
        self._saved_path = path
        return True

    @staticmethod
    def _kb(path):
        try:
            return f"{os.path.getsize(path) / 1024:.0f} KB"
        except OSError:
            return '?'

    @staticmethod
    def _annotated_lines(r, res):
        """标注图左上角文字行（中文，供单图标注与汇总大图共用）"""
        px_um = r.get('px_per_um_used') or 0.0
        area_um = (res['solder_area_px'] / (px_um ** 2)) if px_um > 0 else 0.0
        lines = [
            str(r.get('filename', '')),
            f"空洞率 {res['void_rate'] * 100:.2f}%　空洞 {res['void_count']} 个　"
            f"金锡 {res['solder_area_px']}px²"
            + (f"（{area_um:.0f}μm²）" if area_um > 0 else ""),
            f"t_空洞={res.get('t_void_used', 0):.0f}　"
            f"面积区间 {res.get('min_area_used', '—')}~{res.get('max_area_used', '—')}px²　"
            f"比例尺={'自动' if r.get('bar_found') else '示范值'}"
            + (f"　【面积口径：{r.get('caliber')}】" if r.get('edited') else ""),
        ]
        dev = r.get('deviation')
        if dev:
            lines.append(
                f"vs 示教：偏移 {dev['center_shift'] * 100:.0f}%　"
                f"面积 ×{dev['area_ratio']:.2f}　长宽比 ×{dev['aspect_ratio']:.2f}")
        warn = '；'.join(r.get('warnings') or [])
        if warn:
            lines.append(f"警告：{warn}")
        return lines

    def export_annotated_current(self):
        """导出当前预览图的标注图（PNG）"""
        if self.preview_row is None or not self.batch_results:
            show_info(self, "提示", "请先点击结果表选择一张图")
            return
        r = self.batch_results[self.preview_row]
        img, res = self._rerun_result(self.preview_row)
        if img is None or res is None:
            show_warning(self, "提示", "该图无法重算检测叠加")
            return
        stem = os.path.splitext(r.get('filename', 'result'))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "导出标注图", f"{stem}_标注.png", "PNG (*.png)")
        if not path:
            return
        try:
            out = annotate_result(img, res['band_mask'], res['voids'],
                                  lines=self._annotated_lines(r, res))
            real = path if path.lower().endswith('.png') else path + '.png'
            if not self._save_png(path, out):
                show_warning(self, "导出失败",
                                    f"{self._last_save_error}\n目标：{real}")
                return
        except Exception as e:
            show_warning(self, "错误", f"导出失败：{e}")
            return
        msg = f"已导出：{real}\n大小 {self._kb(real)}"
        if getattr(self, '_last_save_warning', ''):
            msg += "\n\n" + self._last_save_warning
        show_info(self, "成功", msg)

    def export_annotated_all(self):
        """批量导出全部图的标注图到指定文件夹（复核/报告用）"""
        if not self.batch_results:
            show_info(self, "提示", "没有可导出的结果")
            return
        folder = QFileDialog.getExistingDirectory(self, "选择标注图输出文件夹")
        if not folder:
            return
        total = len(self.batch_results)
        progress = QProgressDialog("正在导出标注图...", "取消", 0, total, self)
        progress.setWindowTitle("导出标注图")
        progress.setMinimumDuration(0)
        progress.setValue(0)
        ok_cnt, fail_cnt = 0, 0
        first_err = ''
        for i, r in enumerate(self.batch_results):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            progress.setLabelText(f"{i + 1}/{total}  {r.get('filename', '')}")
            QApplication.processEvents()
            try:
                img, res = self._rerun_result(i)
                if img is None or res is None:
                    fail_cnt += 1
                    continue
                stem = os.path.splitext(r.get('filename', f'img{i}'))[0]
                out = annotate_result(img, res['band_mask'], res['voids'],
                                      lines=self._annotated_lines(r, res))
                if self._save_png(os.path.join(folder, f"{stem}_标注.png"), out):
                    ok_cnt += 1
                else:
                    fail_cnt += 1
                    if not first_err:
                        first_err = self._last_save_error
            except Exception:
                fail_cnt += 1
        progress.setValue(total)
        progress.close()
        msg = f"已导出 {ok_cnt} 张标注图，失败 {fail_cnt} 张\n输出目录：{folder}"
        if getattr(self, '_last_save_warning', ''):
            msg += "\n\n" + self._last_save_warning
        if fail_cnt and first_err:
            msg += f"\n\n失败原因（首条）：{first_err}"
        show_info(self, "完成", msg)

    # ================== 状态刷新 ==================

    def _refresh_labels(self):
        if self.roi_mask is not None:
            area = int(cv2.countNonZero(self.roi_mask))
            self.lbl_roi.setText(f"已定义 {area} px")
        else:
            self.lbl_roi.setText("未定义（自动识别草拟后可微调顶点）")
        self.lbl_void.setText(
            f"已点选 {len(self.void_marks)} 个（点典型大小的即可，不用标全）")
        if self.pixel_scale > 0:
            self.lbl_calib.setText(f"已标定：1 μm = {self.pixel_scale:.2f} px")
        else:
            self.lbl_calib.setText("未标定（划线后输入实际 μm 值）")
