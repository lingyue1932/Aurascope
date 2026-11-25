"""应用内自更新：下载发布包 → 应用内预复制到 staging → 退出后毫秒级交换。

为什么要「应用内复制 + 退出后改名」两段式（而不是退出后 robocopy）：
Windows 下运行中的 exe 与 ``_internal/*.dll`` 被锁定，只能等进程退出再替换；
如果替换时才开始复制 240MB（叠加杀软扫描可到十几秒），用户会看到长时间的
无反馈黑屏。改为先在应用内把新文件复制到 ``<安装目录>_new``（带进度条），
退出后脚本只做 3 次目录/文件改名（毫秒级），空窗期从数秒压到 1~2 秒。

全程只写 ``%LOCALAPPDATA%`` 与程序自身目录，不需要管理员权限。
交换用目录改名 + 失败回滚，不会删除安装目录里用户自己的数据（如 ``recipes/``）。
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import zipfile

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from app_paths import local_data_dir
from app_version import APP_VERSION

logger = logging.getLogger('Aurascope')

SWAP_SCRIPT = 'swap_update.cmd'
SWAP_LOG = 'apply.log'
PENDING_NOTICE = 'pending.json'

# 交给退出后运行的交换脚本：只做改名，不复制。
# %1=旧进程 PID %2=staging 目录 %3=安装目录 %4=exe 文件名 %5=日志
_SWAP_TEMPLATE = '''@echo off
setlocal
set "PID=%~1"
set "STAGE=%~2"
set "INSTALL=%~3"
set "EXE=%~4"
set "LOG=%~5"
set "TRIES=0"
echo [%DATE% %TIME%] swap start, waiting pid %PID% >> "%LOG%"
:wait
tasklist /FI "PID eq %PID%" 2>nul | findstr /C:"%PID%" >nul
if errorlevel 1 goto swap
set /a TRIES+=1
if %TRIES% GEQ 100 goto rollback
ping -n 2 127.0.0.1 >nul
goto wait

:swap
if not exist "%STAGE%\\_internal" goto rollback
move "%INSTALL%\\_internal" "%INSTALL%\\_internal_old" >> "%LOG%" 2>&1
if errorlevel 1 goto rollback
move "%STAGE%\\_internal" "%INSTALL%\\_internal" >> "%LOG%" 2>&1
if errorlevel 1 goto restore
move /Y "%STAGE%\\%EXE%" "%INSTALL%\\%EXE%" >> "%LOG%" 2>&1
if errorlevel 1 goto restore
echo [%DATE% %TIME%] swap ok >> "%LOG%"
start "" "%INSTALL%\\%EXE%"
ping -n 4 127.0.0.1 >nul
rmdir /s /q "%INSTALL%\\_internal_old" >> "%LOG%" 2>&1
rmdir /s /q "%STAGE%" >> "%LOG%" 2>&1
exit /b

:restore
echo [%DATE% %TIME%] swap failed, restoring old files >> "%LOG%"
if exist "%INSTALL%\\_internal" move "%INSTALL%\\_internal" "%INSTALL%\\_internal_new_failed" >> "%LOG%" 2>&1
if exist "%INSTALL%\\_internal_old" move "%INSTALL%\\_internal_old" "%INSTALL%\\_internal" >> "%LOG%" 2>&1
rmdir /s /q "%INSTALL%\\_internal_new_failed" >> "%LOG%" 2>&1
goto rollback

:rollback
echo [%DATE% %TIME%] update aborted, starting installed version >> "%LOG%"
start "" "%INSTALL%\\%EXE%"
exit /b
'''

# 只能用 CREATE_NO_WINDOW：加 DETACHED_PROCESS 后脚本里的
# tasklist | findstr 会一直判定进程仍在（实测挂死），且会闪出控制台窗口
_NO_WINDOW = 0x08000000


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


def staging_dir(install_dir):
    """staging 必须与安装目录同级（同一磁盘），改名才能瞬间完成。"""
    return os.path.normpath(install_dir) + '_new'


def tree_size(root):
    total = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    return total


def stage_files(source_dir, staging, progress=None, cancelled=None):
    """把新版本文件复制到 staging 目录，返回复制的字节数。

    progress(已复制字节, 总字节) 用于驱动进度条；cancelled() 返回真时中止，
    调用方负责清理 staging 目录（安装目录此时完全没被改动）。
    """
    total = tree_size(source_dir)
    copied = 0
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    for folder, _dirs, files in os.walk(source_dir):
        rel = os.path.relpath(folder, source_dir)
        target = staging if rel == '.' else os.path.join(staging, rel)
        os.makedirs(target, exist_ok=True)
        for name in files:
            if cancelled is not None and cancelled():
                return -1
            src = os.path.join(folder, name)
            dst = os.path.join(target, name)
            shutil.copy2(src, dst)
            try:
                copied += os.path.getsize(src)
            except OSError:
                pass
            if progress is not None:
                progress(copied, total)
    if progress is not None:
        progress(total, total)
    return copied


def write_swap_script():
    """写出交换脚本（ASCII 内容，避免 cmd 编码问题）。"""
    script = os.path.join(updates_root(), SWAP_SCRIPT)
    with open(script, 'w', encoding='ascii', newline='\r\n') as stream:
        stream.write(_SWAP_TEMPLATE)
    return script


def write_update_notice(version):
    """记下“即将更新到某版本”，新版本启动时消费，用于提示更新成功。"""
    path = os.path.join(updates_root(), PENDING_NOTICE)
    try:
        with open(path, 'w', encoding='utf-8') as stream:
            json.dump({'target': str(version or '')}, stream)
    except OSError:
        logger.warning('写入更新提示标记失败', exc_info=True)


def consume_update_notice():
    """新版本启动时调用：版本号对得上才返回 True，并删除标记。"""
    path = os.path.join(updates_root(), PENDING_NOTICE)
    if not os.path.isfile(path):
        return False
    target = ''
    try:
        with open(path, encoding='utf-8') as stream:
            target = str((json.load(stream) or {}).get('target') or '')
    except (OSError, ValueError):
        target = ''
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return target == APP_VERSION


def launch_swap(staging, install_dir, exe_name, pid=None):
    """启动交换脚本并立刻返回；调用方随后应关闭应用。"""
    script = write_swap_script()
    log = os.path.join(updates_root(), SWAP_LOG)
    subprocess.Popen(
        ['cmd', '/c', script, str(pid or os.getpid()), staging,
         install_dir, exe_name, log],
        creationflags=_NO_WINDOW, close_fds=True)
    logger.info('已启动更新交换脚本：%s → %s', staging, install_dir)
    return script


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


def can_self_update():
    """源码运行没有可替换的打包目录，只能走浏览器下载。"""
    return bool(getattr(sys, 'frozen', False))
