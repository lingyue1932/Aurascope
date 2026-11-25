"""应用内自更新：下载发布包 → 解压到用户目录 → 退出后替换并重启。

Windows 下运行中的 exe 与 ``_internal/*.dll`` 被锁定，进程内无法替换自身，
因此生成一个 .cmd 脚本：它等待本进程 PID 退出后再 robocopy 覆盖安装目录，
最后启动新版本。全程只写 ``%LOCALAPPDATA%`` 与程序自身目录，不需要管理员权限。

替换时使用 robocopy（不带 /MIR），因此不会删除安装目录里用户自己的数据
（如 ``recipes/`` 里的示教配方）。
"""

import logging
import os
import shutil
import subprocess
import sys
import zipfile

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from app_paths import local_data_dir

logger = logging.getLogger('Aurascope')

APPLY_SCRIPT = 'apply_update.cmd'
APPLY_LOG = 'apply.log'

# 等待进程退出 → 覆盖文件 → 启动新版本。
# %1=PID %2=新版本目录 %3=安装目录 %4=exe 文件名 %5=日志文件
_APPLY_TEMPLATE = '''@echo off
setlocal
set "PID=%~1"
set "SRC=%~2"
set "DST=%~3"
set "EXE=%~4"
set "LOG=%~5"
echo [%DATE% %TIME%] waiting for pid %PID% >> "%LOG%"
:wait
tasklist /FI "PID eq %PID%" 2>nul | findstr /C:"%PID%" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)
echo [%DATE% %TIME%] copying "%SRC%" -^> "%DST%" >> "%LOG%"
robocopy "%SRC%" "%DST%" /E /IS /IT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1
if errorlevel 8 (
  echo [%DATE% %TIME%] robocopy failed, running from updates cache >> "%LOG%"
  start "" "%SRC%\\%EXE%"
) else (
  echo [%DATE% %TIME%] update applied >> "%LOG%"
  start "" "%DST%\\%EXE%"
)
endlocal
'''

# CREATE_NO_WINDOW | DETACHED_PROCESS：脚本不弹黑框，也不随父进程退出而结束
_NO_WINDOW = 0x08000000
_DETACHED = 0x00000008


def updates_root():
    """更新缓存目录（用户可写，无需管理员权限）。"""
    root = os.path.join(local_data_dir(), 'updates')
    os.makedirs(root, exist_ok=True)
    return root


def prepare_target_dir(version):
    """每个版本用一个独立目录，清掉上一次可能残留的包。"""
    target = os.path.join(updates_root(), f'v{version or "unknown"}')
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)
    return target


def find_main_exe(root):
    """在解压结果里找主程序 exe（取目录层级最浅的 Aurascope*.exe）。"""
    found = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.lower().endswith('.exe') and name.lower().startswith('aurascope'):
                depth = folder[len(root):].count(os.sep)
                found.append((depth, os.path.join(folder, name)))
    if not found:
        return None
    found.sort()
    return found[0][1]


class UpdateDownloader(QObject):
    """下载发布包并解压，完成后给出新版本 exe 的绝对路径。"""

    progress = pyqtSignal(int, int)   # 已接收字节, 总字节（未知时为 0）
    ready = pyqtSignal(str)           # 解压后的新版本 exe 路径
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._chunks = []
        self._version = ''

    def start(self, url, version):
        self._version = str(version or '')
        self._chunks = []
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader,
                          'Aurascope-Updater')
        request.setTransferTimeout(60000)
        self._reply = self._manager.get(request)
        # downloadProgress 是 qint64，直接连 int 信号会因类型不匹配失败
        self._reply.downloadProgress.connect(
            lambda received, total: self.progress.emit(int(received), int(total)))
        self._reply.readyRead.connect(self._on_ready_read)
        self._reply.finished.connect(self._on_finished)

    def cancel(self):
        if self._reply is not None:
            self._reply.abort()

    def _on_ready_read(self):
        if self._reply is not None:
            self._chunks.append(bytes(self._reply.readAll()))

    def _on_finished(self):
        reply, self._reply = self._reply, None
        if reply is None:
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.failed.emit(reply.errorString() or '下载已取消')
                return
            data = b''.join(self._chunks)
            self._chunks = []
            if not data:
                self.failed.emit('下载内容为空')
                return
            target = prepare_target_dir(self._version)
            archive = os.path.join(target, 'package.zip')
            with open(archive, 'wb') as stream:
                stream.write(data)
            extract_dir = os.path.join(target, 'extracted')
            with zipfile.ZipFile(archive) as package:
                package.extractall(extract_dir)
            exe = find_main_exe(extract_dir)
            if exe is None:
                self.failed.emit('更新包里没有找到 Aurascope 主程序')
                return
            logger.info('更新包已就绪：%s', exe)
            self.ready.emit(exe)
        except Exception as exc:                      # 下载/解压任何一步失败都要能回退
            logger.exception('更新包处理失败')
            self.failed.emit(f'更新包处理失败：{exc}')
        finally:
            reply.deleteLater()


def write_apply_script():
    """写出替换脚本（ASCII 内容，避免 cmd 编码问题）。"""
    script = os.path.join(updates_root(), APPLY_SCRIPT)
    with open(script, 'w', encoding='ascii', newline='\r\n') as stream:
        stream.write(_APPLY_TEMPLATE)
    return script


def launch_apply(source_dir, target_dir, exe_name, pid=None):
    """启动替换脚本并立刻返回；调用方随后应关闭应用。"""
    script = write_apply_script()
    log = os.path.join(updates_root(), APPLY_LOG)
    subprocess.Popen(
        ['cmd', '/c', script, str(pid or os.getpid()), source_dir,
         target_dir, exe_name, log],
        creationflags=_NO_WINDOW | _DETACHED, close_fds=True)
    logger.info('已启动更新脚本：%s → %s', source_dir, target_dir)
    return script


def can_self_update():
    """源码运行没有可替换的打包目录，只能走浏览器下载。"""
    return bool(getattr(sys, 'frozen', False))
