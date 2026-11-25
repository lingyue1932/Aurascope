"""关于窗口与离线帮助（Markdown）窗口。"""

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QTextBrowser,
                             QVBoxLayout)

from app_paths import build_date, log_dir, resource_path
from app_version import APP_VERSION
from recipe import recipe_dir
from ui_components import (create_card_subtitle, create_card_title,
                           create_divider, create_info_label,
                           create_primary_button, create_secondary_button)


def _open_dir(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class MarkdownDialog(QDialog):
    """离线查看随包分发的 Markdown 文档。"""

    def __init__(self, title, filename, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(780, 640)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(12)

        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        try:
            with open(resource_path(filename), encoding='utf-8') as stream:
                view.setMarkdown(stream.read())
        except OSError:
            view.setPlainText(f'未找到文档：{filename}\n请确认程序包内包含该文件。')
        lo.addWidget(view, 1)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(create_primary_button('关闭', self.accept))
        lo.addLayout(row)


class AboutDialog(QDialog):
    """版本、构建日期、许可、联系与数据/日志目录。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('关于 Aurascope')
        self.resize(540, 430)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 20, 20, 20)
        lo.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        pix = QPixmap(resource_path('logo_innolight.png'))
        if not pix.isNull():
            logo.setPixmap(pix.scaledToHeight(44))
        head.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(create_card_title('Aurascope'))
        titles.addWidget(create_card_subtitle('视觉检测与数据分析工具'))
        head.addLayout(titles)
        head.addStretch()
        lo.addLayout(head)
        lo.addWidget(create_divider())

        self._data_dir = self._safe_dir(recipe_dir)
        self._logs_dir = self._safe_dir(log_dir)
        for label, value in (
                ('版本', APP_VERSION),
                ('构建日期', build_date()),
                ('许可', 'MIT License'),
                ('联系', 'Innolight · 工艺工程'),
        ):
            lo.addLayout(self._info_row(label, value))
        self._dir_row(lo, '数据目录', self._data_dir)
        self._dir_row(lo, '日志目录', self._logs_dir)
        lo.addStretch()

        row = QHBoxLayout()
        row.addWidget(create_secondary_button('复制版本信息', self._copy_info))
        row.addStretch()
        row.addWidget(create_primary_button('关闭', self.accept))
        lo.addLayout(row)

    @staticmethod
    def _safe_dir(getter):
        try:
            return getter()
        except OSError:
            return '—'

    @staticmethod
    def _info_row(label, value):
        row = QHBoxLayout()
        row.setSpacing(10)
        tag = create_info_label(label)
        tag.setFixedWidth(72)
        row.addWidget(tag)
        row.addWidget(create_info_label(value), 1)
        return row

    def _dir_row(self, layout, label, path):
        row = QHBoxLayout()
        row.setSpacing(10)
        tag = create_info_label(label)
        tag.setFixedWidth(72)
        row.addWidget(tag)
        row.addWidget(create_info_label(path), 1)
        open_btn = create_secondary_button('打开')
        open_btn.setFixedWidth(64)
        if path and path != '—':
            open_btn.clicked.connect(lambda _=False, p=path: _open_dir(p))
        else:
            open_btn.setEnabled(False)
        row.addWidget(open_btn)
        layout.addLayout(row)

    def _copy_info(self):
        from PyQt6.QtWidgets import QApplication
        text = (f'Aurascope {APP_VERSION}\n'
                f'构建日期：{build_date()}\n'
                f'数据目录：{self._data_dir}\n'
                f'日志目录：{self._logs_dir}')
        QApplication.clipboard().setText(text)
