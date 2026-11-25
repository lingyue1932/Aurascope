---
kind: build_system
name: PyInstaller 打包与 Windows 桌面应用构建
category: build_system
scope:
    - '**'
source_files:
    - AurascopeV6.spec
    - version_info.txt
    - requirements.txt
    - update_check.py
---

## 1. 构建系统概览

本项目是纯 Python PyQt6 桌面应用，没有 Makefile、Dockerfile、CI 流水线或 `setup.py`/`pyproject.toml`。构建完全依赖 **PyInstaller**（通过 `.spec` 文件）在 Windows 上把 `main.py` 打包为单可执行文件，并使用 `version_info.txt` 注入 Windows 版本资源。

- 运行时依赖由 `requirements.txt` 声明：`PyQt6>=6.4.0`、`opencv-python>=4.8.0`、`numpy>=1.24.0`、`pandas>=1.5.0`、`tifffile>=2023.7.8`。
- 打包产物名为 `AurascopeV6.3.exe`，版本号与 `version_info.txt` 中的 `VSVersionInfo` 保持一致（当前 `6.3.0`）。
- 仓库未包含 CI 配置；更新检查逻辑通过 GitHub Releases API 在线查询最新版本，但发布流程本身未在仓库中自动化。

## 2. 关键文件

- `AurascopeV6.spec` — PyInstaller 主 spec，定义入口、数据文件、EXE 名称、图标与版本资源。
- `version_info.txt` — Windows 二进制版本元数据（`VSVersionInfo`），含公司名、产品名、文件/产品版本、版权及原始文件名。
- `requirements.txt` — 运行时依赖清单。
- `update_check.py` — 运行时从 `https://api.github.com/repos/{REPO}/releases/latest` 拉取最新 release 做版本对比。

## 3. 架构与约定

### 3.1 PyInstaller 打包结构 (`AurascopeV6.spec`)

```python
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
    excludes=['PySide6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
```

- 入口脚本固定为 `main.py`。
- 通过 `datas=` 将 `说明书.md`、`CHANGELOG.md`、`logo_1.ico`、`logo.png`、`logo_innolight.png` 作为附加资源打入包内（相对路径 `'.'` 表示与 EXE 同目录）。
- 显式 `excludes=['PySide6', 'PySide2']` 以排除 Qt 的另一个实现，避免与 `PyQt6` 冲突。
- `hiddenimports=[]`、`hookspath=[]`、`runtime_hooks=[]` 保持默认，无自定义 Hook。
- `optimize=0`（不优化字节码）、`noarchive=False`（保留 PYZ 归档）便于调试。

EXE 构建段：

```python
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='AurascopeV6.3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['logo_1.ico'],
)
```

- 输出文件名硬编码为 `AurascopeV6.3`，与 `version_info.txt` 中 `OriginalFilename: AurascopeV6.3.exe` 一致。
- `upx=True` 启用 UPX 压缩；`strip=False` 保留符号表以便调试。
- `console=False` 生成 GUI 窗口模式（无控制台）。
- `icon=['logo_1.ico']` 设置 EXE 图标。
- `version='version_info.txt'` 将 Windows 版本资源注入到可执行文件中。

### 3.2 版本管理策略

版本号在两个地方同步维护：

1. `version_info.txt` 中的 `VSVersionInfo` → `filevers=(6, 3, 0, 0)`、`prodvers=(6, 3, 0, 0)`、`StringFileInfo` 中的 `FileVersion` / `ProductVersion` 均为 `6.3.0`。
2. `AurascopeV6.spec` 中 EXE 的 `name='AurascopeV6.3'`。

两者需手动保持一致，仓库中没有自动校验脚本。

### 3.3 运行时更新检查

`update_check.py` 通过 GitHub Releases API 获取最新版本并比较，用于提示用户下载新发行版。该逻辑仅用于运行时行为，不参与构建过程。

## 4. 约定与约束

- **构建工具唯一性**：仓库仅使用 PyInstaller + `.spec` 文件进行打包，未见 Makefile、shell 构建脚本、Dockerfile、GitHub Actions 或其他 CI 配置。
- **平台限定**：`version_info.txt` 使用 Windows 专属的 `VSVersionInfo` 格式，且 EXE 名称带 `.exe` 后缀，表明构建目标仅为 Windows。
- **依赖锁定方式**：仅通过 `requirements.txt` 的宽松版本范围（`>=`）声明依赖，未使用 `pip freeze` 生成的锁文件或 Poetry/Pipenv 等现代依赖管理器。
- **打包资源清单**：所有需要随 EXE 分发的文本与图片资源必须显式添加到 `AurascopeV6.spec` 的 `datas=` 列表中，否则打包后不可用。
- **Qt 实现互斥**：通过 `excludes=['PySide6', 'PySide2']` 强制排除 PySide 系列，确保只打包 PyQt6。
- **UPX 压缩**：默认启用 `upx=True`，若后续引入受 UPX 保护的第三方库，需在 `upx_exclude` 中添加对应模块。
- **无跨平台构建**：未发现任何针对 macOS/Linux 的 spec 或 Docker 配置，也未见交叉编译脚本。

## 5. 已知缺失

- 无自动化构建脚本（如 `build.bat` / `build.sh`），开发者需直接调用 `pyinstaller AurascopeV6.spec`。
- 无 CI 流水线，发布版本需人工修改 `version_info.txt` 与 `AurascopeV6.spec` 中的版本号并保持同步。
- 无单元测试的构建集成（`pytest` 未被纳入构建流程）。