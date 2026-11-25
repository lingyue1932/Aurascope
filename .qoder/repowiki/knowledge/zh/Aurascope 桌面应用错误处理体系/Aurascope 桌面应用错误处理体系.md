---
kind: error_handling
name: Aurascope 桌面应用错误处理体系
category: error_handling
scope:
    - '**'
source_files:
    - logging_setup.py
    - ui_dialogs.py
    - area_tab.py
    - canvas.py
    - image.py
    - main_window.py
---

## 1. 总体策略

Aurascope 采用「业务层抛出具体异常 + 调用方捕获并转为 UI 反馈 + 全局未捕获异常兜底」的分层模式，没有自定义异常类、错误码或中间件。核心思路是：
- 算法/IO 层通过 `raise ValueError(...)` 表达参数非法；
- UI 层（area_tab、main_window 等）用 `try/except` 捕获后写日志、更新状态栏 `_status(..., error=True)` 或弹出统一消息框；
- 主线程与子线程的未捕获异常由 `logging_setup.install_excepthook()` 接管，写入滚动日志并弹出带「复制详情 / 打开日志」按钮的错误对话框。

仓库中未发现 `QMessageBox.critical/warning/information` 的直接使用——所有用户可见提示均走 `ui_dialogs.py` 中的 `show_toast`、`show_message`（及其 `show_info/show_warning/show_error` 包装），以及 area_tab 自有的 `_status` 方法。

## 2. 关键文件与职责

| 文件 | 错误处理职责 |
|---|---|
| `logging_setup.py` | 初始化 RotatingFileHandler（`aurascope.log`，单文件 1MB × 5 份）、安装 `sys.excepthook` 与 `threading.excepthook`，提供 `_report_exception` 与 `_show_error_dialog` |
| `ui_dialogs.py` | 统一 Toast（底部 QLabel，默认 1800ms 自动消失）与 `show_message`（info/warning/error 三态，error 级附带「打开日志」按钮） |
| `area_tab.py` | 图片加载、CSV 导出、ROI 检测的主捕获点，将 `OSError/ValueError/cv2.error/zlib.error/ImportError` 转为日志 + 状态栏错误 |
| `canvas.py` | 画布内部交互（鼠标事件、撤销栈、资源加载）中使用宽泛 `except Exception: pass` 做防御性静默 |
| `image.py` | 算法入口函数对入参做严格校验，抛 `ValueError`；可选 GUI 依赖通过顶层 try/except 降级 |
| `main_window.py` | TIF 读取回退（tifffile → cv2.imdecode）、标定失败等场景直接 `print` 或 `show_warning` |

## 3. 架构与约定

### 3.1 全局异常兜底（logging_setup）

`install_excepthook()` 同时替换 `sys.excepthook` 与 `threading.excepthook`：
- 主线程未捕获异常：`_report_exception` 用 `traceback.format_exception` 生成完整堆栈，以 `Aurascope` logger 的 `critical` 级别写入日志，再调用 `_show_error_dialog`。
- 工作线程未捕获异常：context 标记为 `线程 {name} 未捕获异常`，同样落盘但不弹 GUI 对话框（因为无 active window）。
- `KeyboardInterrupt` 被显式忽略，不弹窗。

`_show_error_dialog` 内部再次 `try/except Exception` 包裹 PyQt6 导入与 `QMessageBox.exec`，确保「错误对话框显示失败」本身不会二次崩溃——失败时仅记录 `exception('错误对话框显示失败')`。

### 3.2 业务层异常分类与捕获

**参数校验（image.py）**：在 `detect_voids` 等函数入口处集中抛 `ValueError`，例如：
```
raise ValueError('gray 必须是非空二维 uint8 数组')
raise ValueError('thresh_val 必须是 [0, 255] 内的有限实数')
raise ValueError('roi_mask 必须是与 gray 同形且仅含 0/255 的 uint8 数组')
```
这些不是运行时崩溃，而是「参数契约违反」，由调用方按语义区分对待。

**IO 与第三方库异常（area_tab.py）**：
- 图片加载：`except (OSError, ValueError, cv2.error, zlib.error, ImportError) as exc` → 写 warning 日志 + `_status(..., error=True)` + 返回 `False`。
- ROI 检测：`except (ValueError, cv2.error) as exc` → 将该 ROI 标记为 `status='error'`、清空对象列表，继续处理其他 ROI，不影响整体批处理。
- CSV 导出：`except OSError` → 临时文件清理后返回 `False`。

**画布层防御性捕获（canvas.py）**：多处 `except Exception:` 直接 `pass`，用于容忍 Qt 事件回调中不可预期的异常（如鼠标坐标越界、样式属性缺失），保证画布渲染不因单次交互崩溃。

### 3.3 UI 反馈通道

| 通道 | 使用场景 | 实现位置 |
|---|---|---|
| `_status(text, error=True)` | area_tab 内短消息，红色表示失败 | `area_tab.py` |
| `show_toast(parent, text)` | 成功/简短反馈，底部居中，自动过期 | `ui_dialogs.py` |
| `show_message/show_error/show_warning` | 需要用户确认的消息框，error 级附带「打开日志」 | `ui_dialogs.py` |
| `QMessageBox` 直接调用 | main_window 中标定失败等少数场景 | `main_window.py` |

### 3.4 可选 GUI 依赖降级

`image.py` 顶部：
```python
try:
    from PyQt6.QtWidgets import QApplication
except Exception:
    QApplication = None
```
`_pump_events()` 在无 GUI 环境下成为空操作，使算法模块可被外部报告工具独立调用而不强依赖 PyQt6。

## 4. 观察到的约定与约束

- **业务异常类型**：目前仅使用 Python 内置 `ValueError` 表达参数非法；未见自定义异常类、错误码枚举或 `Exception` 基类继承体系。
- **日志框架**：统一通过 `logging.getLogger('Aurascope')` 访问，级别包括 `info`（正常路径）、`warning`（可恢复错误）、`critical`（未捕获异常）。日志文件位于 `app_paths.log_dir()/aurascope.log`，使用 `RotatingFileHandler(maxBytes=1_000_000, backupCount=5, encoding='utf-8')`。
- **GUI 安全**：所有可能触发 UI 的代码（`QMessageBox`、`QApplication.clipboard`、`QDesktopServices.openUrl`）都包裹在 `try/except Exception` 中，避免错误提示本身引发二次崩溃。
- **线程异常**：通过 `threading.excepthook` 捕获，但仅写日志，不弹窗——这是有意为之，因为工作线程通常没有 active window。
- **未覆盖区域**：`main_window.py` 中仍有裸 `print(f"tifffile 读取失败: {e}")`（L807）和裸 `except:`（L891-893），未走统一日志/消息通道；`canvas.py` 中大量 `except Exception: pass` 属于静默吞异常，不利于问题定位。
- **测试侧**：`test_area_tab.py` 通过 `raise cv2.error('synthetic ROI failure')` 模拟 OpenCV 异常，验证 area_tab 的错误分支。

## 5. 总结

该仓库的错误处理是「轻量实用型」：没有统一的错误类型系统，主要靠 `ValueError` + 调用方 `try/except` + 全局 `excepthook` 兜底。设计上的取舍是优先保证 GUI 不崩溃（广泛 `except Exception: pass`），并通过滚动日志与「复制详情/打开日志」按钮把诊断信息交给用户。未来若需增强，建议收敛到 `ui_dialogs.show_*` 与 `logging.getLogger('Aurascope')`，并逐步替换 `canvas.py` 中的静默捕获。