"""金锡焊空洞分析 - 主入口"""

import logging
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "windows"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from styles import STYLESHEET
from main_window import MainWindow
from app_paths import resource_path
from app_version import APP_VERSION
from logging_setup import install_excepthook, setup_logging
from ui_components import LoadingSplash


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
    # 启动图是独立顶层窗口，它一关就把应用带走，表现就是「闪一下窗口就没了」
    app.setQuitOnLastWindowClosed(False)

    # 启动图：先把字母动画跑完，再装配主窗口，窗口一就绪立刻淡出
    splash = LoadingSplash()
    splash.show()
    splash.pre_animate(600)

    logger = logging.getLogger('Aurascope')
    try:
        window = MainWindow()
    except Exception:
        # 窗口模式(console=False)下 exe 没有控制台，异常必须落盘才能排查
        logger.exception('主窗口装配失败')
        splash.close()
        raise

    # 退出改成显式绑定主窗口：不再依赖 quitOnLastWindowClosed 的隐式规则
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    window.destroyed.connect(lambda *_: app.quit())
    window.show()
    logger.info('主窗口已显示')
    splash.finish()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
