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


def _close_splash():
    """关掉 PyInstaller bootloader 启动图；源码运行没有 pyi_splash，直接跳过。"""
    try:
        import pyi_splash
    except ImportError:
        return
    try:
        pyi_splash.close()
    except Exception:
        pass


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
    # 等窗口画出第一帧再撤启动图，避免白屏闪烁
    QTimer.singleShot(0, _close_splash)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
