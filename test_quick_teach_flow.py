# -*- coding: utf-8 -*-
"""端到端集成测试：主窗口 → 批次文件夹 → 快速示教（弹窗打桩）→ 整批检测

为什么要有这个测试
------------------
2026-10-15 出过一次线上 bug：'TeachBatchTab' object has no attribute '_pick_setup_image'
—— 原因是我替换代码块时误删了该方法，而当时的"冒烟测试"只启动窗口、没走这条路径 ✗。
所以这里把**真实调用链**跑通：`on_quick_teach()` 里做的事一件不少（除弹窗交互本身）。
"""
import os
import shutil
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 隔离的临时配方库：把参考配方(6)拷进来做对照，避免污染用户桌面配方；
# 另外**另存一份 ref6** —— 因为快速示教会把「6」覆盖掉，对比基准必须另存 ✗
_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    '.workbuddy', 'tmp_recipes')
_SRC = r'C:\Users\lingfeng.zhang\Desktop\recipes'
os.makedirs(_TMP, exist_ok=True)
for _f in os.listdir(_TMP):
    try:
        os.remove(os.path.join(_TMP, _f))
    except OSError:
        pass
for _f in ('6.taught.json', '6_bar.png'):
    _a = os.path.join(_SRC, _f)
    if os.path.isfile(_a):
        shutil.copy2(_a, os.path.join(_TMP, _f))
if os.path.isfile(os.path.join(_TMP, '6.taught.json')):
    shutil.copy2(os.path.join(_TMP, '6.taught.json'),
                 os.path.join(_TMP, 'ref6.taught.json'))
os.environ['AURASCOPE_RECIPE_DIR'] = _TMP

import numpy as np                                          # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog  # noqa: E402
from PyQt6.QtCore import QEventLoop, QTimer                  # noqa: E402
from PyQt6.QtGui import QFontDatabase, QFont                # noqa: E402

PASS = FAIL = 0


