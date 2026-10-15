# -*- coding: utf-8 -*-
"""快速示教弹窗测试（离屏可跑）

覆盖：
· 打开即自动识别焊层区域 → 自动进第②步
· 点选空洞 → 自动学习 → 状态条出现 t_焊层/t_空洞/空洞率
· **Delete 键删除点选** → 重新学习、编号刷新
· 完成并采用 → get_model() 返回标准示教配方
· 手绘多边形定义焊层区域（模拟画一个内缩矩形）
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 用**隔离的临时配方库**：把参考配方(6)拷进来做对照，避免污染用户桌面配方 ✗
_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    '.workbuddy', 'tmp_recipes')
os.makedirs(_TMP, exist_ok=True)
_SRC = r'C://Users//lingfeng.zhang//Desktop//recipes'
for _f in ('6.taught.json', '6_bar.png'):
    _a = os.path.join(_SRC, _f)
    if os.path.isfile(_a):
        import shutil
        shutil.copy2(_a, os.path.join(_TMP, _f))
os.environ['AURASCOPE_RECIPE_DIR'] = _TMP

import numpy as np                                         # noqa: E402
import cv2                                                 # noqa: E402
from PyQt6.QtWidgets import QApplication                   # noqa: E402
from PyQt6.QtGui import QFontDatabase, QFont               # noqa: E402
from PyQt6.QtCore import Qt                                # noqa: E402

PASS = FAIL = 0


def chk(name, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [OK]   {name} {extra}')
    else:
        FAIL += 1
        print(f'  [FAIL] {name} {extra}')


def load_gray(p):
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


class _KeyEvent:
    def __init__(self, key):
        self._k = key

    def key(self):
        return self._k


def main():
    app = QApplication(sys.argv)
    fp = r'C:\Windows\Fonts\msyh.ttc'
    if os.path.exists(fp):
        QFontDatabase.addApplicationFont(fp)
    app.setFont(QFont('Microsoft YaHei', 9))
    from styles import STYLESHEET
    app.setStyleSheet(STYLESHEET)
    from quick_teach_dialog import QuickTeachDialog, ImagePickerDialog
    from image import apply_taught_model
    from recipe import load_recipe

    folder = r'C:\Users\lingfeng.zhang\Desktop\空洞测试文件夹\6'
    img_path = os.path.join(folder, '3.tif')
    if not os.path.isfile(img_path):
        print('测试图不存在，跳过：', img_path)
        return 0
    gray = load_gray(img_path)
    print('=== 快速示教弹窗测试 ===')
    dlg = QuickTeachDialog(gray, sample_name='3.tif', title='快速示教（测试）')
    dlg.resize(1120, 720)
    dlg.show()
    app.processEvents()

    # ① 打开即自动识别
    chk('自动识别焊层区域', dlg.roi_mask is not None and np.count_nonzero(dlg.roi_mask) > 0,
        f'({0 if dlg.roi_mask is None else int(np.count_nonzero(dlg.roi_mask))}px²)')
    chk('识别成功自动进第②步', dlg._step == 1)
    chk('画布已有焊层多边形', len(dlg.roi_pts) >= 3, f'({len(dlg.roi_pts)} 顶点)')
    chk('完成按钮初始不可用', not dlg.btn_ok.isEnabled())

    # ② 点选真实空洞（用参考配方检出的空洞中心模拟人点）
    ref = load_recipe('6')
    r0 = apply_taught_model(gray, ref) if ref else {}
    voids = (r0.get('voids') or [])[:4]
    chk('参考配方有空洞可点', len(voids) >= 2, f'({len(voids)} 个)')
    n_ok = 0
    for v in voids[:3]:
        dlg._on_click_void(float(v['cx']), float(v['cy']))
        app.processEvents()
        if len(dlg.blobs) > n_ok:
            n_ok += 1
    chk('点选抓到暗核', n_ok >= 2, f'(抓到 {n_ok}/{min(3, len(voids))} 个)')
    dlg._learn_now()                     # 绕过防抖计时器，立即学习
    app.processEvents()
    chk('已学习出模型', dlg.model is not None)
    chk('完成按钮已可用', dlg.btn_ok.isEnabled())
    if dlg.model and ref:
        sol = (dlg.model.get('solder') or {}).get('threshold', 0)
        voi = (dlg.model.get('void') or {}).get('threshold', 0)
        chk('t_焊层 与参考配方接近', abs(sol - float(ref['solder']['threshold'])) <= 25,
            f'(本 {sol:.0f} vs 参考 {ref["solder"]["threshold"]:.0f})')
        chk('t_空洞 与参考配方接近', abs(voi - float(ref['void']['threshold'])) <= 40,
            f'(本 {voi:.0f} vs 参考 {ref["void"]["threshold"]:.0f})')
    print('  状态条:', dlg.lbl_stat.text())

    # ③ Delete 键删除点选
    n_before = len(dlg.blobs)
    dlg.keyPressEvent(_KeyEvent(Qt.Key.Key_Delete))
    app.processEvents()
    dlg._learn_now()
    app.processEvents()
    chk('Delete 删掉一个点选', len(dlg.blobs) == n_before - 1,
        f'({n_before} → {len(dlg.blobs)})')
    chk('删除后仍能学习', dlg.model is not None)
    print('  状态条:', dlg.lbl_stat.text())

    # ④ 手绘多边形定义焊层区域（模拟画一个内缩矩形）
    h, w = gray.shape
    poly = [(w * 0.05, h * 0.05), (w * 0.95, h * 0.05),
            (w * 0.95, h * 0.55), (w * 0.05, h * 0.55)]
    dlg._on_poly(poly)
    app.processEvents()
    chk('手绘多边形生效', dlg.roi_mask is not None and len(dlg.roi_pts) == 4)

    # ⑤ 保存为配方（勾选项）→ 完成并采用
    from recipe import list_recipes
    dlg.chk_save.setChecked(True)
    dlg.edit_name.setText('测试_快速示教')
    dlg._on_ok()
    chk('配方已写入配方库', any('测试_快速示教' in d or '测试_快速示教' in f
                                for d, f in list_recipes(kind='taught')),
        f'(saved_name={dlg.saved_name})')
    m = dlg.get_model()
    chk('完成返回标准配方', isinstance(m, dict) and m.get('type') == 'taught')
    chk('配方可被引擎应用',
        bool(m) and bool((apply_taught_model(gray, m) or {}).get('ok')))
    if m:
        print('  返回配方:', m.get('note'),
              '| t_焊层=%.0f t_空洞=%.0f' % (m['solder']['threshold'],
                                            m['void']['threshold']))

    # ⑥ 基准图选择器（用户可自行选择示教图片）
    imgs = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
            if os.path.splitext(f)[1].lower() in ('.tif', '.tiff', '.jpg', '.jpeg', '.png')][:6]
    try:
        pk = ImagePickerDialog(imgs, current=imgs[0], title='选择器测试')
        chk('选择器列出候选图', pk.list.count() == len(imgs), f'({pk.list.count()} 张)')
        chk('默认选中自动挑的那张',
            os.path.abspath(pk.selected()) == os.path.abspath(imgs[0]))
        pk.list.setCurrentRow(2)
        pk._on_ok()
        chk('选第 3 张后 selected 返回它',
            os.path.abspath(pk.selected()) == os.path.abspath(imgs[2]),
            f'({os.path.basename(pk.selected())})')
        print('  选择器状态:', pk.lbl_sel.text())
    except Exception as e:
        chk('基准图选择器', False, f'({type(e).__name__}: {e})')

    # ⑦ 对话框暴露"换图"入口
    chk('对话框有更换图片按钮', hasattr(dlg, 'btn_pick_img'))

    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '.workbuddy', 'validation'), exist_ok=True)
    dlg.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 '.workbuddy', 'validation', 'quick_teach_dialog.png'))
    print('  截图已存 .workbuddy/validation/quick_teach_dialog.png')
    print(f'\nPASS={PASS}  FAIL={FAIL}')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
