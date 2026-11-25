---
kind: logging_system
name: 日志系统：统一滚动文件、全局异常兜底与 Aurascope 命名空间
category: logging_system
scope:
    - '**'
source_files:
    - logging_setup.py
    - main.py
---

## 1. 使用的系统与方案

Aurascope 使用 Python 标准库 `logging`，没有引入第三方日志框架。核心由 `logging_setup.py` 提供：
- 根 logger（`logging.getLogger()`）设置级别为 `INFO`。
- 通过 `logging.handlers.RotatingFileHandler` 输出到单文件 `aurascope.log`，按大小轮转：单文件最大 1MB，保留最近 5 个备份（`maxBytes=1_000_000, backupCount=5`），编码 `utf-8`。
- 所有业务模块统一通过命名空间 `Aurascope` 获取 logger：`logging.getLogger('Aurascope')`。
- 格式器固定为 `'%(asctime)s %(levelname)s [%(name)s] %(message)s'`，无结构化字段（JSON/traceId 等）。
- 同时安装主线程 `sys.excepthook` 与工作线程 `threading.excepthook`，把未捕获异常以 `critical` 级别写入日志并弹出 Qt 错误对话框。

## 2. 关键文件

- `logging_setup.py` — 日志初始化、轮转 handler、`log_file()`、全局异常钩子。
- `main.py` — 启动时调用 `setup_logging()` → `install_excepthook()` → 记录启动信息，再创建 `QApplication`。
- `app_paths.py` — 提供 `log_dir()`，决定日志落盘目录（源码模式 vs frozen 打包模式路径不同）。
- 消费方（仅用 `Aurascope` 命名空间）：`area_tab.py`、`main_window.py`、`ui_dialogs.py`、`update_check.py`。

## 3. 架构与约定

### 3.1 启动装配顺序
`main.py::main()` 的调用顺序是固定的：
1. `setup_logging()` 计算 `_LOG_FILE = os.path.join(log_dir(), 'aurascope.log')`，注册 RotatingFileHandler，返回日志路径。
2. `install_excepthook()` 替换 `sys.excepthook` 与 `threading.excepthook`。
3. 记录 `info('启动 Aurascope %s（frozen=%s）日志：%s', APP_VERSION, ...)`。
4. 设置 Qt HighDPI 策略后创建 `QApplication`。

### 3.2 防重复安装
`setup_logging()` 通过检查 root handlers 中是否已存在带 `_aurascope=True` 标记的 `RotatingFileHandler` 来避免重复注册：
```python
installed = any(
    isinstance(h, RotatingFileHandler) and getattr(h, '_aurascope', False)
    for h in root.handlers)
```
因此多次调用 `setup_logging()` 是幂等的。

### 3.3 全局异常兜底
`install_excepthook()` 覆盖两个位置：
- 主线程：`sys.excepthook`，跳过 `KeyboardInterrupt`，其余异常经 `_report_exception` 写 `critical` 日志并弹出 `QMessageBox`。
- 工作线程：`threading.excepthook`，在上下文中标注线程名（`f'线程 {getattr(args.thread, "name", "?")} 未捕获异常'`）。

错误对话框 `_show_error_dialog` 做了三层降级：
- 如果 `QApplication.instance() is None`（无 GUI 场景），直接返回不弹框。
- 用户可选择「复制详情」或「打开日志」（调用 `QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir()))`）。
- 如果弹框本身失败，回退到 `logging.getLogger('Aurascope').exception('错误对话框显示失败')`。

### 3.4 命名空间与级别约定
- 所有业务 logger 统一使用 `logging.getLogger('Aurascope')`，而非 `__name__`。
- 正常流程用 `info`；可恢复问题用 `warning`；不可恢复/崩溃用 `critical`；异常堆栈用 `exception`。
- 当前仓库内未发现 `debug` 级别的使用，根 logger 也固定在 `INFO`，因此 debug 消息不会输出。

### 3.5 日志落盘位置
日志文件名固定为 `aurascope.log`，目录来自 `app_paths.log_dir()`。`log_file()` 提供读取入口，既可用于弹窗中的“打开日志”按钮，也可供外部工具定位日志。

## 4. 约定与约束

- **必须**通过 `logging_setup.setup_logging()` 初始化日志，再由各模块通过 `logging.getLogger('Aurascope')` 获取 logger（由 `main.py` 启动顺序保证）。
- **禁止**直接实例化 `RotatingFileHandler` 或修改 root logger 的 handler 列表；已有 `_aurascope` 标记用于识别本应用注册的 handler。
- **禁止**使用其他 logger 命名空间——现有消费方全部使用 `Aurascope`，新增模块应保持一致。
- **约定**日志格式固定为 `asctime + levelname + name + message`，不包含时间戳以外的结构化字段；如需扩展字段需先改 formatter。
- **约定**未捕获异常一律走 `install_excepthook()` 提供的钩子，不要在各模块自行 try/except 后裸抛。
- **约束**根 logger 级别硬编码为 `INFO`，无法通过环境变量或配置开关调整（当前实现）。