"""统一提示：底部 toast 与带「复制详情 / 打开日志」的消息框。"""

import logging

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox

from app_paths import log_dir


def show_toast(parent, text, ms=1800):
    """窗口底部轻提示（成功/简短反馈），不打断操作。"""
    window = parent.window() if parent is not None else None
    if window is None:
        return
    old = getattr(window, '_toast', None)
    if old is not None:
        try:
            old.hide()
            old.deleteLater()
        except RuntimeError:
            pass
    toast = QLabel(text, window)
    toast.setObjectName('Toast')
    toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
    toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    toast.setMaximumWidth(max(280, window.width() - 80))
    toast.adjustSize()
    x = max(8, (window.width() - toast.width()) // 2)
    y = max(8, window.height() - toast.height() - 44)
    toast.move(x, y)
    toast.show()
    toast.raise_()
    window._toast = toast

    def _expire():
        try:
            toast.deleteLater()
        except RuntimeError:
            pass

    QTimer.singleShot(ms, _expire)


def show_message(parent, title, text, level='info', detail=''):
    """统一消息框：信息/警告/错误；错误带日志入口。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon({'info': QMessageBox.Icon.Information,
                 'warning': QMessageBox.Icon.Warning,
                 'error': QMessageBox.Icon.Critical}.get(
                     level, QMessageBox.Icon.Information))
    box.setText(text)
    if detail:
        box.setDetailedText(detail)

    copy_btn = None
    log_btn = None
    if detail:
        copy_btn = box.addButton('复制详情', QMessageBox.ButtonRole.ActionRole)
        copy_btn.setObjectName('SecondaryBtn')
    if level == 'error':
        log_btn = box.addButton('打开日志', QMessageBox.ButtonRole.ActionRole)
        log_btn.setObjectName('SecondaryBtn')
    ok_btn = box.addButton('确定', QMessageBox.ButtonRole.AcceptRole)
    ok_btn.setObjectName('PrimaryBtn')

    if level == 'error':
        logging.getLogger('Aurascope').warning('%s：%s', title, text)

    box.exec()
    clicked = box.clickedButton()
    if copy_btn is not None and clicked is copy_btn:
        QApplication.clipboard().setText(detail)
    elif log_btn is not None and clicked is log_btn:
        QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir()))


def show_info(parent, title, text, detail=''):
    show_message(parent, title, text, 'info', detail)


def show_warning(parent, title, text, detail=''):
    show_message(parent, title, text, 'warning', detail)


def show_error(parent, title, text, detail=''):
    show_message(parent, title, text, 'error', detail)
