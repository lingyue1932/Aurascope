"""统一日志与全局异常兜底。"""

import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

from app_paths import log_dir

_LOG_FILE = None


def setup_logging():
    """初始化滚动日志（单文件 1MB × 5），返回日志文件路径。"""
    global _LOG_FILE
    _LOG_FILE = os.path.join(log_dir(), 'aurascope.log')
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    installed = any(
        isinstance(h, RotatingFileHandler) and getattr(h, '_aurascope', False)
        for h in root.handlers)
    if not installed:
        handler = RotatingFileHandler(
            _LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding='utf-8')
        handler._aurascope = True
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s [%(name)s] %(message)s'))
        root.addHandler(handler)
    return _LOG_FILE


def log_file():
    return _LOG_FILE or os.path.join(log_dir(), 'aurascope.log')


def _report_exception(exc_type, exc, tb, context='未捕获异常'):
    text = ''.join(traceback.format_exception(exc_type, exc, tb))
    logging.getLogger('Aurascope').critical('%s\n%s', context, text)
    return text


def _show_error_dialog(text):
    """统一的崩溃提示：复制详情 / 打开日志（不阻塞无 GUI 场景）。"""
    try:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return
        box = QMessageBox(QApplication.activeWindow())
        box.setWindowTitle('Aurascope 发生错误')
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText('程序遇到未处理的错误。\n详细信息已写入日志，可复制后反馈。')
        box.setDetailedText(text)
        copy_btn = box.addButton('复制详情', QMessageBox.ButtonRole.ActionRole)
        log_btn = box.addButton('打开日志', QMessageBox.ButtonRole.ActionRole)
        box.addButton('关闭', QMessageBox.ButtonRole.RejectRole)
        copy_btn.setObjectName('SecondaryBtn')
        log_btn.setObjectName('SecondaryBtn')
        box.exec()
        if box.clickedButton() is copy_btn:
            QApplication.clipboard().setText(text)
        elif box.clickedButton() is log_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir()))
    except Exception:
        logging.getLogger('Aurascope').exception('错误对话框显示失败')


def install_excepthook():
    """把主线程与工作线程的未捕获异常写入日志并提示用户。"""
    def hook(exc_type, exc, tb):
        if exc_type is KeyboardInterrupt:
            return
        text = _report_exception(exc_type, exc, tb)
        _show_error_dialog(text)

    sys.excepthook = hook

    def thread_hook(args):
        _report_exception(
            args.exc_type, args.exc_value, args.exc_traceback,
            context=f'线程 {getattr(args.thread, "name", "?")} 未捕获异常')

    threading.excepthook = thread_hook