def chk(name, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [OK]   {name} {extra}')
    else:
        FAIL += 1
        print(f'  [FAIL] {name} {extra}')


def main():
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    app = QApplication(sys.argv)
    fp = r'C:\Windows\Fonts\msyh.ttc'
    if os.path.exists(fp):
        QFontDatabase.addApplicationFont(fp)
    app.setFont(QFont('Microsoft YaHei', 9))
    from styles import STYLESHEET
    app.setStyleSheet(STYLESHEET)

    print('=== 端到端：快速示教 → 整批 ===')
    # 0) 主窗口能构造（应用级冒烟）
    try:
        from main_window import MainWindow
        win = MainWindow()
        win.resize(1400, 800)
        win.show()
        app.processEvents()
        chk('主窗口构造成功', True)
    except Exception as e:
        chk('主窗口构造成功', False, f'({type(e).__name__}: {e})')
        print(f'\nPASS={PASS}  FAIL={FAIL}')
        return 1

    from teach_batch_tab import TeachBatchTab
    from image import apply_taught_model, learn_taught_model, grab_local_dark_blob
    from recipe import load_recipe
    import cv2

    tab = TeachBatchTab()
    tab.resize(1200, 760)
    tab.show()

    folder = r'C:\Users\lingfeng.zhang\Desktop\空洞测试文件夹\6'
    chk('批次文件夹存在', os.path.isdir(folder))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: folder)
    tab.pick_folder()
    app.processEvents()
    chk('选文件夹后有图片', bool(tab.batch_paths), f'({len(tab.batch_paths)} 张)')

    # 1) 代表性图挑选（就是这次 bug 所在的方法）
    try:
        sp = tab._pick_setup_image()
        chk('_pick_setup_image 可用', bool(sp), f'({os.path.basename(sp) if sp else "-"})')
        stem = os.path.splitext(os.path.basename(sp))[0]
        chk('挑的是纯数字切片', stem.isdigit(), f'(stem={stem})')
    except Exception as e:
        chk('_pick_setup_image 可用', False, f'({type(e).__name__}: {e})')
        sp = None

    # 2) 快速示教：把弹窗打桩成"自动点几个参考空洞并学习"
    import quick_teach_dialog as qtd
    holder = {}

    class FakeTeachDialog:
        def __init__(self, gray, sample_name='', parent=None, title='',
                     image_bgr=None, suggest_name='', candidates=None,
                     current_path=''):
            self.gray = gray
            self.sample_name = sample_name
            self.suggest_name = suggest_name
            self.candidates = list(candidates or [])
            self.current_path = current_path
            self.picked_path = None          # 换图约定：非空且返回 Accepted+100
            self.saved_name = None
            self.model = None
            ref = load_recipe('ref6')
            r = apply_taught_model(gray, ref) if ref else {}
            self._n_pick = 0
            if r.get('ok') and r.get('voids'):
                roi = (r['band_mask'] > 0).astype(np.uint8) * 255
                marks, blobs = [], []
                for v in r['voids'][:3]:
                    b, a = grab_local_dark_blob(gray, float(v['cx']), float(v['cy']),
                                                float(ref['solder']['threshold']),
                                                region_mask=roi)
                    if b is not None:
                        marks.append((float(v['cx']), float(v['cy'])))
                        blobs.append(b)
                if blobs:
                    self.model = learn_taught_model(gray, roi, marks, void_blobs=blobs)
                    self._n_pick = len(marks)
                    if self.model:
                        self.model['name'] = '<快速示教>'
                        self.model['note'] = f"快速示教：点选 {len(marks)} 个空洞"
            holder['d'] = self

        def exec(self):
            if not self.model:
                return QDialog.DialogCode.Rejected
            # 模拟"保存为配方"：名字用调用方建议的（批次文件夹名）
            from recipe import save_taught
            name = self.suggest_name or 'flow_test'
            self.model['name'] = name
            save_taught(self.model)
            self.saved_name = name
            return QDialog.DialogCode.Accepted

        def get_model(self):
            return self.model

    qtd.QuickTeachDialog = FakeTeachDialog
    try:
        tab.on_quick_teach()
        app.processEvents()
        chk('on_quick_teach 走通', tab.quick_model is not None,
            f'(点选 {holder.get("d")._n_pick if holder.get("d") else 0} 个)')
    except Exception as e:
        chk('on_quick_teach 走通', False, f'({type(e).__name__}: {e})')
        print(f'\nPASS={PASS}  FAIL={FAIL}')
        return 1
    # 3) 整批跑一遍（用快速示教模型，不需要配方）
    tab.combo_recipe.setCurrentIndex(-1)
    tab.start_batch()
    loop = QEventLoop()
    if getattr(tab, 'worker', None) is not None:
        tab.worker.finished.connect(loop.quit)
    QTimer.singleShot(180000, loop.quit)
    loop.exec()
    app.processEvents()
    ok = [r for r in tab.batch_results if r.get('ok')]
    rates = [r.get('void_rate', 0) * 100 for r in ok]
    bad = [r for r in tab.batch_results if not r.get('ok')]
    chk('整批出结果', len(ok) > 0, f'({len(ok)}/{len(tab.batch_results)} 张成功)')
    if bad:
        print('        未成功:', ', '.join(
            f"{r.get('filename')}({(r.get('warnings') or ['?'])[0][:26]})" for r in bad[:3]))
    chk('用的是快速示教模型', tab._last_model is tab.quick_model)
    if rates:
        chk('空洞率在合理区间', 0.0 <= min(rates) and max(rates) <= 30.0,
            f'(范围 {min(rates):.2f}%~{max(rates):.2f}% 均值 {np.mean(rates):.2f}%)')
        # 与人工配方对照（同一批）
        ref = load_recipe('ref6')
        man = []
        from teach_batch_tab import read_image_file as _rif
        for r in tab.batch_results:
            if not r.get('ok'):
                continue
            img = _rif(r['path'])
            g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            rr = apply_taught_model(g, ref)
            if rr.get('ok'):
                man.append(rr['void_rate'] * 100)
        if man and len(man) == len(rates):
            dev = float(np.abs(np.array(rates) - np.array(man)).mean())
            chk('与人工配方偏差可接受', dev <= 1.5,
                f'(平均绝对偏差 {dev:.2f}%　人工均值 {np.mean(man):.2f}%　本 {np.mean(rates):.2f}%)')

    chk('保存后提示条说明已入库', '保存为配方' in tab.lbl_quick_teach.text(),
        f'("{tab.lbl_quick_teach.text()[:34]}…")')
    from recipe import list_recipes
    chk('配方库里出现该配方',
        any('6' == d or f == '6.taught.json' for d, f in list_recipes(kind='taught')),
        f'(共 {len(list_recipes(kind="taught"))} 个)')
    chk('下拉框已选中该配方',
        '6' in (tab.combo_recipe.currentText() or ''),
        f'(当前：{tab.combo_recipe.currentText()})')
    # 复用路径：重新选同一文件夹 → 应自动带出同名配方
    tab.quick_model = None
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: folder)
    tab.pick_folder()
    app.processEvents()
    chk('再选同文件夹自动带出配方', '已自动带出同名配方' in tab.lbl_quick_teach.text(),
        f'("{tab.lbl_quick_teach.text()[:30]}…")')


    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '.workbuddy', 'validation'), exist_ok=True)
    tab.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 '.workbuddy', 'validation', 'quick_flow.png'))
    print('  截图已存 .workbuddy/validation/quick_flow.png')
    print(f'\nPASS={PASS}  FAIL={FAIL}')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
