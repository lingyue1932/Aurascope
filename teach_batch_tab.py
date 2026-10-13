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
import pandas as pd
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                             QFrame, QScrollArea, QLabel, QTableWidget,
                             QTableWidgetItem, QHeaderView, QInputDialog,
                             QMessageBox, QSizePolicy, QGraphicsDropShadowEffect,
                             QProgressBar, QProgressDialog, QComboBox,
                             QListWidget, QListWidgetItem, QAbstractItemView,
                             QSplitter, QApplication)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QImage

from canvas import ImageCanvas
from image import (polygon_to_mask, otsu_threshold, locate_solder_band,
                   grab_local_dark_blob, learn_taught_model, apply_taught_model,
                   read_scale_bar, resample_polygon_points, two_class_threshold,
                   annotate_result)
from recipe import list_recipes, load_recipe, save_taught, load_bar_template
from ui_components import (create_primary_button, create_secondary_button,
                           create_success_button, create_danger_button,
                           create_step_title, create_info_label,
                           create_checkbox, CollapsibleSection)

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

    # ================== UI ==================

    def init_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(0)

        # 用可拖拽分隔条：左侧功能面板宽度可横向调节（与「空洞分析」Tab 一致）
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = self._build_sidebar()
        self.splitter.addWidget(sidebar)
        self.canvas = ImageCanvas()
        self.splitter.addWidget(self.canvas)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        start = min(460, max(340, self._sb_min))
        self.splitter.setSizes([start, max(560, 1000 - start)])
        lo.addWidget(self.splitter)

        self._connect()

    def _compute_sidebar_min_width(self):
        """按"折叠区全部展开"的真实需求算侧栏最小宽度

        折叠区收起时其内部控件不参与 sizeHint，若按收起状态定宽，
        用户一展开「批量检测」内容就被裁掉（实测展开后需 334px）。
        """
        for cs in self._collapsibles:
            cs.container.setVisible(True)
        self._sb_content.adjustSize()
        QApplication.processEvents()
        hint = self._sb_content.sizeHint().width()
        for cs in self._collapsibles:
            cs.container.setVisible(False)
        self._sb_content.adjustSize()
        return max(300, min(520, hint + 12))

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("SidebarCard")
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
        self._sb_content = content            # 供最小宽度测量
        self._collapsibles = []
        v = QVBoxLayout(content)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── ① 上传样板图 ──
        v.addWidget(create_step_title("① 上传样板图"))
        v.addWidget(create_primary_button("上传样板图", self.load_sample))

        # ── ② 点选典型空洞（放在焊层区域之前：空洞是焊层带内部的锚点）──
        v.addWidget(create_step_title("② 点选典型空洞"))
        void_row = QHBoxLayout()
        self.btn_teach_void = create_secondary_button("点选空洞", self.toggle_teach_void,
                                                      checkable=True)
        void_row.addWidget(self.btn_teach_void)
        v.addLayout(void_row)
        self.list_marks = QListWidget()
        self.list_marks.setMaximumHeight(80)
        self.list_marks.setMinimumWidth(150)   # 不让它撑大面板宽度
        self.list_marks.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.list_marks.setToolTip("已点选的空洞，可删除选错的那一个")
        v.addWidget(self.list_marks)
        mark_row = QHBoxLayout()
        self.btn_del_mark = create_secondary_button("删除选中", self.delete_selected_mark)
        mark_row.addWidget(self.btn_del_mark)
        self.btn_clear_marks = create_danger_button("清除全部", self.clear_void_marks)
        mark_row.addWidget(self.btn_clear_marks)
        v.addLayout(mark_row)
        self.lbl_void = create_info_label("已点选 0 个（点典型大小的即可，不用标全）")
        v.addWidget(self.lbl_void)

        # ── ③ 示范焊层区域 ──
        v.addWidget(create_step_title("③ 示范焊层区域"))
        roi_row = QHBoxLayout()
        self.btn_auto_band = create_secondary_button("自动识别焊层带", self.auto_draft_roi)
        roi_row.addWidget(self.btn_auto_band)
        self.btn_poly = create_secondary_button("多边形手绘", self.start_poly_roi,
                                                checkable=True)
        roi_row.addWidget(self.btn_poly)
        v.addLayout(roi_row)
        self.btn_edit_roi = create_secondary_button("编辑顶点", self.toggle_edit_roi,
                                                    checkable=True)
        v.addWidget(self.btn_edit_roi)
        self.lbl_roi = create_info_label("未定义（点过空洞后可用「自动识别」，或手绘）")
        v.addWidget(self.lbl_roi)
        self.lbl_roi_tip = QLabel("移动光标到边界 → 最近的顶点高亮 → 拖动即可\n"
                                  "双击边新增顶点 · 选中顶点按 Delete 删除")
        self.lbl_roi_tip.setWordWrap(True)
        self.lbl_roi_tip.setStyleSheet("color: #718096; font-size: 12px;")
        v.addWidget(self.lbl_roi_tip)

        # ── ④ 标定比例尺 ──
        v.addWidget(create_step_title("④ 标定比例尺"))
        self.btn_calib = create_secondary_button("在比例尺上划线", self.start_calib,
                                                 checkable=True)
        v.addWidget(self.btn_calib)
        self.lbl_calib = create_info_label("未标定（划线后输入实际 μm 值）")
        v.addWidget(self.lbl_calib)

        # ── ⑤ 学习并保存 ──
        v.addWidget(create_step_title("⑤ 学习并保存"))
        self.btn_learn = create_primary_button("开始学习", self.on_learn)
        v.addWidget(self.btn_learn)
        self.btn_save_recipe = create_success_button("保存为示教配方", self.on_save_recipe)
        self.btn_save_recipe.setEnabled(False)
        v.addWidget(self.btn_save_recipe)
        self.lbl_learn = create_info_label("完成 ①~④ 后点「开始学习」，会在图上回放检测结果")
        v.addWidget(self.lbl_learn)

        # ── 批量检测 ──
        batch = CollapsibleSection("批量检测（同系列多图全自动）")
        self._collapsibles.append(batch)
        self.combo_recipe = QComboBox()
        self.combo_recipe.setMinimumWidth(110)
        self.combo_recipe.setToolTip("已保存的示教配方")
        recipe_row = QHBoxLayout()
        recipe_row.addWidget(self.combo_recipe, 1)
        btn_refresh = create_secondary_button("刷新", self.refresh_recipe_combo)
        recipe_row.addWidget(btn_refresh)
        batch.addLayout(recipe_row)

        self.btn_folder = create_secondary_button("选择批次文件夹", self.pick_folder)
        batch.addWidget(self.btn_folder)
        self.lbl_folder = create_info_label("未选择文件夹")
        batch.addWidget(self.lbl_folder)

        run_row = QHBoxLayout()
        self.btn_run = create_primary_button("开始批量", self.start_batch)
        run_row.addWidget(self.btn_run)
        self.btn_cancel = create_danger_button("取消", self.cancel_batch)
        self.btn_cancel.setEnabled(False)
        run_row.addWidget(self.btn_cancel)
        batch.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        batch.addWidget(self.progress)
        self.lbl_current = create_info_label("")
        batch.addWidget(self.lbl_current)

        # 汇总
        self.lbl_total = create_info_label("总空洞率: —")
        self.lbl_total.setObjectName("StatValue")
        batch.addWidget(self.lbl_total)
        self.lbl_stats = create_info_label("块均值: —")
        batch.addWidget(self.lbl_stats)

        # 结果表（点击行 = 在右侧画布查看该图的检测叠加）
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["图片", "金锡面积(px²)", "空洞数", "空洞率(%)", "警告"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMaximumHeight(260)
        self.table.setMinimumWidth(170)        # 表格自带滚动条，不必撑大面板
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self.preview_result)
        batch.addWidget(self.table)

        self.lbl_preview = create_info_label(
            "预览: 未选择（点击结果表任意行，在右侧查看该图的检测叠加）")
        batch.addWidget(self.lbl_preview)

        # ── 单图核对与修正 ──
        fix = CollapsibleSection("单图核对与修正（先点选结果表某一行）")
        self._collapsibles.append(fix)
        fix_row1 = QHBoxLayout()
        self.btn_edit_band = create_secondary_button("编辑金锡区域",
                                                     self.toggle_edit_band, checkable=True)
        fix_row1.addWidget(self.btn_edit_band)
        self.btn_add_void = create_secondary_button("添加空洞",
                                                    self.toggle_add_void, checkable=True)
        fix_row1.addWidget(self.btn_add_void)
        fix.addLayout(fix_row1)

        fix_row1b = QHBoxLayout()
        self.btn_del_void = create_secondary_button("删除空洞",
                                                    self.toggle_del_void, checkable=True)
        fix_row1b.addWidget(self.btn_del_void)
        fix_row1b.addStretch()
        fix.addLayout(fix_row1b)

        fix_row2 = QHBoxLayout()
        self.chk_labels = create_checkbox("显示序号", True, self.toggle_void_display)
        fix_row2.addWidget(self.chk_labels)
        self.chk_fill = create_checkbox("红色填充", True, self.toggle_void_display)
        fix_row2.addWidget(self.chk_fill)
        fix.addLayout(fix_row2)

        self.lbl_edit_tip = create_info_label(
            "区域：光标移到边界上，最近顶点高亮后拖动 · 双击边加点 · Delete 删点\n"
            "空洞：点空白处添加 / 点空洞删除")
        fix.addWidget(self.lbl_edit_tip)

        fix_row3 = QHBoxLayout()
        self.btn_apply_edit = create_success_button("应用修改", self.apply_result_edit)
        fix_row3.addWidget(self.btn_apply_edit)
        self.btn_revert_edit = create_danger_button("还原自动结果",
                                                    self.revert_result_edit)
        fix_row3.addWidget(self.btn_revert_edit)
        fix.addLayout(fix_row3)
        batch.addWidget(fix)

        exp_row = QHBoxLayout()
        self.btn_exp_cur = create_secondary_button("导出当前标注图",
                                                   self.export_annotated_current)
        exp_row.addWidget(self.btn_exp_cur)
        self.btn_exp_all = create_secondary_button("导出全部标注图",
                                                   self.export_annotated_all)
        exp_row.addWidget(self.btn_exp_all)
        batch.addLayout(exp_row)

        self.btn_export = create_secondary_button("导出 CSV", self.export_csv)
        self.btn_export.setEnabled(False)
        batch.addWidget(self.btn_export)

        v.addWidget(batch)
        v.addStretch()
        scroll.setWidget(content)

        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._sb_min = self._compute_sidebar_min_width()
        sidebar.setMinimumWidth(self._sb_min)
        self.refresh_recipe_combo()
        return sidebar

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
            QMessageBox.warning(self, "错误", "图片加载失败")
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
        self.model = None
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
            QMessageBox.information(self, "提示", "请先上传样板图")
            return
        self.btn_poly.setChecked(False)
        self.canvas.mode = 'none'

        if not self.void_blobs:
            QMessageBox.information(
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
            QMessageBox.warning(
                self, "提示", "未找到焊层带，请用「多边形手绘」框选")
            return
        pts = self._mask_to_polygon(band)
        if len(pts) < 3:
            QMessageBox.warning(self, "提示", "轮廓提取失败，请改用手绘")
            return
        self._set_roi(pts, band)

    def start_poly_roi(self):
        if self.gray is None:
            QMessageBox.information(self, "提示", "请先上传样板图")
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
            QMessageBox.information(self, "提示", "请先自动识别或手绘焊层区域")
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
            QMessageBox.information(self, "提示", "请先上传样板图")
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
            QMessageBox.information(self, "提示", "该位置未抓到暗核，请点空洞中心")
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
            QMessageBox.information(self, "提示", "请先在列表中选择要删除的空洞")
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
        self.canvas.fill_voids = True
        self.canvas.update()

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
            QMessageBox.information(self, "提示", "请先上传样板图")
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
            QMessageBox.warning(self, "提示", "标定线太短，请重画")
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
            QMessageBox.information(self, "提示", "请先完成 ① 上传 和 ③ 焊层区域示范")
            return
        if not self.void_marks:
            QMessageBox.information(self, "提示", "请先点选至少 1 个典型空洞（②）")
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
            QMessageBox.warning(
                self, "提示", "所有点选都不在焊层带内，请检查 ② 的点选位置")
            return
        if dropped:
            QMessageBox.information(
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
            QMessageBox.warning(self, "错误", "学习失败，请检查焊层区域示范是否有效")
            return
        model['name'] = self.recipe_name or "未命名示教"
        self.model = model

        # 预览：在样板图上回放
        res = apply_taught_model(self.gray, model)
        if not res.get('ok'):
            QMessageBox.warning(self, "提示",
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
        self.canvas.fill_voids = True
        self.canvas.void_rate_text = f"空洞率: {res['void_rate'] * 100:.2f}%"
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
            QMessageBox.warning(self, "提示", "配方名称不能为空")
            return
        self.recipe_name = name
        self.model['name'] = name
        self.model['note'] = (f"样板图: {os.path.basename(self.sample_path)}"
                              if self.sample_path else "")
        self.model['updated'] = datetime.now().isoformat(timespec='seconds')
        try:
            save_taught(self.model,
                        bar_template=(self.bar_info or {}).get('template'))
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")
            return
        self.refresh_recipe_combo()
        idx = self.combo_recipe.findText(name)
        if idx >= 0:
            self.combo_recipe.setCurrentIndex(idx)
        QMessageBox.information(self, "成功", f"示教配方「{name}」已保存")

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
        if not folder:
            return
        paths = []
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith(IMG_EXTS):
                paths.append(os.path.join(folder, fn))
        if not paths:
            QMessageBox.information(self, "提示", "该文件夹下没有图片文件")
            return
        self.batch_paths = paths
        self.lbl_folder.setText(f"已选择 {len(paths)} 张：{os.path.basename(folder)}")

    def start_batch(self):
        fn = self.combo_recipe.currentData()
        if not fn:
            QMessageBox.information(self, "提示", "请先选择示教配方")
            return
        model = load_recipe(fn)
        if model is None or model.get('type') != 'taught':
            QMessageBox.warning(self, "错误", "配方读取失败或不是示教配方")
            self.refresh_recipe_combo()
            return
        if not self.batch_paths:
            QMessageBox.information(self, "提示", "请先选择批次文件夹")
            return
        bar_template = load_bar_template(fn)

        self.batch_results = []
        self.result_edits = {}
        self.preview_row = None
        self._reset_edit_modes()
        self.table.setRowCount(0)
        self.lbl_total.setText("总空洞率: —")
        self.lbl_stats.setText("块均值: —")
        self.btn_export.setEnabled(False)
        self.progress.setValue(0)
        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.preview_row = None
        self._batch_canceled = False
        self.lbl_preview.setText("预览: 批量进行中…（结束后点击结果表任意行查看）")
        # 缓存本次批量的模型与比例尺模板，预览/导出标注图时按需重算
        self._last_model = model
        self._last_bar_template = bar_template

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
        self.table.setItem(row, 0, QTableWidgetItem(r.get('filename', '')))
        self.table.setItem(row, 1, QTableWidgetItem(area))
        self.table.setItem(row, 2, QTableWidgetItem(cnt))
        self.table.setItem(row, 3, QTableWidgetItem(rate))
        self.table.setItem(row, 4, QTableWidgetItem(warn))
        if warn:
            for c in range(5):
                self.table.item(row, c).setBackground(QColor(254, 249, 195))

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
            QMessageBox.information(
                self, "已取消",
                f"批量已取消，已完成 {len(results)}/{len(self.batch_paths)} 张\n"
                f"（已完成的结果可在表格中查看，点击行可预览）")
        else:
            QMessageBox.information(
                self, "完成",
                f"批量检测完成：{len(results)} 张\n"
                f"（异常图已在表格中标黄；点击任意行可在右侧查看该图检测叠加）")

    def on_batch_failed(self, msg):
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        QMessageBox.warning(self, "错误", f"批量处理出错: {msg}")

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
        df = pd.DataFrame(rows)
        df.to_csv(path, index=False, encoding='utf-8-sig')
        QMessageBox.information(self, "成功", f"已导出 {len(rows)} 行")

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
        self.table.selectRow(row)
        self._reset_edit_modes()
        if not r.get('ok'):
            self.lbl_preview.setText(
                f"预览: {r.get('filename', '')} — 处理失败"
                f"（{'；'.join(r.get('warnings') or [])}）")
            return
        img, res = self._rerun_result(row)
        if img is None:
            self.lbl_preview.setText("预览: 图片读取失败或模型不可用")
            return
        if res is None:
            self.lbl_preview.setText(f"预览: {r['filename']} — 未能定位焊层带")
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
        parts = [f"预览: {r['filename']}   空洞率 {res['void_rate'] * 100:.2f}%"]
        if r.get('edited'):
            parts.append(f"【已人工修正 · 面积口径:{r.get('caliber') or '人工修正轮廓'}】")
        else:
            parts.append("面积口径:检测掩码")
        dev = r.get('deviation')
        if dev:
            parts.append(f"vs示教: 偏移{dev['center_shift'] * 100:.0f}% "
                         f"面积×{dev['area_ratio']:.2f} 长宽×{dev['aspect_ratio']:.2f}")
        warn = '；'.join(r.get('warnings') or [])
        if warn:
            parts.append(f"⚠ {warn}")
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
            QMessageBox.information(self, "提示", "请先点击结果表选中一行")
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
        self.lbl_edit_tip.setText(
            "区域编辑中：光标移到边界上，最近顶点会高亮，拖动它移动 · "
            "双击边新增顶点 · 选中顶点按 Delete 删除")

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
        self.lbl_edit_tip.setText("添加空洞：点击图上空洞位置（暗核自动抓取）")

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
        self.lbl_edit_tip.setText("删除空洞：点击要删除的空洞（悬停高亮）")

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
            QMessageBox.information(self, "提示", "该位置未抓到暗核（可能不在焊层带内）")
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
            QMessageBox.information(self, "提示", "焊层区域无效（至少 3 个顶点）")
            return
        band = self._edit_mask
        if band is None or cv2.countNonZero(band) == 0:
            QMessageBox.information(self, "提示", "焊层区域无效")
            return
        r = self.batch_results[row]
        cur_voids = [(v['id'], round(float(v['area_px']), 3)) for v in self._edit_voids]
        base_voids = self._baseline_voids
        unchanged = (not self._poly_touched) and (cur_voids == base_voids)
        if unchanged:
            QMessageBox.information(
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
        QMessageBox.information(
            self, "已应用",
            f"已应用修正：空洞率 {r['void_rate'] * 100:.2f}%\n"
            f"面积口径：{caliber}（表格与汇总已更新）")

    def revert_result_edit(self):
        if not self._require_preview():
            return
        row = self.preview_row
        if row not in self.result_edits:
            QMessageBox.information(self, "提示", "该图没有人工修正")
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
        QMessageBox.information(self, "已还原", "已还原为自动检测结果")

    def _update_table_row(self, row):
        r = self.batch_results[row]
        if row >= self.table.rowCount():
            return
        vals = [r.get('filename', ''),
                f"{r['solder_area_px']}" if r.get('ok') else '—',
                f"{r['void_count']}" if r.get('ok') else '—',
                f"{r['void_rate'] * 100:.2f}" if r.get('ok') else '—',
                '；'.join(r.get('warnings') or [])]
        for c, val in enumerate(vals):
            it = QTableWidgetItem(val)
            if r.get('warnings'):
                it.setBackground(QColor(254, 249, 195))
            self.table.setItem(row, c, it)

    def _update_summary(self):
        ok = [r for r in self.batch_results if r.get('ok') and r.get('solder_area_px')]
        if not ok:
            return
        tot_solder = sum(r['solder_area_px'] for r in ok)
        tot_void = sum(r['void_area_px'] for r in ok)
        total_rate = tot_void / tot_solder * 100 if tot_solder else 0.0
        rates = [r['void_rate'] * 100 for r in ok]
        self.lbl_total.setText(f"总空洞率: {total_rate:.2f}%")
        self.lbl_stats.setText(
            f"块均值: {float(np.mean(rates)):.2f}% ± {float(np.std(rates)):.2f}   "
            f"最小 {min(rates):.2f}% ~ 最大 {max(rates):.2f}%   "
            f"异常 {len(self.batch_results) - len(ok)} 张"
            + (f"   人工修正 {len(self.result_edits)} 张" if self.result_edits else ""))

    @staticmethod
    def _save_png(path, img_bgr):
        """写 PNG（绕开 cv2.imwrite 不支持中文路径的问题）"""
        ok, buf = cv2.imencode('.png', img_bgr)
        if not ok:
            return False
        with open(path, 'wb') as f:
            f.write(buf.tobytes())
        return True

    @staticmethod
    def _annotated_lines(r, res):
        """标注图左上角文字行"""
        px_um = r.get('px_per_um_used') or 0.0
        area_um = (res['solder_area_px'] / (px_um ** 2)) if px_um > 0 else 0.0
        lines = [
            str(r.get('filename', '')),
            f"void_rate={res['void_rate'] * 100:.2f}%  voids={res['void_count']}  "
            f"solder={res['solder_area_px']}px2"
            + (f" ({area_um:.0f}um2)" if area_um > 0 else ""),
            f"t_void={res.get('t_void_used', 0):.0f}  "
            f"scale={'auto' if r.get('bar_found') else 'taught'}"
            + (f"  [EDIT:{r.get('caliber')}]" if r.get('edited') else ""),
        ]
        dev = r.get('deviation')
        if dev:
            lines.append(
                f"vs taught: center={dev['center_shift'] * 100:.0f}%  "
                f"area x{dev['area_ratio']:.2f}  aspect x{dev['aspect_ratio']:.2f}")
        warn = '; '.join(r.get('warnings') or [])
        if warn:
            lines.append(f"warn: {warn}")
        return lines

    def export_annotated_current(self):
        """导出当前预览图的标注图（PNG）"""
        if self.preview_row is None or not self.batch_results:
            QMessageBox.information(self, "提示", "请先点击结果表选择一张图")
            return
        r = self.batch_results[self.preview_row]
        img, res = self._rerun_result(self.preview_row)
        if img is None or res is None:
            QMessageBox.warning(self, "提示", "该图无法重算检测叠加")
            return
        stem = os.path.splitext(r.get('filename', 'result'))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "导出标注图", f"{stem}_标注.png", "PNG (*.png)")
        if not path:
            return
        try:
            out = annotate_result(img, res['band_mask'], res['voids'],
                                  lines=self._annotated_lines(r, res))
            if not self._save_png(path, out):
                raise RuntimeError('写入失败')
        except Exception as e:
            QMessageBox.warning(self, "错误", f"导出失败: {e}")
            return
        QMessageBox.information(self, "成功", f"已导出：{os.path.basename(path)}")

    def export_annotated_all(self):
        """批量导出全部图的标注图到指定文件夹（复核/报告用）"""
        if not self.batch_results:
            QMessageBox.information(self, "提示", "没有可导出的结果")
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
            except Exception:
                fail_cnt += 1
        progress.setValue(total)
        progress.close()
        QMessageBox.information(
            self, "完成",
            f"已导出 {ok_cnt} 张标注图，失败 {fail_cnt} 张\n输出目录：{folder}")

    # ================== 状态刷新 ==================

    def _refresh_labels(self):
        if self.roi_mask is not None:
            area = int(cv2.countNonZero(self.roi_mask))
            self.lbl_roi.setText(f"已定义：{area} px（可继续微调顶点）")
        else:
            self.lbl_roi.setText("未定义（自动识别草拟后可微调顶点）")
        self.lbl_void.setText(
            f"已点选 {len(self.void_marks)} 个（点典型大小的即可，不用标全）")
        if self.pixel_scale > 0:
            self.lbl_calib.setText(f"已标定：1 μm = {self.pixel_scale:.2f} px")
        else:
            self.lbl_calib.setText("未标定（划线后输入实际 μm 值）")
