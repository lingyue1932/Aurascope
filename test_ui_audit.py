# -*- coding: utf-8 -*-
"""UI 走查：把每个 tab、每个关键弹窗都截一张图，供人工检查视觉缺陷"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('AURASCOPE_RECIPE_DIR',
                      r'C:\Users\lingfeng.zhang\Desktop\recipes')
sys.path.insert(0, r'D:\toolbox\0428')
OUT = r'D:\toolbox\0428\.workbuddy\validation\audit'
os.makedirs(OUT, exist_ok=True)

import numpy as np                                          # noqa: E402
import cv2                                                  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox       # noqa: E402
from PyQt6.QtGui import QFontDatabase, QFont                # noqa: E402


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
    from main_window import MainWindow

    w = MainWindow()
    w.resize(1440, 900)
    w.show()
    for _ in range(6):
        app.processEvents()

    tw = getattr(w, 'tab_widget', None) or getattr(w, 'tabs', None)
    names = []
    if tw:
        for i in range(tw.count()):
            t = tw.tabText(i)
            tw.setCurrentIndex(i)
            for _ in range(6):
                app.processEvents()
            fn = os.path.join(OUT, f'tab{i}_{t.strip().replace("/", "_")}.png')
            w.grab().save(fn)
            names.append((i, t.strip(), os.path.basename(fn)))
    for i, t, fn in names:
        print(f'  tab{i}: {t} → {fn}')

    # ---- 关键弹窗 ----
    try:
        import tifffile
        p = r'C:\Users\lingfeng.zhang\Desktop\空洞测试文件夹\6\3.tif'
        a = tifffile.imread(p)
        if a.dtype != np.uint8:
            a = (a / max(1, a.max()) * 255).astype(np.uint8)
        gray = a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
        import void_bridge_dummy  # noqa: F401
    except Exception:
        gray = None
        try:
            import tifffile
            p = r'C:\Users\lingfeng.zhang\Desktop\空洞测试文件夹\6\3.tif'
            a = tifffile.imread(p)
            if a.dtype != np.uint8:
                a = (a / max(1, a.max()) * 255).astype(np.uint8)
            gray = a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
        except Exception:
            gray = None

    # 快速示教弹窗
    dlg = None
    if gray is not None:
        try:
            from quick_teach_dialog import QuickTeachDialog
            import image as _im
            dlg = QuickTeachDialog(gray, title='走查：快速示教')
            dlg.resize(1120, 720)
            dlg.show()
            for _ in range(6):
                app.processEvents()
            dlg.grab().save(os.path.join(OUT, 'dlg_quick_teach.png'))
            print('  dlg: 快速示教 → dlg_quick_teach.png')
        except Exception as e:
            print('  快速示教弹窗构造失败:', type(e).__name__, e)

    # 图像选择器
    if gray is not None:
        try:
            from quick_teach_dialog import ImagePickerDialog
            folder = r'C:\Users\lingfeng.zhang\Desktop\空洞测试文件夹\6'
            imgs = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                    if os.path.splitext(f)[1].lower() in ('.tif', '.tiff', '.jpg', '.jpeg', '.png')][:8]
            pk = ImagePickerDialog(imgs, current=imgs[0], title='走查：选择示教图')
            pk.resize(760, 560)
            pk.show()
            for _ in range(6):
                app.processEvents()
            pk.grab().save(os.path.join(OUT, 'dlg_picker.png'))
            print('  dlg: 图片选择器 → dlg_picker.png')
        except Exception as e:
            print('  选择器构造失败:', type(e).__name__, e)

    # 学习报告弹窗
    try:
        from learn_dialog import LearnReportDialog, build_learn_items
        from recipe import load_recipe
        m = load_recipe('6')
        if m:
            items = build_learn_items(m)
            ld = LearnReportDialog(items, None, title='走查：学习报告')
            ld.show()
            for _ in range(6):
                app.processEvents()
            ld.grab().save(os.path.join(OUT, 'dlg_learn_report.png'))
            print('  dlg: 学习报告 → dlg_learn_report.png')
    except Exception as e:
        print('  学习报告构造失败:', type(e).__name__, e)

    print('\n截图目录:', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
