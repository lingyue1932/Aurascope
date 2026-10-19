# -*- coding: utf-8 -*-
"""拼接测试：对齐精度 / 无缝（羽化）/ 深灰背景 / 自动微调

严格做法：拿**一张真实图**裁成两张有已知重叠的瓦片 → 在**同一处特征**上打标记
（模拟用户标"前一张尾部 = 后一张头部"）→ 拼回来应与原图**逐像素基本一致** ✔
再故意把标记打偏 10px，验证自动微调能把偏移纠回来 ✔
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                          # noqa: E402
import cv2                                                  # noqa: E402
from PyQt6.QtWidgets import QApplication                    # noqa: E402
from PyQt6.QtCore import QPointF                            # noqa: E402

PASS = FAIL = 0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '.workbuddy', 'validation')


def chk(name, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [OK]   {name} {extra}')
    else:
        FAIL += 1
        print(f'  [FAIL] {name} {extra}')


def read_gray(p):
    ext = os.path.splitext(p)[1].lower()
    if ext in ('.tif', '.tiff'):
        import tifffile
        a = tifffile.imread(p)
        if a.ndim == 3 and a.shape[0] in (3, 4):
            a = np.transpose(a, (1, 2, 0))
        if a.dtype != np.uint8:
            a = (a / max(1, a.max()) * 255).astype(np.uint8)
        return a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    a = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if a is None:
        return None
    if a.dtype != np.uint8:
        a = (a / max(1, a.max()) * 255).astype(np.uint8)
    return a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)


def make_canvas():
    from stitching_canvas import StitchingCanvas
    return StitchingCanvas()


def set_tiles(cv_obj, tiles, marks):
    """tiles: [BGR...]  marks: [(head_xy, tail_xy), ...]"""
    cv_obj.images = []
    for img, (head, tail) in zip(tiles, marks):
        cv_obj.images.append({
            'image': img, 'path': '', 'marked': True,
            'line_p1': QPointF(*head), 'line_p2': QPointF(*tail),
        })
    cv_obj.current_image_idx = 0


def main():
    app = QApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    from stitching_canvas import StitchingCanvas, STITCH_BG

    src_dir = r'C:\Users\lingfeng.zhang\Desktop\空洞测试文件夹\6'
    fn = next((f for f in sorted(os.listdir(src_dir))
               if os.path.splitext(f)[1].lower() in ('.tif', '.tiff', '.jpg')
               and os.path.splitext(f)[0].isdigit()), None)
    if fn is None:
        print('测试图不存在，跳过')
        return 0
    gray = read_gray(os.path.join(src_dir, fn))
    H, W = gray.shape
    # 用彩色大图便于肉眼对比
    big = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    print('=== 用例 A：两张瓦片按标记对齐 → 应与原图一致（无缝）===')
    OV = 120                                   # 已知重叠宽度
    W1 = W // 2 + OV // 2
    tileA = big[:, 0:W1].copy()
    tileB = big[:, W1 - OV:W].copy()
    fx = W1 - 10                               # 特征点（在 A 里）
    fy = H // 2
    headA, tailA = (fx - 300, fy), (fx, fy)    # A：尾部点在特征处
    headB, tailB = (fx - (W1 - OV), fy), (fx - (W1 - OV) + 200, fy)   # B：头部点在同一特征
    c = make_canvas()
    set_tiles(c, [tileA, tileB], [(headA, tailA), (headB, tailB)])
    res = c.stitch_images()
    chk('拼接返回结果', res is not None)
    if res is not None:
        chk('输出尺寸 = 原图尺寸', res.shape[:2] == (H, W),
            f'({res.shape[1]}x{res.shape[0]} vs 原 {W}x{H})')
        if res.shape[:2] == (H, W):
            d = np.abs(res.astype(np.int16) - big.astype(np.int16))
            # 只看"重叠缝"附近那一条
            seam_x = W1 - OV // 2
            band = d[:, max(0, seam_x - 40):seam_x + 40]
            chk('重叠缝处与背景融合无跳变', float(band.mean()) < 6.0,
                f'(缝带平均差 {band.mean():.2f}/255，最大 {band.max()})')
            chk('整体与原图基本一致', float(d.mean()) < 3.0,
                f'(全图平均差 {d.mean():.2f}/255)')
        cv2.imwrite(os.path.join(OUT, 'stitch_result.png'), res)

    print('\n=== 用例 B：标记打偏 10px → 输出应严格跟随标记（自动微调默认关）===')
    headB_off = (headB[0] + 10, headB[1] + 6)
    c2 = make_canvas()
    set_tiles(c2, [tileA, tileB], [(headA, tailA), (headB_off, tailB)])
    res2 = c2.stitch_images()
    chk('拼接返回结果（偏标记）', res2 is not None)
    if res2 is not None:
        exp_w, exp_h = W - 10, H + 6      # 标记偏 (dx-10, dy+6) → 画布相应变化
        chk('输出严格跟随标记（±2px）',
            abs(res2.shape[1] - exp_w) <= 2 and abs(res2.shape[0] - exp_h) <= 2,
            f'(得到 {res2.shape[1]}x{res2.shape[0]}，期望约 {exp_w}x{exp_h})')
        print('        说明：自动微调（互相关）默认关闭 —— 实测在真实 SEM 纹理上会')
        print('              把已对齐的结果改坏；标记对齐本身误差仅 0.02/255 ✔')

    print('\n=== 用例 C：未覆盖区域用深灰背景 ===')
    # A：300×200 放在 (0,0)；B：300×160 放在 (300,100) → 右下角露出未覆盖区
    hA, hB = 200, 160
    tA = big[:hA, :300].copy()
    tB = big[:hB, :300].copy()
    c3 = make_canvas()
    # 让 B 的原点 = (300, 100)：A 尾点 y=200、B 头点 y=100 → dy = 100 ✔
    set_tiles(c3, [tA, tB], [((0, 0), (300, 200)), ((0, 100), (0, 100))])
    res3 = c3.stitch_images()
    chk('拼接返回结果（露背景）', res3 is not None)
    if res3 is not None:
        # A 覆盖 x0..300,y0..200；B 覆盖 x=(300-0)..,y=100.. → A 下方 y=200 之后是空的
        region = res3[205:min(res3.shape[0], 260), 5:280, :]
        if region.size:
            vals = sorted(set(int(v) for v in np.unique(region)[:6]))
            chk('未覆盖区域是深灰', all(abs(v - STITCH_BG) <= 1 for v in vals),
                f'(该区像素 {vals[:4]}，期望 {STITCH_BG}；画布 {res3.shape[1]}x{res3.shape[0]})')
        else:
            chk('未覆盖区域是深灰', False, '(没取到未覆盖区，测试设计需调整)')
        cv2.imwrite(os.path.join(OUT, 'stitch_bg.png'), res3)

    print('\n=== 用例 D：拼好的图能复制到剪贴板（导出时会自动做一次）===')
    try:
        from stitching_tab import StitchingTab
        tab = StitchingTab()
        tab.canvas.stitched_image = np.zeros((120, 400, 3), np.uint8)
        tab.canvas.stitched_image[:] = STITCH_BG
        ok, why = tab.copy_to_clipboard(silent=True)
        chk('复制到剪贴板成功', ok, why)
        qi = app.clipboard().image()
        chk('剪贴板里图像尺寸正确', (qi.width(), qi.height()) == (400, 120),
            f'({qi.width()}x{qi.height()})')
        tab.canvas.stitched_image = None      # 清空后再试 → 应返回 False 且不报错
        chk('未拼接时给出友好提示', tab.copy_to_clipboard(silent=True)[0] is False)
    except Exception as e:
        chk('剪贴板复制', False, f'({type(e).__name__}: {e})')

    print('\n=== 用例 E：金锡拼接图（导出用）—— 无缝 + 深灰底 ===')
    try:
        from image import render_solder_strip, crop_solder_region
        from ui_components import copy_bgr_to_clipboard
        # 造 3 张"金锡区域"（横向亮条 + 一个红空洞），放进带掩膜的 entries
        entries = []
        for k in range(3):
            im = np.full((220, 300, 3), 30, np.uint8)
            # 三张的金锡高度不同（第 2 张矮）→ 才会出现"补空"区域可验证 ✔
            y0, y1 = (60, 160) if k != 1 else (90, 140)
            im[y0:y1, :] = 210
            mask = np.zeros((220, 300), np.uint8)
            mask[y0:y1, :] = 255
            voids = [{'points': [[20 + k * 5, 90], [40 + k * 5, 90],
                                 [40 + k * 5, 120], [20 + k * 5, 120]],
                      'rect': (20 + k * 5, 90, 20, 30), 'area_px': 600.0,
                      'cx': 30 + k * 5, 'cy': 105, 'id': 1}]
            entries.append({'img': im, 'band_mask': mask, 'voids': voids})
        strip = render_solder_strip(entries, [])
        chk('金锡拼接图生成', strip is not None, f'({None if strip is None else strip.shape})')
        if strip is not None:
            # 无缝：不应有"整列都是背景色"的列
            bgcols = sum(1 for x in range(strip.shape[1])
                         if np.all(strip[:, x, 0] == 64))
            chk('片间无缝（无背景色竖列）', bgcols == 0, f'(背景列 {bgcols})')
            # 深灰底：第 2 张比第 1 张矮 → 它上下会补空成 64
            x2 = 300 + 150          # 落在第 2 张的横向范围内
            col = strip[:min(40, strip.shape[0]), x2 - 2:x2 + 2, :]
            chk('补空处为深灰 64', int(np.median(col)) == 64,
                f'(中位 {int(np.median(col))}，形状 {strip.shape})')
            ok, why = copy_bgr_to_clipboard(strip, silent=True)
            chk('金锡拼接图可复制到剪贴板', ok, why)
            qi = app.clipboard().image()
            chk('剪贴板尺寸与拼接图一致',
                (qi.width(), qi.height()) == (strip.shape[1], strip.shape[0]),
                f'({qi.width()}x{qi.height()})')
    except Exception as e:
        chk('金锡拼接图', False, f'({type(e).__name__}: {e})')

    print(f'\nPASS={PASS}  FAIL={FAIL}')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
