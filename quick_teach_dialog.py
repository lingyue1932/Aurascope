# -*- coding: utf-8 -*-
"""快速示教（2 步 · 操作最少化）

设计目标
--------
把"完整示教"压成**两步、尽量不用动手**：

    ① 焊层区域 —— **打开就已经自动识别好了**（不满意才手绘多边形/拖顶点微调）
    ② 点选空洞 —— 左键点 2~3 个典型空洞；点错按 **Delete** 删除；点完**自动学习**

· **没有"上传样板图"**：图由调用方直接传入（批次里已自动挑好代表性图）
· **没有"开始学习"按钮**：每次点选/删除后自动重学并实时刷新（防抖 120ms）
· **没有学习报告弹窗**：关键数字（t_焊层 / t_空洞 / 空洞数 / 空洞率）就在底部状态条
· **没有模式切换**：第 2 步左键即点空洞；焊层区域在①步编辑

所有算法**直接复用示教同款**（image.py）：`locate_solder_band` /
`grab_local_dark_blob` / `learn_taught_model` / `apply_taught_model`。
产出的 `model` 就是一份标准示教配方，可直接喂给 `BatchWorker`。
"""

import os

import numpy as np
import cv2

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QMessageBox, QSizePolicy, QCheckBox, QLineEdit,
                             QListWidget, QListWidgetItem, QAbstractItemView,
                             QPushButton)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QImage, QPixmap, QIcon

from canvas import ImageCanvas
from image import (locate_solder_band, polygon_to_mask, grab_local_dark_blob,
                   learn_taught_model, apply_taught_model)
from recipe import save_taught, list_recipes
from ui_components import (create_primary_button, create_secondary_button,
                           create_success_button, create_info_label)
from styles import STYLESHEET


class ImagePickerDialog(QDialog):
    """选择示教基准图（缩略图网格；★ 标记系统自动挑的那张）

    为什么要给用户选：自动挑的是"p90 最接近整批中位数"的切片，但哪张最能代表
    这个器件、哪张空洞最清楚，只有人知道 ✗ 所以默认自动、允许一键更换 ✔
    """

    THUMB_H = 120
    MAX_SHOW = 80                       # 缩略图太多会很慢，最多展示 80 张

    def __init__(self, paths, current=None, parent=None,
                 title='选择示教基准图', thumb_loader=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(STYLESHEET)
        self.resize(760, 560)
        self._paths = list(paths)[:self.MAX_SHOW]
        self._cur = current
        self._loader = thumb_loader or _default_thumb
        self._chosen = current
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 10, 12, 10)
        lo.setSpacing(8)
        lb = create_info_label('点一张作为示教基准图（双击直接选用）。'
                               '★ = 系统自动挑的那张。')
        lb.setWordWrap(True)
        lo.addWidget(lb)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(160, self.THUMB_H))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSpacing(8)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        lo.addWidget(self.list, 1)
        self.lbl_sel = create_info_label('')
        lo.addWidget(self.lbl_sel)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(create_secondary_button('取消', self.reject))
        row.addWidget(create_primary_button('用这张', self._on_ok))
        lo.addLayout(row)
        self._fill()
        self.list.itemDoubleClicked.connect(lambda _i: self._on_ok())
        self.list.currentItemChanged.connect(lambda *a: self._refresh_sel())

    def _fill(self):
        for p in self._paths:
            same = self._cur and os.path.abspath(p) == os.path.abspath(self._cur)
            it = QListWidgetItem(('★ ' if same else '') + os.path.basename(p))
            try:
                it.setIcon(QIcon(self._loader(p)))   # ✗ setIcon 要 QIcon，传 QPixmap 会静默失败
            except Exception:
                pass
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.list.addItem(it)
        if self._cur:
            for i in range(self.list.count()):
                if os.path.abspath(self.list.item(i).data(Qt.ItemDataRole.UserRole)) \
                        == os.path.abspath(self._cur):
                    self.list.setCurrentRow(i)
                    break
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self._refresh_sel()

    def _refresh_sel(self):
        it = self.list.currentItem()
        self.lbl_sel.setText('' if it is None else
                             '已选：' + os.path.basename(
                                 it.data(Qt.ItemDataRole.UserRole)))

    def _on_ok(self):
        it = self.list.currentItem()
        if it is None:
            return
        self._chosen = it.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def selected(self):
        return self._chosen


