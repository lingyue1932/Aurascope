"""金锡焊空洞分析 - 主入口"""

import logging
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "windows"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

from styles import STYLESHEET
from main_window import MainWindow
from app_paths import resource_path
from app_version import APP_VERSION
from logging_setup import install_excepthook, setup_logging


def _close_splash(attempt=1):
    """关掉 PyInstaller bootloader 启动图；源码运行没有 pyi_splash，直接跳过。

    启动图是独立进程的置顶小窗，只有 pyi_splash.close() 能收掉；
    一旦失败用户就会一直看到它盖在主窗口上（表现为“卡在启动界面”）。
    因此这里不吞异常：失败写日志并重试，便于事后定位。
    """
    logger = logging.getLogger('Aurascope')
    try:
        import pyi_splash
    except ImportError:
        if getattr(sys, 'frozen', False):
            logger.warning('启动图模块 pyi_splash 缺失，启动图将无法关闭')
        return
    try:
        pyi_splash.close()
        logger.info('启动图已关闭')
    except Exception:
        logger.warning('关闭启动图失败（第 %d 次）', attempt, exc_info=True)
        if attempt < 3:
            QTimer.singleShot(1500, lambda: _close_splash(attempt + 1))


def main():
    """主函数"""
    log_path = setup_logging()
    install_excepthook()
    logging.getLogger('Aurascope').info(
        '启动 Aurascope %s（frozen=%s）日志：%s',
        APP_VERSION, getattr(sys, 'frozen', False), log_path)

    # 必须在创建 QApplication 之前设置
    if hasattr(Qt, 'HighDpiScaleFactorRoundingPolicy'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(resource_path('logo_1.ico')))
    app.setStyleSheet(STYLESHEET)

    # 启动图阶段先关掉「最后一个窗口关闭 = 退出」：
    # 启动图/对话框关掉时不能把应用带走
    app.setQuitOnLastWindowClosed(False)

    # 启动图：双击时 bootloader 已经显示静态卡片，这里只负责就绪后关掉
    logger = logging.getLogger('Aurascope')
    try:
        window = MainWindow()
    except Exception:
        # 窗口模式(console=False)下 exe 没有控制台，异常必须落盘才能排查
        logger.exception('主窗口装配失败')
        _close_splash()
        raise

    # 退出改成显式绑定主窗口：不再依赖 quitOnLastWindowClosed 的隐式规则
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    window.destroyed.connect(lambda *_: app.quit())
    window.show()
    logger.info('主窗口已显示')
    # 启动图若还在，会把主窗口盖住；主动抬到前台
    window.raise_()
    window.activateWindow()
    # 等窗口画出第一帧再撤启动图，避免白屏闪烁
    QTimer.singleShot(0, _close_splash)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
