"""GitHub Releases 版本检查：纯解析逻辑 + 异步网络查询。

请求 `GET /repos/{owner}/{repo}/releases/latest`，在后台完成，
不阻塞界面；失败静默忽略。只有版本号比当前新且不是
draft/prerelease 时才发出 update_found 信号。
"""

import json
import logging
import os

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from packaging.version import InvalidVersion, Version

from app_version import APP_VERSION

REPO = 'lingyue1932/Aurascope'
LATEST_RELEASE_URL = f'https://api.github.com/repos/{REPO}/releases/latest'


def parse_release_tag(tag):
    """把 GitHub tag（可带 v 前缀）转成 Version；非法返回 None。"""
    if not tag:
        return None
    text = tag.strip()
    if text.lower().startswith('v'):
        text = text[1:]
    try:
        return Version(text)
    except InvalidVersion:
        return None


def release_is_newer(tag, current=APP_VERSION):
    """tag 对应的版本是否比 current 新；无法解析时视为不新。"""
    version = parse_release_tag(tag)
    if version is None:
        return False
    try:
        return version > Version(current)
    except InvalidVersion:
        return False


def should_show_update(info, skipped_version=None):
    """用户“忽略本次更新”后，同版本不再提示；更高版本照常提示。"""
    if not skipped_version:
        return True
    current = parse_release_tag((info or {}).get('version') or '')
    skipped = parse_release_tag(skipped_version)
    if current is None or skipped is None:
        return True
    return current.base_version != skipped.base_version


def pick_update_asset(payload):
    """从 release 的 assets 里挑出应用内更新用的 .zip 包。"""
    for asset in (payload.get('assets') or []):
        name = asset.get('name') or ''
        url = asset.get('browser_download_url') or ''
        if name.lower().endswith('.zip') and url:
            return {'name': name, 'url': url,
                    'size': int(asset.get('size') or 0)}
    return None


def parse_latest_release(payload):
    """从 GitHub latest release JSON 提取版本/链接/说明；跳过 draft 与 prerelease。"""
    if not isinstance(payload, dict):
        return None
    if payload.get('draft') or payload.get('prerelease'):
        return None
    tag = payload.get('tag_name') or ''
    version = parse_release_tag(tag)
    if version is None:
        return None
    return {
        'version': str(version),
        'tag': tag,
        'url': payload.get('html_url') or '',
        'notes': payload.get('body') or '',
        'asset': pick_update_asset(payload),
    }


class UpdateChecker(QObject):
    update_found = pyqtSignal(dict)
    check_finished = pyqtSignal(object, str)   # (info 或 None, 错误文案)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)

    def check(self, current=APP_VERSION, manual=False):
        # 开发/验收用：AURASCOPE_UPDATE_JSON 可指向本地或自建的 release JSON，
        # 复现「发现新版本 → 下载并更新」全链路，不必真的发版。
        url = os.environ.get('AURASCOPE_UPDATE_JSON') or LATEST_RELEASE_URL
        if os.environ.get('AURASCOPE_UPDATE_JSON'):
            logging.getLogger('Aurascope').info('使用自定义更新源：%s', url)
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader,
                          'Aurascope-Updater')
        request.setTransferTimeout(8000)
        reply = self._manager.get(request)
        reply.finished.connect(lambda: self._on_finished(reply, current, manual))

    def _on_finished(self, reply, current, manual=False):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                logging.getLogger('Aurascope').warning(
                    '检查更新失败：%s', reply.errorString())
                if manual:
                    self.check_finished.emit(None, reply.errorString())
                return
            payload = json.loads(bytes(reply.readAll()).decode('utf-8'))
            info = parse_latest_release(payload)
            if info and release_is_newer(info['tag'], current):
                logging.getLogger('Aurascope').info(
                    '发现新版本 %s', info.get('tag'))
                self.update_found.emit(info)
            elif manual:
                self.check_finished.emit(None, '')
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logging.getLogger('Aurascope').warning('检查更新解析失败：%s', exc)
            if manual:
                self.check_finished.emit(None, f'返回数据无法解析（{exc}）')
        finally:
            reply.deleteLater()