def _default_thumb(path, height=120):
    """缩略图 QPixmap（cv2 读图 + 等比缩放 → QImage）"""
    img = _read_img_any(path)
    if img is None:
        return QPixmap()
    h, w = img.shape[:2]
    s = height / float(max(1, h))
    small = cv2.resize(img, (max(1, int(w * s)), height), interpolation=cv2.INTER_AREA)
    small = (cv2.cvtColor(small, cv2.COLOR_GRAY2RGB) if small.ndim == 2
             else cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
    small = np.ascontiguousarray(small)
    q = QImage(small.data, small.shape[1], small.shape[0], 3 * small.shape[1],
               QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(q)


def _read_img_any(path):
    """读图（16 位 TIFF 归一化，与软件 _read_image 一致）"""
    ext = os.path.splitext(path)[1].lower()
    a = None
    if ext in ('.tif', '.tiff'):
        try:
            import tifffile
            a = tifffile.imread(path)
            if a.ndim == 3 and a.shape[0] in (3, 4):
                a = np.transpose(a, (1, 2, 0))
            if a.ndim == 3 and a.shape[2] == 3:
                a = cv2.cvtColor(a, cv2.COLOR_RGB2BGR)
        except Exception:
            a = None
    if a is None:
        a = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if a is None:
        return None
    if a.dtype != np.uint8:
        a = (a / max(1, a.max()) * 255).astype(np.uint8)
    return a


class QuickTeachDialog(QDialog):
    """两步快速示教：① 焊层区域（已自动识别） ② 点选空洞（自动学习）"""

    STEPS = ("① 焊层区域", "② 点选空洞")
    LEARN_DELAY_MS = 120          # 点选后延迟学习（连续点击时合并）

    def __init__(self, gray, sample_name="", parent=None,
                 title="快速示教", image_bgr=None, suggest_name="",
                 candidates=None, current_path=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(STYLESHEET)
        self.resize(1120, 720)
        self.gray = gray
        self.img_bgr = image_bgr if image_bgr is not None else self._to_bgr(gray)
        self.sample_name = sample_name or ""
        # 状态
        self.roi_mask = None
        self.roi_pts = []
        self.marks = []              # 点选坐标 [(x, y)]
        self.blobs = []              # 点选抓到的暗核掩码
        self.model = None
        self.saved_name = None            # 存进配方库后的名字
        self.picked_path = None           # 用户换选的基准图（若有）
        self.suggest_name = (suggest_name or '').strip()
        self.candidates = list(candidates or [])   # 可换的基准图候选
        self.current_path = current_path or ''
        self._step = 0
        self._can_ok = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._learn_now)
        self._build_ui()
        self.canvas.set_image(self.img_bgr)
        self._connect()
        self._auto_roi(silent=True)          # 打开即自动识别焊层区域
        # 已识别好就直接进第 2 步（用户只需"点几个空洞"就能收工）
        self._set_step(0 if self.roi_mask is None else 1)

    # ------------------------------------------------------------------ UI
    @staticmethod
    def _to_bgr(gray):
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR) if gray.ndim == 2 else gray

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 10, 12, 10)
        lo.setSpacing(8)

        # 步骤条 + 更换基准图
        row = QHBoxLayout()
        row.setSpacing(8)
        self.step_btns = []
        for i, t in enumerate(self.STEPS):
            b = create_secondary_button(
                t, lambda _=False, i=i: self._set_step(i), checkable=True)
            b.setStyleSheet(
                "QPushButton { text-align: left; padding: 7px 10px; font-size: 12px; }"
                "QPushButton:checked { background: #4299e1; color: #ffffff;"
                " font-weight: 600; border-color: #4299e1; }")
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.addWidget(b)
            self.step_btns.append(b)
        # 示教基准图可由用户自行选择（默认用自动挑的那张）
        self.btn_pick_img = create_secondary_button("更换示教图片…", self._choose_image)
        self.btn_pick_img.setEnabled(bool(self.candidates))
        if self.candidates:
            self.btn_pick_img.setToolTip(
                f"从本批次的 {len(self.candidates)} 张里挑一张作为示教基准图\n"
                f"（默认用自动挑的：{os.path.basename(self.current_path) or '—'}）")
        row.addWidget(self.btn_pick_img)
        lo.addLayout(row)

        # 主区：左栏（当前步骤的操作）+ 画布
        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._build_left(), 0)
        self.canvas = ImageCanvas()
        body.addWidget(self.canvas, 1)
        lo.addLayout(body, 1)

        # 底部①：状态行
        self.lbl_stat = create_info_label("正在自动识别焊层区域…")
        self.lbl_stat.setWordWrap(True)
        lo.addWidget(self.lbl_stat)

        # 底部②：保存为配方（默认勾选 → 学完即入库，以后可在下拉框直接复用）
        row = QHBoxLayout()
        row.setSpacing(6)
        self.chk_save = QCheckBox("保存为配方（以后可直接复用）")
        self.chk_save.setChecked(True)
        row.addWidget(self.chk_save)
        self.edit_name = QLineEdit(self.suggest_name or "快速示教")
        self.edit_name.setMaximumWidth(180)
        row.addWidget(self.edit_name)
        self.lbl_save_hint = create_info_label("")
        row.addWidget(self.lbl_save_hint, 1)
        lo.addLayout(row)

        # 底部③：按钮
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.btn_cancel = create_secondary_button("取消", self.reject)
        bottom.addWidget(self.btn_cancel)
        self.btn_ok = create_success_button("完成并采用", self._on_ok)
        self.btn_ok.setEnabled(False)
        bottom.addWidget(self.btn_ok)
        lo.addLayout(bottom)

        self.chk_save.toggled.connect(self._refresh_save_hint)
        self.edit_name.textChanged.connect(self._refresh_save_hint)
        self._refresh_save_hint()

    def _build_left(self):
        from PyQt6.QtWidgets import QWidget, QFrame
        box = QFrame()
        box.setObjectName("TeachLeftPanel")     # ★ 限定：不写裸 QFrame，否则内部 QLabel 也会被套边框 ✗
        box.setFixedWidth(232)
        box.setStyleSheet("QFrame#TeachLeftPanel { background:#FFFFFF;"
                          " border:1px solid #DCE3EC; border-radius:10px; }")
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        # —— 步骤① 焊层区域 ——
        self.pane_roi = QWidget()
        p = QVBoxLayout(self.pane_roi)
        p.setContentsMargins(0, 0, 0, 0)
        p.setSpacing(6)
        p.addWidget(create_info_label(
            "已自动识别。\n不对时可手绘多边形，\n或拖动绿色顶点微调。"))
        self.btn_auto_roi = create_secondary_button("重新自动识别", self._auto_roi)
        p.addWidget(self.btn_auto_roi)
        self.btn_poly = create_secondary_button(
            "手绘焊层区域", lambda _=False: self._toggle_poly(), checkable=True)
        p.addWidget(self.btn_poly)
        self.btn_edit_roi = create_secondary_button(
            "拖动顶点微调", lambda _=False: self._toggle_edit_roi(), checkable=True)
        p.addWidget(self.btn_edit_roi)
        v.addWidget(self.pane_roi)

        # —— 步骤② 点选空洞 ——
        self.pane_void = QWidget()
        p2 = QVBoxLayout(self.pane_void)
        p2.setContentsMargins(0, 0, 0, 0)
        p2.setSpacing(6)
        _hint2 = create_info_label(
            "左键点 2~3 个典型空洞\n（不用挑最黑的，边界的最准）\n\n"
            "点错：按 Delete 删除")
        _hint2.setWordWrap(True)      # ✗ 不开换行，右栏窄的时候文字会被截断
        p2.addWidget(_hint2)
        self.lbl_void = create_info_label("已点选 0 个")
        self.lbl_void.setWordWrap(True)
        p2.addWidget(self.lbl_void)
        self.btn_clear = create_secondary_button("清空点选", self._clear_marks)
        p2.addWidget(self.btn_clear)
        v.addWidget(self.pane_void)
        v.addStretch()
        return box

    def _choose_image(self):
        """更换示教基准图：选完通过回调交给调用方重开对话框（避免半途重置状态出错）"""
        if not self.candidates:
            return
        dlg = ImagePickerDialog(self.candidates, current=self.current_path,
                                parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path = dlg.selected()
        if not path or (self.current_path and
                        os.path.abspath(path) == os.path.abspath(self.current_path)):
            return
        self.picked_path = path
        self.done(QDialog.DialogCode.Accepted + 100)   # 约定码：调用方据此换图重开

    def _refresh_save_hint(self, *_a):
        """勾选保存时：提示是否已存在同名配方（保存会覆盖）"""
        on = self.chk_save.isChecked()
        self.edit_name.setEnabled(on)
        if not on:
            self.lbl_save_hint.setText("")
            return
        name = (self.edit_name.text() or '').strip()
        if not name:
            self.lbl_save_hint.setText("请填配方名")
            return
        try:
            exist = any(disp == name or fn == name or fn == f'{name}.taught.json'
                        for disp, fn in list_recipes(kind='taught'))
        except Exception:
            exist = False
        self.lbl_save_hint.setText(
            f"⚠ 已有同名配方，保存将覆盖它" if exist
            else "保存后可在批次面板的配方下拉框里直接选用")

    def _connect(self):
        self.canvas.roi_poly_finished.connect(self._on_poly)
        self.canvas.roi_polygon_edited.connect(self._on_poly_edited)
        self.canvas.teach_void_at.connect(self._on_click_void)

    # ------------------------------------------------------- 步骤与键盘
    def _set_step(self, i):
        self._step = max(0, min(int(i), len(self.STEPS) - 1))
        for k, b in enumerate(self.step_btns):
            b.setChecked(k == self._step)
            mark = "▶ " if k == self._step else ("✓ " if self._done(k) else "· ")
            b.setText(mark + self.STEPS[k])
        self.pane_roi.setVisible(self._step == 0)
        self.pane_void.setVisible(self._step == 1)
        if self._step == 0:
            self.canvas.set_teach_void_mode(False)
            self.canvas.set_roi_edit_enabled(self.btn_edit_roi.isChecked())
        else:
            self.btn_poly.setChecked(False)
            self.btn_edit_roi.setChecked(False)
            self.canvas.mode = 'none'
            self.canvas.set_roi_edit_enabled(False)
            self.canvas.set_teach_void_mode(True)
        self._refresh_status()

    def _done(self, i):
        return self.roi_mask is not None if i == 0 else len(self.blobs) > 0

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_last()
            return
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._can_ok:
            self._on_ok()
            return
        super().keyPressEvent(e)

    # ---------------------------------------------------------- 焊层区域
    def _auto_roi(self, silent=False):
        """自动识别焊层区域（p90 定位 → 取多边形）"""
        g = self.gray
        band = None
        try:
            band, _ = locate_solder_band(g, float(np.percentile(g, 90)), band_ref=None)
        except Exception:
            band = None
        if band is None or np.count_nonzero(band) < 0.005 * g.size:
            if not silent:
                QMessageBox.information(
                    self, "提示", "自动识别未成功，请用「手绘焊层区域」圈一下焊层")
                self.btn_poly.setChecked(True)
                self.canvas.mode = 'poly'
                self.canvas.current_points = []
                self.canvas.update()
            return False
        self.roi_mask = (band > 0).astype(np.uint8) * 255
        self.roi_pts = self._mask_to_polygon(self.roi_mask)
        self.canvas.set_roi_polygon(self.roi_pts)
        self.canvas.set_roi_edit_enabled(self.btn_edit_roi.isChecked())
        if self._step == 0 and not silent:
            self._set_step(1)          # 识别成功 → 直接进第 2 步（少一步操作）
        self._refresh_status()
        return True

    @staticmethod
    def _mask_to_polygon(mask):
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return []
        big = max(cnts, key=cv2.contourArea)
        approx = cv2.approxPolyDP(big, 2.0, True)
        return [(float(p[0][0]), float(p[0][1])) for p in approx]

    def _toggle_poly(self):
        on = self.btn_poly.isChecked()
        if on:
            self.btn_edit_roi.setChecked(False)
            self.canvas.set_roi_edit_enabled(False)
            self.canvas.mode = 'poly'
            self.canvas.current_points = []
            self.canvas.update()
            self.lbl_stat.setText("在图上依次点顶点，双击/回车闭合多边形")
        else:
            self.canvas.mode = 'none'
            self.canvas.update()

    def _toggle_edit_roi(self):
        on = self.btn_edit_roi.isChecked()
        if on:
            self.btn_poly.setChecked(False)
            self.canvas.mode = 'none'
        self.canvas.set_roi_edit_enabled(on and self.roi_mask is not None)
        self.canvas.update()

    def _on_poly(self, pts):
        if len(pts) < 3:
            return
        self.btn_poly.setChecked(False)
        self.canvas.mode = 'none'
        self._set_roi(pts)

    def _on_poly_edited(self, pts):
        if len(pts) < 3:
            return
        self.roi_pts = [(float(x), float(y)) for x, y in pts]
        self.roi_mask = polygon_to_mask(self.roi_pts, self.gray.shape)
        self._refresh_status()
        if self.blobs:
            self._schedule_learn()

    def _set_roi(self, pts):
        self.roi_pts = [(float(x), float(y)) for x, y in pts]
        self.roi_mask = polygon_to_mask(self.roi_pts, self.gray.shape)
        self.canvas.set_roi_polygon(self.roi_pts)
        self.canvas.set_roi_edit_enabled(self.btn_edit_roi.isChecked())
        self._refresh_status()
        if self.blobs:
            self._schedule_learn()

    # ---------------------------------------------------------- 点选空洞
    def _on_click_void(self, x, y):
        if self.roi_mask is None:
            self.lbl_stat.setText("请先在①步定义焊层区域")
            return
        h, w = self.gray.shape
        x1, y1 = max(0, int(x) - 40), max(0, int(y) - 40)
        x2, y2 = min(w, int(x) + 40), min(h, int(y) + 40)
        if x2 - x1 < 5 or y2 - y1 < 5:
            return
        t_ref = float(np.percentile(self.gray[y1:y2, x1:x2], 85))
        blob, area = grab_local_dark_blob(self.gray, x, y, t_ref,
                                          region_mask=self.roi_mask)
        if blob is None:
            self.lbl_stat.setText("该位置未抓到暗核（点在亮处/区域外）——换一个空洞点")
            return
        self.marks.append((float(x), float(y)))
        self.blobs.append(blob)
        self._refresh_marks()
        self._schedule_learn()

    def _delete_last(self):
        """Delete：撤掉最后点选的那个空洞（点错了不用重来）"""
        if not self.blobs:
            self.lbl_stat.setText("还没有点选可删除")
            return
        self.marks.pop()
        self.blobs.pop()
        self._refresh_marks()
        if self.blobs:
            self._schedule_learn()
        else:
            self.model = None
            self.canvas.draw_voids = []
            self.canvas.update()
            self._can_ok = False
            self.btn_ok.setEnabled(False)
            self._refresh_status()

    def _clear_marks(self):
        self.marks, self.blobs = [], []
        self.model = None
        self.canvas.draw_voids = []
        self.canvas.update()
        self._can_ok = False
        self.btn_ok.setEnabled(False)
        self._refresh_marks()
        self._refresh_status()

    def _refresh_marks(self):
        """把已点选的暗核画到画布上（青=已点选，红=该阈值下检出的空洞）"""
        self.lbl_void.setText(f"已点选 {len(self.blobs)} 个")
        draw = []
        for i, blob in enumerate(self.blobs):
            cnts, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                continue
            cnt = max(cnts, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(cnt)
            draw.append({'id': i + 1, 'area_px': float(cv2.contourArea(cnt)),
                         'rect': (int(x), int(y), int(w), int(h)),
                         'cx': float(x + w / 2), 'cy': float(y + h / 2),
                         'points': cnt.reshape(-1, 2).tolist()})
        self.canvas.draw_voids = draw
        self.canvas.show_labels = True
        self.canvas.fill_voids = True
        self.canvas.update()

    # ------------------------------------------------------- 学习与预览
    def _schedule_learn(self):
        self._timer.start(self.LEARN_DELAY_MS)     # 连续点选时合并成一次学习

    def _learn_now(self):
        if not self.blobs or self.roi_mask is None:
            return
        try:
            model = learn_taught_model(self.gray, self.roi_mask, self.marks,
                                       void_blobs=self.blobs)
        except Exception as e:
            self.lbl_stat.setText(f"学习失败：{e}")
            return
        if model is None:
            self.lbl_stat.setText("学习失败（焊层区域或点选无效）")
            return
        model['name'] = '<快速示教>'
        model['note'] = f"快速示教：点选 {len(self.marks)} 个空洞"
        self.model = model
        self._can_ok = True
        self.btn_ok.setEnabled(True)
        self._refresh_status()

    def _refresh_status(self):
        if self.model is None:
            if self.roi_mask is None:
                self.lbl_stat.setText("请定义焊层区域")
            elif self._step == 1:
                self.lbl_stat.setText(
                    f"焊层区域就绪（{int(np.count_nonzero(self.roi_mask))}px²）"
                    f"　左键点 2~3 个典型空洞即可（点完自动学习）")
            return
        sol = (self.model.get('solder') or {}).get('threshold', 0)
        voi = (self.model.get('void') or {}).get('threshold', 0)
        try:
            res = apply_taught_model(self.gray, self.model)
        except Exception:
            res = {}
        rate = (res.get('void_rate') or 0) * 100
        n_v = len(res.get('voids') or [])
        if not res.get('ok'):
            self.lbl_stat.setText(
                f"t_焊层={sol:.0f}　t_空洞={voi:.0f}　"
                f"⚠ 示例图上未定位到焊层带：{(res.get('warnings') or [''])[0]}")
            return
        self.lbl_stat.setText(
            f"t_焊层={sol:.0f}　t_空洞={voi:.0f}　"
            f"点选 {len(self.marks)} 个　示例图检出空洞 {n_v} 个　"
            f"空洞率 {rate:.2f}%　（点错按 Delete）")

    # ---------------------------------------------------------------- 确认
    def _on_ok(self):
        if self.model is None:
            self.lbl_stat.setText("请至少点选 1 个空洞完成学习")
            return
        if self.chk_save.isChecked():
            name = (self.edit_name.text() or '').strip() or self.suggest_name or "快速示教"
            self.model['name'] = name
            try:
                save_taught(self.model)
                self.saved_name = name
            except Exception as e:
                QMessageBox.warning(self, "提示", f"保存配方失败（不影响本次使用）：{e}")
        self.accept()

    def get_model(self):
        return self.model


def quick_teach(gray, sample_name="", parent=None, image_bgr=None, suggest_name=""):
    """便捷入口：返回学到的配方（取消返回 None）"""
    dlg = QuickTeachDialog(gray, sample_name=sample_name, parent=parent,
                           image_bgr=image_bgr, suggest_name=suggest_name)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.get_model()
    return None
