---
kind: dependency_management
name: 依赖管理 — requirements.txt + PyInstaller 打包
category: dependency_management
scope:
    - '**'
source_files:
    - requirements.txt
    - main.spec
    - AurascopeV6.spec
    - .gitignore
---

## 1. 使用的系统/方法

仓库采用最简的 Python 依赖管理模式：
- 通过 `requirements.txt` 声明运行时依赖，使用 `>=` 宽松版本约束。
- 通过 PyInstaller（`.spec` 文件）将应用打包为 Windows 可执行文件。
- 没有使用虚拟环境清单（如 `pip freeze` 输出）、lockfile（`requirements.lock` / `poetry.lock` / `Pipfile.lock`）、私有源或 vendored 第三方库。

## 2. 关键文件

- `requirements.txt`：唯一依赖声明入口，列出 PyQt6、opencv-python、numpy、pandas、tifffile 五个包。
- `main.spec`：PyInstaller 构建脚本，入口指向旧版 `AuscopeV5.py`，排除 `PySide6`、`PySide2`，启用 UPX 压缩，图标 `logo_1.ico`。
- `AurascopeV6.spec`：当前 V6 构建脚本，入口 `main.py`，通过 `datas` 内嵌 `说明书.md`、`CHANGELOG.md`、`logo_1.ico`、`logo.png`、`logo_innolight.png`，并通过 `version_info.txt` 注入 Windows 文件版本信息。
- `.gitignore`：忽略 `dist/*.exe`、`build/*/*.pkg`、`__pycache__/`、`*.pyc`，表明 `dist/` 与 `build/` 是 PyInstaller 产物目录。

## 3. 架构与约定

- **依赖声明**：所有第三方包集中在根目录 `requirements.txt`，无子模块级依赖文件。
- **版本策略**：全部使用 `>=` 下限约束（例如 `PyQt6>=6.4.0`、`opencv-python>=4.8.0`、`numpy>=1.24.0`、`pandas>=1.5.0`、`tifffile>=2023.7.8`），不锁定上限，也不固定精确版本。
- **打包方式**：PyInstaller 以 spec 文件驱动；V6 分支使用 `AurascopeV6.spec`，V5 遗留使用 `main.spec`。两个 spec 都显式 `excludes=['PySide6', 'PySide2']`，避免与 PyQt6 冲突。
- **资源内嵌**：V6 spec 通过 `datas=[...]` 把说明文档和 logo 打入 exe，而非运行时从源码路径读取。
- **版本元数据**：Windows 可执行文件的版本信息来自根目录 `version_info.txt`，由 spec 的 `version='version_info.txt'` 参数引用。
- **压缩**：两个 spec 均设置 `upx=True`，默认启用 UPX 压缩可执行体。

## 4. 约定与约束

- 新增第三方依赖时，应在根目录 `requirements.txt` 中以 `>=` 形式追加一行（依据现有文件的统一写法）。
- 发布新的桌面安装包时，应维护对应的 PyInstaller spec 文件，并在 `datas` 中同步加入需要随 exe 分发的静态资源（参考 `AurascopeV6.spec`）。
- 不应引入 `PySide6` 或 `PySide2`，因为 spec 已显式排除它们（`excludes=['PySide6', 'PySide2']`）。
- 构建产物位于 `dist/` 与 `build/`，这些目录被 `.gitignore` 忽略，不会提交到仓库。
- 仓库未配置任何私有 PyPI 源、代理或认证信息，也未使用 pipenv/poetry/hatch 等现代工具链；依赖安装应通过 `pip install -r requirements.txt` 完成。