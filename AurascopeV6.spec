# -*- mode: python ; coding: utf-8 -*-
"""Aurascope 打包配置（onedir + 无 UPX + bootloader 启动图）。

为什么不用单文件：单文件每次双击都要把 ~100MB 内容解包到 %TEMP%\_MEIxxxx，
实测从双击到 main() 写日志要 11.5s；onedir 直接读安装目录，同一台机器降到 0.7s。
UPX 一并不用：它对启动只有副作用，还容易被杀软误报。

启动图用 PyInstaller 的 Splash（bootloader 直接显示，双击后 0.1s 就出来）：
Qt 自绘启动图必须等 QApplication 起来，而 DLL 加载 + 杀软扫描那 2~3 秒是空白。
"""


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('说明书.md', '.'),
           ('CHANGELOG.md', '.'),
           ('logo_1.ico', '.'),
           ('logo.png', '.'),
           ('logo_innolight.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pandas 已由 csv_export 取代；matplotlib 从未使用，一并排除
    excludes=['PySide6', 'PySide2', 'pandas', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

splash = Splash('splash_boot.png', a.binaries, a.datas)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    [],
    name='AurascopeV6.3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    exclude_binaries=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['logo_1.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AurascopeV6.3',
)
