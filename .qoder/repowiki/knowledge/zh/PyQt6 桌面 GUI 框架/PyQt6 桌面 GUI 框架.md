---
kind: external_dependency
name: PyQt6 桌面 GUI 框架
slug: pyqt6
category: external_dependency
category_hints:
    - framework_behavior
scope:
    - '**'
---

### Aurascope 的桌面 UI 框架
- 作为 PyQt6 应用，主窗口通过 QTabWidget 组织空洞分析、距离测量、剪切力计算、物料计数等 Tab 页面。
- Canvas 层基于 QWidget + QPainter 实现 ROI 绘制、缩放/平移、坐标转换与分析结果覆盖层。
- 打包使用 PyInstaller（AurascopeV6.spec），目标平台 Windows 7+。
- 设计约束：单机运行、不联网、CPU 计算、兼容 Windows 7+。