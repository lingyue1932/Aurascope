# -*- coding: utf-8 -*-
"""学习过程窗口：把「开始学习」到底做了哪些事、得到了什么数，逐条摊开给用户看"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QScrollArea, QWidget, QFrame)

from ui_components import (create_primary_button, create_step_title,
                           create_info_label)


class LearnReportDialog(QDialog):
    """展示一次学习的过程与结果

    items: [(标题, [明细行...], 状态)]  状态 ∈ {'ok','warn','info'}
    preview: 可选 (QImage/QPixmap) 学习结果叠加图
    """

    def __init__(self, items, preview=None, title="学习过程", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(680, 620)
        self.setStyleSheet("QDialog { background: #f0f4f8; }")

        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(10)

        # head = QLabel("学习做完了哪些事、得到了什么参数")
        # head.setStyleSheet("font-size: 15px; font-weight: 600; color: #2d3748;")
        # lo.addWidget(head)
        # lo.addWidget(create_info_label(
        #     "下面每一块都对应检测时真正用到的参数。若某一项明显不对，"
        #     "回到对应步骤调整后重新学习。"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        hv = QVBoxLayout(host)
        hv.setContentsMargins(0, 0, 6, 0)
        hv.setSpacing(10)
        hv.setAlignment(Qt.AlignmentFlag.AlignTop)

        if preview is not None:
            cap = QLabel("学习结果叠加（绿=焊层区域，红框=空洞）")
            cap.setStyleSheet("color:#718096; font-size:12px;")
            hv.addWidget(cap)
            pic = QLabel()
            pix = preview if isinstance(preview, QPixmap) else QPixmap.fromImage(preview)
            pic.setPixmap(pix.scaledToWidth(
                min(620, max(320, pix.width())),
                Qt.TransformationMode.SmoothTransformation))
            pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pic.setStyleSheet("background:#ffffff; border:1px solid #e2e8f0;"
                              " border-radius:6px; padding:4px;")
            hv.addWidget(pic)

        for name, rows, state in items:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background:#ffffff; border:1px solid #e2e8f0;"
                " border-radius:8px; }")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(12, 10, 12, 10)
            cv.setSpacing(4)
            mark = {'ok': '✔', 'warn': '⚠', 'info': '·'}.get(state, '·')
            color = {'ok': '#0F6E56', 'warn': '#A32D2D'}.get(state, '#2d3748')
            t = QLabel(f"{mark} {name}")
            t.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {color};")
            cv.addWidget(t)
            for r in rows:
                lb = QLabel(r)
                lb.setWordWrap(True)
                lb.setStyleSheet("color:#4a5568; font-size:12px;")
                cv.addWidget(lb)
            hv.addWidget(card)

        scroll.setWidget(host)
        lo.addWidget(scroll, 1)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(create_primary_button("知道了", self.accept))
        lo.addLayout(row)


def build_learn_items(model, extra=None):
    """把模型里的东西翻译成"人话"明细，供 LearnReportDialog 展示"""
    if not model:
        return [("学习失败", ["没有生成模型"], "warn")]
    sol = model.get('solder') or {}
    bg = model.get('background') or {}
    void = model.get('void') or {}
    geom = model.get('band_ref') or {}
    diag = model.get('diagnostics') or {}
    band_cfg = model.get('band') or {}

    items = []
    px_um = model.get('px_per_um') or 0.0
    n_marks = void.get('taught_count') or 0

    items.append(("示范区域统计", [
        f"示范区域灰度：中位 {sol.get('median')}，主要范围 {sol.get('p5')} ~ {sol.get('p95')}"
        f"（标准差 {sol.get('std')}）",
        # "焊层类取自示范区域内的「灰度主峰核」——比「取亮半边」更抗邻层污染",
    ], 'info'))

    sep = diag.get('solder_bg_separability')
    rows = [f"焊层阈值 t_焊层 = {sol.get('threshold')}",
            f"对比背景类：中位 {bg.get('median')}，主要范围 {bg.get('p5')} ~ {bg.get('p95')}",
            f"两类可分性 = {sep}（<1.5 示范不够典型，建议重画区域或补点空洞）"]
    sf = diag.get('bg_same_gray_frac') or 0
    if sf > 0.2:
        rows.append(f"⚠ 周边有 {sf * 100:.0f}% 的像素与焊料同灰度，已自动剔除"
                    f"（这类像素若混进背景类会把阈值推高）")
    items.append(("焊层 / 背景两类分离",
                  rows, 'warn' if (sep is not None and sep < 1.5) else 'ok'))

    items.append(("空洞（来自你点选的典型空洞）", [
        f"点选 {n_marks} 个；点选面积范围 "
        f"{min([void.get('min_area_taught', 0)] if n_marks else [0])} ~ "
        f"{void.get('max_area') or '—'} px²（仅供参考，不再作为检测下限）",
        f"空洞阈值 t_空洞 = {void.get('threshold')}"
        f"（低于它算空洞；检测时还会加「深度容差」偏移）",
        f"检测用面积下限：自动（按焊层带面积 0.02%、下限 12px²）",
    ], 'ok' if void.get('threshold') is not None else 'warn'))

    if geom:
        items.append(("几何基准（用于批量时与示教模板比对）", [
            f"归一化中心 ({geom.get('cx_norm')}, {geom.get('cy_norm')})，"
            f"宽高占比 {geom.get('w_norm')} × {geom.get('h_norm')}",
            f"面积占比 {geom.get('area_frac')}，长宽比 {geom.get('aspect')}",
            # "批量时若某张图与它的偏差超阈值（位置 15%/面积 0.4~2.5 倍/长宽比 0.5~2.0），"
            # "会在结果里告警——通常意味着那批图需要单独示教",
        ], 'ok'))

    items.append(("比例尺", [
        f"px/μm = {px_um:.2f}" if px_um > 0 else
        "未标定——仍然可以用像素平方出结果，无实际面积换算",
    ], 'ok' if px_um > 0 else 'info'))

    items.append(("检测细节参数", [
        f"最小宽度过滤 {band_cfg.get('min_thickness_px')} px"
        f"（剔除界面薄滴/毛刺，0 = 关闭）",
        f"贴边空洞缺口桥接：" + ("自动" if int(band_cfg.get('bridge_win_px', -1)) < 0
                                  else ("关闭" if int(band_cfg.get('bridge_win_px', -1)) == 0
                                        else f"窗口 {band_cfg.get('bridge_win_px')} px")),
        # "批量时可再选「灵敏度」档位微调（标准 / 高灵敏）",
    ], 'info'))

    if extra:
        items.extend(extra)
    return items
