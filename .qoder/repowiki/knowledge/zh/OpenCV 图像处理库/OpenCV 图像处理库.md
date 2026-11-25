---
kind: external_dependency
name: OpenCV 图像处理库
slug: opencv-python
category: external_dependency
category_hints:
    - framework_behavior
scope:
    - '**'
---

### 图像算法核心依赖
- image.py 是唯一的算法层，集中实现阈值二值化、轮廓提取、Canny 边缘验证、圆度过滤、distanceTransform、形态学操作等。
- 与 GUI 层解耦，仅暴露 Python API 供 main_window.py 等调用。