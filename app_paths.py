"""应用运行路径与构建信息（兼容 PyInstaller 单文件模式）。"""

import os
import sys
from datetime import datetime


def resource_path(name):
    """随 exe 打包的资源路径（onefile 解包目录或源码目录）。"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def app_dir():
    """程序所在目录：打包后取 exe 同级，源码运行取本文件目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def local_data_dir():
    """当前用户可写数据目录（无需管理员权限）。"""
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser(r'~\AppData\Local')
    path = os.path.join(base, 'Aurascope')
    os.makedirs(path, exist_ok=True)
    return path


def log_dir():
    path = os.path.join(local_data_dir(), 'logs')
    os.makedirs(path, exist_ok=True)
    return path


def build_date():
    """构建日期：打包后取 exe 修改时间，源码运行取本文件时间。"""
    target = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
    try:
        return datetime.fromtimestamp(os.path.getmtime(target)).strftime('%Y-%m-%d')
    except OSError:
        return '—'
