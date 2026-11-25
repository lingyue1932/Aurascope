# Aurascope

微电子封装产线半自动化视觉检测与数据分析桌面工具。

---

## 功能模块

| 模块 | 功能 |
|------|------|
| **空洞分析** | 金锡焊料 X 光 / SEM 图空洞率检测，支持阈值二值化、局部阈值笔刷、Canny 边缘验证、圆度过滤 |
| **距离测量** | 标定像素比后两点测距，支持批量测量与统计 |
| **剪切力计算** | 按 MIL-STD-883H Method 2019.9 标准计算芯片剪切力要求值 |
| **物料计数** | 蓝膜 LD / Submount 离散物料自动计数，支持框选区域、手动增删 |

## 快速开始

### 环境要求

- Python 3.10+
- Windows 7+

### 安装

```bash
pip install -r requirements.txt
```

### 运行

```bash
python main.py
```

## 技术栈

- **PyQt6** — 桌面 GUI 框架
- **OpenCV** — 图像处理
- **NumPy** — 数值计算
- **csv（标准库）** — CSV 导出

## 项目结构

```
├── main.py              # 主入口
├── app_paths.py         # 资源 / 用户数据 / 日志路径
├── main_window.py       # 主窗口装配
├── area_tab.py          # 缺陷面积 Tab
├── area_canvas.py       # 缺陷面积画布
├── canvas.py            # 空洞分析画布
├── image.py             # 图像处理算法
├── recipe.py            # 检测配方 JSON 读写
├── quick_teach_dialog.py # 快速示教弹窗
├── teach_batch_tab.py   # 示教 / 批量检测 Tab
├── measure_tab.py       # 距离测量 Tab
├── measure_canvas.py    # 距离测量画布
├── stitching_tab.py     # 图像拼接 Tab
├── stitching_canvas.py  # 图像拼接画布
├── shear_tab.py         # 剪切力计算 Tab
├── counting_tab.py      # 物料计数 Tab
├── counting_canvas.py   # 物料计数画布
├── styles.py            # 全局样式表
├── ui_components.py     # UI 组件工厂函数
└── AurascopeV6.spec     # PyInstaller 打包配置
```

## 打包

```bash
pip install pyinstaller
pyinstaller AurascopeV6.spec
```

产物是 `dist/Aurascope/` 文件夹，双击其中的 `Aurascope.exe` 运行（exe 名字固定不带版本号，升级后桌面快捷方式不会失效）。

> 不要改回单文件（`--onefile`）：单文件每次启动都要把 ~100MB 解包到 `%TEMP%`，实测冷启动到主窗口 11.5s；onedir 为 0.7s。需要“单文件”外观就用安装包工具把该文件夹包起来。

## License

MIT