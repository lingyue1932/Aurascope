"""图像处理工具函数"""

import os

import cv2
import numpy as np

try:                                  # GUI 是可选依赖：报告工具/无界面场景下不需要
    from PyQt6.QtWidgets import QApplication
except Exception:                     # pragma: no cover
    QApplication = None


def _pump_events():
    """长循环里让界面有机会刷新（没有 GUI 时什么都不做）

    原先直接调用 QApplication.processEvents()，把分析引擎和 PyQt6 绑死了，
    外部（如报告生成工具）只想用算法也得拖上整个 GUI 库。
    """
    if QApplication is not None:
        try:
            QApplication.processEvents()
        except Exception:
            pass


def extract_threshold_contour(img, rect_tuple, thresh_val):
    """从矩形区域提取阈值轮廓
    
    Args:
        img: 原始图像
        rect_tuple: (x, y, w, h) 矩形区域
        thresh_val: 阈值
        
    Returns:
        tuple: (rect_info, local_mask, contour) 或 (None, None, None)
    """
    if rect_tuple is None or img is None:
        return None, None, None

    x, y, w, h = map(int, rect_tuple)
    ih, iw = img.shape[:2]
    x = max(0, x)
    y = max(0, y)
    w = min(w, iw - x)
    h = min(h, ih - y)
    
    if w <= 1 or h <= 1:
        return None, None, None

    roi_src = img[y:y + h, x:x + w]
    if len(roi_src.shape) == 2:
        gray = roi_src
    else:
        gray = cv2.cvtColor(roi_src, cv2.COLOR_BGR2GRAY)

    _, mask = cv2.threshold(gray, int(thresh_val), 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return (x, y, w, h), mask, None

    max_cnt = max(contours, key=cv2.contourArea)
    if cv2.contourArea(max_cnt) <= 3:
        return (x, y, w, h), mask, None

    max_cnt = max_cnt.astype(np.int32)
    max_cnt[:, 0, 0] += x
    max_cnt[:, 0, 1] += y
    return (x, y, w, h), mask, max_cnt


def resample_polygon_points(points, target_count):
    """重采样多边形顶点
    
    Args:
        points: 原始顶点列表
        target_count: 目标顶点数
        
    Returns:
        list: 重采样后的顶点列表
    """
    if len(points) < 3:
        return points
        
    pts = np.array(points, dtype=np.float32)
    segs = np.roll(pts, -1, axis=0) - pts
    seg_len = np.linalg.norm(segs, axis=1)
    total_len = float(np.sum(seg_len))
    
    if total_len <= 1e-6:
        return points

    target_count = max(3, int(target_count))
    cumsum = np.cumsum(seg_len)
    step = total_len / target_count
    out = []
    
    for i in range(target_count):
        d = i * step
        seg_idx = int(np.searchsorted(cumsum, d, side='right'))
        seg_idx = min(seg_idx, len(pts) - 1)
        prev_sum = 0.0 if seg_idx == 0 else float(cumsum[seg_idx - 1])
        t = (d - prev_sum) / max(float(seg_len[seg_idx]), 1e-6)
        p0 = pts[seg_idx]
        p1 = pts[(seg_idx + 1) % len(pts)]
        out.append(((1 - t) * p0 + t * p1).tolist())
        
    return out


def contour_to_polygon(contour, target_vertices):
    """将轮廓转换为多边形
    
    Args:
        contour: OpenCV轮廓
        target_vertices: 目标顶点数
        
    Returns:
        list: 多边形顶点列表
    """
    if contour is None:
        return []
        
    peri = cv2.arcLength(contour, True)
    eps = max(0.5, 0.002 * peri)
    approx = cv2.approxPolyDP(contour, eps, True)
    points = approx.reshape(-1, 2).astype(float).tolist()

    if len(points) < 3:
        points = contour.reshape(-1, 2).astype(float).tolist()

    if len(points) > target_vertices:
        points = resample_polygon_points(points, target_vertices)
    return points


def polygon_to_mask(points, img_shape):
    """将多边形转换为掩码
    
    Args:
        points: 多边形顶点列表
        img_shape: 图像尺寸 (h, w)
        
    Returns:
        numpy.ndarray: 二值掩码
    """
    if len(points) < 3:
        return None
        
    h, w = img_shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    pts = np.array(points, dtype=np.int32)
    cv2.fillPoly(mask, [pts], 255)
    return mask


def build_snap_edge_mask(rect_info, local_mask, img_shape):
    """构建边缘吸附掩码
    
    Args:
        rect_info: (x, y, w, h) 矩形信息
        local_mask: 局部掩码
        img_shape: 图像尺寸 (h, w)
        
    Returns:
        numpy.ndarray: 边缘掩码
    """
    if rect_info is None or local_mask is None:
        return None
        
    x, y, w, h = rect_info
    h_img, w_img = img_shape[:2]
    edge_mask = np.zeros((h_img, w_img), dtype=np.uint8)
    edge_local = cv2.Canny(local_mask, 50, 150)
    edge_mask[y:y + h, x:x + w] = edge_local
    return edge_mask


def otsu_threshold(gray_img, roi_mask=None):
    """用 Otsu 算法自动计算最佳阈值
    
    Args:
        gray_img: 灰度图像
        roi_mask: ROI 掩码（可选，None则对全图计算）
        
    Returns:
        int: 计算得到的阈值 (0-255)
    """
    if roi_mask is not None:
        roi_pixels = gray_img[roi_mask == 255]
    else:
        roi_pixels = gray_img.flatten()
    if len(roi_pixels) == 0:
        return 128
    thresh, _ = cv2.threshold(roi_pixels, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return int(thresh)


def detect_voids(gray_img, roi_mask, thresh_val,
                 min_area=1, max_area=None,
                 enhanced=False, clahe_enabled=True,
                 morph_enabled=True, morph_kernel=3,
                 min_roundness=0.0, edge_verify=False,
                 edge_thresh=0.3,
                 clahe_clip_limit=2.0,
                 roi_erosion_px=3):
    if enhanced and clahe_enabled:
        clahe = cv2.createCLAHE(clipLimit=clahe_clip_limit, tileGridSize=(8, 8))
        processed = clahe.apply(gray_img)
    else:
        processed = gray_img.copy()

    _, bin_inv = cv2.threshold(processed, thresh_val, 255, cv2.THRESH_BINARY_INV)

    if enhanced and morph_enabled and morph_kernel > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel, morph_kernel))
        bin_inv = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, kernel)

    if roi_erosion_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (roi_erosion_px * 2 + 1, roi_erosion_px * 2 + 1))
        interior_mask = cv2.erode(roi_mask, kernel, iterations=1)
    else:
        interior_mask = roi_mask
    void_mask = cv2.bitwise_and(bin_inv, bin_inv, mask=interior_mask)
    contours, _ = cv2.findContours(void_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 5. Canny 边缘图（用于 edge_verify）
    edge_map = None
    if enhanced and edge_verify:
        blurred = cv2.GaussianBlur(processed, (5, 5), 1.0)
        edge_map = cv2.Canny(blurred, 30, 100)
        edge_map = cv2.bitwise_and(edge_map, edge_map, mask=roi_mask)

    voids_data = []
    void_id = 1

    for i, cnt in enumerate(contours):
        if i % 10 == 0:
            _pump_events()
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue

        if enhanced and min_roundness > 0:
            perimeter = cv2.arcLength(cnt, True)
            if perimeter > 0:
                roundness_val = (4 * np.pi * area) / (perimeter ** 2)
                roundness_val = min(roundness_val, 1.0)
                if roundness_val < min_roundness:
                    continue

        # Canny 边缘验证
        if enhanced and edge_verify and edge_map is not None:
            contour_mask = np.zeros_like(edge_map)
            cv2.drawContours(contour_mask, [cnt], -1, 255, 1)
            overlap = cv2.bitwise_and(contour_mask, contour_mask, mask=edge_map)
            edge_pixels = cv2.countNonZero(overlap)
            total_pixels = cv2.countNonZero(contour_mask)
            if total_pixels > 0 and (edge_pixels / total_pixels) < edge_thresh:
                continue

        x, y, w, h = cv2.boundingRect(cnt)
        M = cv2.moments(cnt)
        if M["m00"] != 0:
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
        else:
            cx, cy = x + w/2, y + h/2

        pts = cnt.reshape(-1, 2).tolist()

        voids_data.append({
            'id': void_id,
            'area_px': area,
            'rect': (x, y, w, h),
            'cx': cx,
            'cy': cy,
            'points': pts,
            'manual': False
        })
        void_id += 1

    return voids_data


def is_void_in_roi(points, roi_mask):
    """检查空洞是否在ROI内
    
    Args:
        points: 空洞轮廓点
        roi_mask: ROI掩码
        
    Returns:
        bool: 是否在ROI内
    """
    if roi_mask is None:
        return False
        
    pts = np.array(points, dtype=np.int32)
    mask = np.zeros_like(roi_mask)
    cv2.fillPoly(mask, [pts], 255)
    overlap = cv2.bitwise_and(mask, roi_mask)
    mask_area = cv2.countNonZero(mask)
    if mask_area == 0:
        return False
    return cv2.countNonZero(overlap) > mask_area * 0.5


def calculate_roundness(points, area_px):
    """计算圆度
    
    Args:
        points: 轮廓点
        area_px: 面积（像素）
        
    Returns:
        float: 圆度值 (0-1)
    """
    perimeter = cv2.arcLength(np.array(points), True)
    if perimeter > 0:
        roundness = (4 * np.pi * area_px) / (perimeter ** 2)
        return min(roundness, 1.0)
    return 0.0

def detect_voids_local(gray_img, roi_mask, global_thresh_val, local_regions=None,
                       min_area=1, max_area=None,
                       enhanced=False, clahe_enabled=True,
                       clahe_clip_limit=2.0,
                       morph_enabled=True, morph_kernel=3,
                       min_roundness=0.0, edge_verify=False,
                       edge_thresh=0.3,
                       roi_erosion_px=3):
    if enhanced and clahe_enabled:
        clahe = cv2.createCLAHE(clipLimit=clahe_clip_limit, tileGridSize=(8, 8))
        gray_img = clahe.apply(gray_img)
    _, bin_inv = cv2.threshold(gray_img, global_thresh_val, 255, cv2.THRESH_BINARY_INV)
    if enhanced and morph_enabled and morph_kernel > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel, morph_kernel))
        bin_inv = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, kernel)

    if local_regions:
        for region in local_regions:
            x, y, w, h, local_thresh = region
            x, y, w, h = int(x), int(y), int(w), int(h)
            x = max(0, x)
            y = max(0, y)
            w = min(w, gray_img.shape[1] - x)
            h = min(h, gray_img.shape[0] - y)
            if w <= 0 or h <= 0:
                continue
            local_gray = gray_img[y:y+h, x:x+w]
            _, local_bin = cv2.threshold(local_gray, local_thresh, 255, cv2.THRESH_BINARY_INV)
            bin_inv[y:y+h, x:x+w] = local_bin

    if roi_erosion_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (roi_erosion_px * 2 + 1, roi_erosion_px * 2 + 1))
        interior_mask = cv2.erode(roi_mask, kernel, iterations=1)
    else:
        interior_mask = roi_mask
    void_mask = cv2.bitwise_and(bin_inv, bin_inv, mask=interior_mask)
    contours, _ = cv2.findContours(void_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    edge_map = None
    if enhanced and edge_verify:
        blurred = cv2.GaussianBlur(gray_img, (5, 5), 1.0)
        edge_map = cv2.Canny(blurred, 30, 100)
        edge_map = cv2.bitwise_and(edge_map, edge_map, mask=interior_mask)

    voids_data = []
    void_id = 1

    for i, cnt in enumerate(contours):
        if i % 10 == 0:
            _pump_events()
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue

        if enhanced and min_roundness > 0:
            perimeter = cv2.arcLength(cnt, True)
            if perimeter > 0:
                roundness_val = (4 * np.pi * area) / (perimeter ** 2)
                roundness_val = min(roundness_val, 1.0)
                if roundness_val < min_roundness:
                    continue

        if enhanced and edge_verify and edge_map is not None:
            contour_mask = np.zeros_like(edge_map)
            cv2.drawContours(contour_mask, [cnt], -1, 255, 1)
            overlap = cv2.bitwise_and(contour_mask, contour_mask, mask=edge_map)
            edge_pixels = cv2.countNonZero(overlap)
            total_pixels = cv2.countNonZero(contour_mask)
            if total_pixels > 0 and (edge_pixels / total_pixels) < edge_thresh:
                continue

        x, y, w, h = cv2.boundingRect(cnt)
        M = cv2.moments(cnt)
        if M["m00"] != 0:
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
        else:
            cx, cy = x + w/2, y + h/2

        pts = cnt.reshape(-1, 2).tolist()

        voids_data.append({
            'id': void_id,
            'area_px': area,
            'rect': (x, y, w, h),
            'cx': cx,
            'cy': cy,
            'points': pts,
            'manual': False
        })
        void_id += 1

    return voids_data


def detect_objects(gray_img,
                   thresh_val,
                   min_area=1,
                   max_area=None,
                   enhanced=False,
                   clahe_enabled=True,
                   clahe_clip_limit=2.0,
                   morph_enabled=True,
                   morph_kernel=3,
                   morph_shape=cv2.MORPH_ELLIPSE,
                   min_roundness=0.0,
                   edge_verify=False,
                   edge_thresh=0.3,
                   invert=False,
                   watershed_enabled=False,
                   watershed_distance=0.5,
                   roi_mask=None):
    """基于增强检测的物料计数（无ROI约束）
    复用空洞检测的核心逻辑，适用于蓝膜上的LD/Submount等有明显边缘的物料。
    
    Args:
        gray_img: 灰度图像
        thresh_val: 二值化阈值 (0-255)
        min_area / max_area: 面积过滤
        enhanced: 是否启用增强检测
        clahe_enabled / clahe_clip_limit: CLAHE 对比度增强
        morph_enabled / morph_kernel: 形态学去噪（开运算）
        min_roundness: 圆度过滤 (0-1, 0=关闭)
        edge_verify / edge_thresh: Canny 边缘验证
        invert: True=检测亮色物体(THRESH_BINARY_INV), False=检测暗色物体(THRESH_BINARY)
        watershed_enabled: 启用距离峰值计数（分离粘连物体）
        watershed_distance: 最小峰值间距（像素, 3-50），越大越保守
    
    Returns:
        list: 对象信息字典列表
    """
    if enhanced and clahe_enabled:
        clahe = cv2.createCLAHE(clipLimit=clahe_clip_limit, tileGridSize=(8, 8))
        processed = clahe.apply(gray_img)
    else:
        processed = gray_img.copy()

    type_flag = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    _, bin_img = cv2.threshold(processed, thresh_val, 255, type_flag)

    if enhanced and morph_enabled and morph_kernel > 1:
        kernel = cv2.getStructuringElement(morph_shape, (morph_kernel, morph_kernel))
        bin_img = cv2.morphologyEx(bin_img, cv2.MORPH_OPEN, kernel)
        morph_close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel * 2 + 1, morph_kernel * 2 + 1))
        bin_img = cv2.morphologyEx(bin_img, cv2.MORPH_CLOSE, morph_close_kernel)

    if roi_mask is not None:
        bin_img = cv2.bitwise_and(bin_img, roi_mask)
    if watershed_enabled and cv2.countNonZero(bin_img) > 0:
        dist = cv2.distanceTransform(bin_img, cv2.DIST_L2, 3)
        ksize = max(3, int(watershed_distance) * 2 + 1)
        kernel_peak = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
        dilated = cv2.dilate(dist, kernel_peak)
        peak_mask = np.uint8((dist == dilated) & (dist > 1.0))
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(peak_mask)
        objects = []
        obj_id = 1
        for label in range(1, num_labels):
            cx, cy = centroids[label]
            xi, yi = int(round(cx)), int(round(cy))
            if not (0 <= yi < dist.shape[0] and 0 <= xi < dist.shape[1]):
                continue
            radius = max(2.0, dist[yi, xi])
            pts = []
            for a in range(0, 360, 15):
                rad = np.radians(a)
                pts.append([cx + radius * np.cos(rad), cy + radius * np.sin(rad)])
            area = cv2.contourArea(np.array(pts, dtype=np.int32))
            if area < min_area:
                continue
            x_r, y_r, w_r, h_r = cv2.boundingRect(np.array(pts, dtype=np.int32))
            objects.append({
                'id': obj_id, 'area_px': area, 'rect': (x_r, y_r, w_r, h_r),
                'cx': cx, 'cy': cy, 'points': pts,
            })
            obj_id += 1
        return objects

    contours, _ = cv2.findContours(bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Canny 边缘图（用于 edge_verify）
    edge_map = None
    if enhanced and edge_verify:
        blurred = cv2.GaussianBlur(processed, (5, 5), 1.0)
        edge_map = cv2.Canny(blurred, 30, 100)

    objects = []
    obj_id = 1

    for i, cnt in enumerate(contours):
        if i % 10 == 0:
            _pump_events()
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue

        if enhanced and min_roundness > 0:
            perimeter = cv2.arcLength(cnt, True)
            if perimeter > 0:
                roundness_val = (4 * np.pi * area) / (perimeter ** 2)
                roundness_val = min(roundness_val, 1.0)
                if roundness_val < min_roundness:
                    continue

        # Canny 边缘验证
        if enhanced and edge_verify and edge_map is not None:
            contour_mask = np.zeros_like(edge_map)
            cv2.drawContours(contour_mask, [cnt], -1, 255, 1)
            overlap = cv2.bitwise_and(contour_mask, contour_mask, mask=edge_map)
            edge_pixels = cv2.countNonZero(overlap)
            total_pixels = cv2.countNonZero(contour_mask)
            if total_pixels > 0 and (edge_pixels / total_pixels) < edge_thresh:
                continue

        x, y, w, h = cv2.boundingRect(cnt)
        M = cv2.moments(cnt)
        if M["m00"] != 0:
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
        else:
            cx, cy = x + w / 2, y + h / 2

        pts = cnt.reshape(-1, 2).tolist()

        objects.append({
            'id': obj_id,
            'area_px': area,
            'rect': (x, y, w, h),
            'cx': cx,
            'cy': cy,
            'points': pts,
        })
        obj_id += 1

    return objects


def create_local_region_around_void(void_info, padding=20):
    """
    根据空洞位置创建局部区域
    
    Args:
        void_info: 空洞信息字典
        padding: 扩展像素数
    
    Returns:
        tuple: (x, y, w, h)
    """
    x, y, w, h = void_info['rect']
    x = max(0, int(x - padding))
    y = max(0, int(y - padding))
    w = int(w + 2 * padding)
    h = int(h + 2 * padding)
    return (x, y, w, h)

# def detect_voids_local(gray_img, roi_mask, global_thresh, local_regions):
#     """使用局部阈值检测空洞
    
#     Args:
#         gray_img: 灰度图像
#         roi_mask: ROI掩码
#         global_thresh: 全局阈值
#         local_regions: 局部区域列表 [(x, y, w, h, local_thresh), ...]
        
#     Returns:
#         list: 空洞信息列表
#     """
#     # 先用全局阈值
#     _, bin_inv = cv2.threshold(gray_img, global_thresh, 255, cv2.THRESH_BINARY_INV)
    
#     # 对局部区域应用不同的阈值
#     for region in local_regions:
#         x, y, w, h, local_thresh = region
#         x, y, w, h = map(int, [x, y, w, h])
        
#         # 边界检查
#         ih, iw = gray_img.shape[:2]
#         x = max(0, x)
#         y = max(0, y)
#         w = min(w, iw - x)
#         h = min(h, ih - y)
        
#         if w <= 1 or h <= 1:
#             continue
        
#         # 在局部区域应用局部阈值
#         roi = gray_img[y:y+h, x:x+w]
#         _, local_bin = cv2.threshold(roi, local_thresh, 255, cv2.THRESH_BINARY_INV)
#         bin_inv[y:y+h, x:x+w] = local_bin
    
#     # 应用ROI掩码
#     void_mask = cv2.bitwise_and(bin_inv, bin_inv, mask=roi_mask)
    
#     # 检测空洞轮廓
#     contours, _ = cv2.findContours(void_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    
#     voids_data = []
#     void_id = 1
    
#     for cnt in contours:
#         area = cv2.contourArea(cnt)
#         if area < 1:
#             continue
            
#         x, y, w, h = cv2.boundingRect(cnt)
#         M = cv2.moments(cnt)
#         if M["m00"] != 0:
#             cx = M["m10"] / M["m00"]
#             cy = M["m01"] / M["m00"]
#         else:
#             cx, cy = x + w/2, y + h/2
            
#         pts = cnt.reshape(-1, 2).tolist()
        
#         voids_data.append({
#             'id': void_id,
#             'area_px': area,
#             'rect': (x, y, w, h),
#             'cx': cx,
#             'cy': cy,
#             'points': pts,
#             'manual': False
#         })
#         void_id += 1
        
#     return voids_data


# def create_local_region_around_void(void_data, margin=20):
#     """在空洞周围创建局部区域
    
#     Args:
#         void_data: 空洞数据字典
#         margin: 扩展边距（像素）
        
#     Returns:
#         tuple: (x, y, w, h) 局部区域
#     """
#     x, y, w, h = void_data['rect']
    
#     # 扩展区域
#     x_new = max(0, x - margin)
#     y_new = max(0, y - margin)
#     w_new = w + 2 * margin
#     h_new = h + 2 * margin
    
#     return (x_new, y_new, w_new, h_new)


# ============================================================
# 示教学习（taught model）
# 从用户示范学习焊层/空洞外观（统计学习，非神经网络），批量逐图套用。
# 本区函数全部无 Qt 依赖，可独立单测。
# ============================================================

def array_stats(px):
    """一维像素数组的灰度统计"""
    px = np.asarray(px, dtype=np.float64).ravel()
    if px.size == 0:
        return None
    return {
        'median': float(np.median(px)),
        'std': float(np.std(px)),
        'p5': float(np.percentile(px, 5)),
        'p95': float(np.percentile(px, 95)),
        'count': int(px.size),
    }


def class_stats(gray, mask=None):
    """计算一类像素的灰度统计（mask 为 None 时用全图）"""
    if mask is not None:
        return array_stats(gray[mask > 0])
    return array_stats(gray)


def two_class_threshold(hist_a, hist_b):
    """两类直方图的分离阈值：最小化 balanced 误分类率（调用顺序无关）

    直接优化"已知标签的两类互分错得最少"——语义与示教一致（我们明确知道
    哪些像素属于哪类）。区别于分区内方差法（Otsu）：当背景类呈多峰时
    （如上方亮区+下方暗区+白边），分区内方差会错误地落到背景类内部的谷里，
    误分类率不会。最终取 J 最小 ±2% 容差带的中点（谷底正中），抗灰度漂移。

    Args:
        hist_a / hist_b: 长度 256 的灰度直方图（两类各自的分布）
    Returns:
        float: 分离阈值；输入非法返回 None
    """
    ha = np.asarray(hist_a, dtype=np.float64).ravel()
    hb = np.asarray(hist_b, dtype=np.float64).ravel()
    if ha.size < 256 or hb.size < 256:
        return None
    ha, hb = ha[:256], hb[:256]
    na, nb = float(ha.sum()), float(hb.sum())
    if na <= 0 or nb <= 0:
        return None
    # 按两类中位数判定高低方向（调用顺序无关）：低类应落在阈值下侧
    v = np.arange(256, dtype=np.float64)
    med_a = float((np.cumsum(ha) / na >= 0.5).argmax())
    med_b = float((np.cumsum(hb) / nb >= 0.5).argmax())
    if med_a <= med_b:
        low, high = ha, hb
    else:
        low, high = hb, ha
    cdf_low = np.cumsum(low) / low.sum()      # P(low <= t)
    cdf_high = np.cumsum(high) / high.sum()   # P(high <= t)
    # J(t) = 0.5·P(low>t) + 0.5·P(high<=t)：低类漏到高侧 + 高类漏到低侧
    J = 0.5 * (1.0 - cdf_low[:255]) + 0.5 * cdf_high[:255]
    jmin = float(J.min())
    # 容差带取中：J 接近最小的区间往往是一段谷底；取中点而非边缘，
    # 对批次图的灰度漂移更稳健（贴类边缘的阈值稍有漂移就会截断该类）
    opt = np.where(J <= jmin + 0.02)[0]
    return float(opt[len(opt) // 2])


def class_separability(stats_a, stats_b):
    """两类灰度可分性（中位数差 / 合并 std）；<1.5 提示示范可能不充分

    上限截到 99.9：类内 std 为 0 时（合成图/极干净样本）会算出极大值，
    界面上显示无意义。
    """
    if not stats_a or not stats_b:
        return 0.0
    pooled = max((stats_a['std'] + stats_b['std']) / 2.0, 1e-6)
    return min(99.9, abs(stats_a['median'] - stats_b['median']) / pooled)


def fill_holes(mask):
    """填充二值掩码内部孔洞（焊层带被空洞分割后的轮廓复原）"""
    h, w = mask.shape[:2]
    padded = np.zeros((h + 2, w + 2), dtype=np.uint8)
    padded[1:-1, 1:-1] = mask
    cv2.floodFill(padded, None, (0, 0), 255)
    holes = np.where(padded[1:-1, 1:-1] == 0, 255, 0).astype(np.uint8)
    return cv2.bitwise_or(mask, holes)


def band_geometry(mask):
    """二值掩码的归一化几何特征（按图像尺寸归一，跨倍率可比）"""
    if mask is None:
        return None
    h, w = mask.shape[:2]
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    return {
        'cx_norm': round((x0 + x1) / 2.0 / w, 4),
        'cy_norm': round((y0 + y1) / 2.0 / h, 4),
        'w_norm': round(bw / float(w), 4),
        'h_norm': round(bh / float(h), 4),
        'area_frac': round(float(xs.size) / (w * h), 5),
        'aspect': round(bw / float(max(bh, 1)), 3),
    }


DEFAULT_BAND_TOL = {
    'center_shift': 0.15,     # 中心偏移：占图像对角线归一化后的比例
    'area_lo': 0.4, 'area_hi': 2.5,
    'aspect_lo': 0.5, 'aspect_hi': 2.0,
}


def compare_band_geometry(ref, cur, tol=None):
    """比较当前焊层带与示教模板的几何偏差（位置/面积/长宽比）

    Returns:
        (dev, warnings)：dev 为偏差字典；warnings 为超差说明（空则未超差）
    """
    if not ref or not cur:
        return None, []
    t = dict(DEFAULT_BAND_TOL)
    t.update(tol or {})
    dx = cur['cx_norm'] - ref['cx_norm']
    dy = cur['cy_norm'] - ref['cy_norm']
    dev = {
        'center_shift': round(float(np.hypot(dx, dy)), 4),
        'area_ratio': round(cur['area_frac'] / max(ref['area_frac'], 1e-9), 3),
        'aspect_ratio': round(cur['aspect'] / max(ref['aspect'], 1e-9), 3),
    }
    warnings = []
    if dev['center_shift'] > t['center_shift']:
        warnings.append(f"焊层带位置偏离示教 {dev['center_shift'] * 100:.0f}%"
                        f"（阈值 {t['center_shift'] * 100:.0f}%）")
    if not (t['area_lo'] <= dev['area_ratio'] <= t['area_hi']):
        warnings.append(f"焊层带面积偏差 {dev['area_ratio']:.2f} 倍"
                        f"（合理 {t['area_lo']}~{t['area_hi']}）")
    if not (t['aspect_lo'] <= dev['aspect_ratio'] <= t['aspect_hi']):
        warnings.append(f"焊层带长宽比偏差 {dev['aspect_ratio']:.2f} 倍"
                        f"（合理 {t['aspect_lo']}~{t['aspect_hi']}）")
    return dev, warnings


def locate_solder_band(gray, t_solder, min_aspect=3.0,
                       min_area_frac=0.01, close_kernel=5, band_ref=None,
                       open_kernel=5, min_thickness_px=8):
    """按示教学到的阈值定位焊层带（位置/形状每张图自适应）

    流程：二值化 → 开运算断开细界面 → 闭运算 → 连通域 → 横向长条候选
    → 择带 → 孔洞填充 → 竖向开运算剔除薄结构。

    三个关键判据：

    1. **开运算断开细界面**：焊层与"灰度相近但非焊料"的邻层在图上紧贴，
       界面线常只有 1~3px；不做开运算两者连通成一个组件，邻层会被一起
       框进焊层。
    2. **几何先验择带**（band_ref 提供时）：按与示教模板的几何匹配度
       （中心位置/面积/长宽比）选带，而不是"最亮最大"。灰度相近的区域
       在图像别处（另一层、另一侧结构）同样能过阈值，只有几何先验能把
       它们排除。
    3. **最小宽度**：界面反应层/过渡带会形成挂在本体上的竖直薄滴/毛刺
       （只有几像素宽），被一起算进金锡面积。用**水平**线结构元开运算剔除
       水平方向连续不足 min_thickness_px 的结构——对水平延展的焊层带
       几乎无损（实测仅削减 0.2% 量级）。

    Returns:
        (band_mask, diagnostics)；找不到返回 (None, diagnostics)
    """
    _, mask = cv2.threshold(gray, float(t_solder), 255, cv2.THRESH_BINARY)
    # 清零最外 2px 框：扫描/SEM 图边缘常见 1-2px 的渲染图框线，
    # 会顺全长把焊层带与图中其他亮斑连成一个大组件，令组件级判据失效
    mask[:2, :] = 0
    mask[-2:, :] = 0
    mask[:, :2] = 0
    mask[:, -2:] = 0
    if open_kernel and open_kernel > 1:
        ko = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                       (open_kernel, open_kernel))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ko)
    if close_kernel > 1:
        # 横向结构元（1×k）：只连接左右方向的碎片（大空洞/划痕把焊层带截断），
        # 不会桥接"上下相邻"的横向界面缝——用方阵/椭圆核会把 1px 界面缝焊死，
        # 把灰度相近的邻层又并回焊层
        kc = cv2.getStructuringElement(cv2.MORPH_RECT, (close_kernel, 1))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kc)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    h_img, w_img = gray.shape[:2]
    min_area = max(min_area_frac * h_img * w_img, 20.0)
    cands = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area or h <= 0:
            continue
        if w / float(h) < min_aspect:
            continue
        filled = fill_holes((labels == i).astype(np.uint8) * 255)
        filled_area = int(cv2.countNonZero(filled))
        if filled_area <= 0:
            continue
        bright_cnt = int(np.count_nonzero((gray > float(t_solder))
                                          & (filled > 0)))
        # 疑似 SEM 图白边/图框的判据：
        # ① 紧贴图像上下边界（阈值化会把最外 1~2 行剔掉，故容差取图像高度的 2%）
        # ② 填孔后中位灰度接近纯白（白边 255，焊料通常 180~230）
        y_tol = max(3, int(0.02 * h_img))
        touch_border = (y <= y_tol) or (y + h >= h_img - y_tol)
        filled_med = float(np.median(gray[filled > 0])) if filled_area else 0.0
        cands.append({
            'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h),
            'area': int(area), 'label': i, 'filled': filled,
            'bright_frac': bright_cnt / float(filled_area),
            'geom': band_geometry(filled),
            'suspect_border': bool(touch_border or filled_med > 240),
        })
    if not cands:
        return None, {'reason': 'no_elongated_component',
                      't_solder': float(t_solder)}

    # 优先弃用疑似白边/图框的候选；若全是，才退而使用
    inner = [c for c in cands if not c['suspect_border']]
    if inner:
        cands = inner

    if band_ref:
        # 几何先验择带：纵向窗口内的候选优先（排除图像别处的灰度相近区），
        # 窗口内再取与示教模板几何最接近者
        win = max(0.25, DEFAULT_BAND_TOL['center_shift'])
        in_win = [c for c in cands
                  if abs(c['geom']['cy_norm'] - band_ref['cy_norm']) <= win]
        pool = in_win or cands
        keep = min(pool, key=lambda c: _geom_distance(band_ref, c['geom']))
        band = keep['filled'].copy()
        for c in pool:      # 只合并与主带纵向邻近、x 相接的同带碎片
            if c is keep:
                continue
            if (abs(c['geom']['cy_norm'] - keep['geom']['cy_norm']) <= 0.08
                    and _x_overlap(band, c)):
                band = cv2.bitwise_or(band, c['filled'])
    else:
        # 无几何先验（示教阶段的自动草拟）：亮填充率高者为焊层带
        keep_pool = [c for c in cands if c['bright_frac'] >= 0.6]
        if not keep_pool:
            keep_pool = [max(cands, key=lambda c: (c['bright_frac'], c['area']))]
        keep_pool.sort(key=lambda c: c['x'])
        keep = keep_pool[0]
        band = keep['filled'].copy()
        for c in keep_pool[1:]:
            # 只合并纵向邻近且 x 相接的碎片：否则上下两条白边会被并到一起，
            # 孔洞填充后会把整幅图填满
            if (abs(c['geom']['cy_norm'] - keep['geom']['cy_norm']) <= 0.08
                    and _x_overlap(band, c)):
                band = cv2.bitwise_or(band, c['filled'])
    band = fill_holes(band)

    # 终检：焊层带不可能占满大半个画面（占满通常是白边被连通的表现）
    if cv2.countNonZero(band) > 0.75 * h_img * w_img:
        return None, {'reason': 'band_too_large',
                      't_solder': float(t_solder),
                      'area_frac': round(cv2.countNonZero(band)
                                         / float(h_img * w_img), 3)}
    thin_removed = 0
    if min_thickness_px and min_thickness_px > 1:
        # 水平线结构元开运算：要求水平方向连续 ≥k 像素，从而剔除竖直方向的
        # 薄滴/毛刺（界面反应层、过渡带、撕裂毛边）——它们通常只有几像素宽，
        # 而焊层带水平方向连续数百像素，几乎不受影响。
        #
        # 方向说明：要剔除"竖直下垂的薄滴"，用的是**水平**结构元（薄滴水平
        # 方向窄，放不下）；改用竖向结构元是错的——竖向连续段因与本体相连
        # 而变长，结构元在连接处能放下，膨胀时会把薄滴长回来，剔不掉。
        # 理论上限：贴在本体上下方的**水平**薄舌头无法用形态学剔除（同上原因），
        # 这类结构只能靠人工修正。
        k = max(2, int(min_thickness_px))
        kt = cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1))
        opened = cv2.morphologyEx(band, cv2.MORPH_OPEN, kt)
        opened = fill_holes(opened)
        a0 = int(cv2.countNonZero(band))
        a1 = int(cv2.countNonZero(opened))
        # 削减超过三成说明本体本身就偏窄，宁可不过滤（避免系统性低估面积）
        if a1 > 0 and (a0 - a1) <= 0.3 * a0:
            thin_removed = a0 - a1
            band = opened

    diag = {
        'reason': 'ok',
        't_solder': float(t_solder),
        'components': len(cands),
        'bbox': (keep['x'], keep['y'], keep['w'], keep['h']),
        'bright_frac': round(keep['bright_frac'], 3),
        'geom_matched': bool(band_ref),
        'geom_distance': (round(_geom_distance(band_ref, keep['geom']), 4)
                          if band_ref else None),
        'thin_removed_px': int(thin_removed),
        'thin_removed_frac': round(thin_removed / max(cv2.countNonZero(band)
                                                      + thin_removed, 1), 4),
    }
    return band, diag


def _x_overlap(mask_a, cand_b):
    """候选 b 的 x 范围是否与已有掩码的 x 范围重叠"""
    cols = np.where(mask_a.max(axis=0) > 0)[0]
    if len(cols) == 0:
        return False
    return cand_b['x'] <= cols[-1] and cand_b['x'] + cand_b['w'] >= cols[0]


def _geom_distance(ref, cur):
    """几何匹配代价（越小越像示教模板）：中心偏移 + 面积/长宽比对数偏差"""
    if not ref or not cur:
        return 1e9
    d = abs(cur['cx_norm'] - ref['cx_norm']) + abs(cur['cy_norm'] - ref['cy_norm'])
    d += 0.3 * abs(np.log(max(cur['area_frac'], 1e-9) / max(ref['area_frac'], 1e-9)))
    d += 0.2 * abs(np.log(max(cur['aspect'], 1e-9) / max(ref['aspect'], 1e-9)))
    return float(d)


def _dominant_gray_core(px, win=7, rel=0.2):
    """取灰度直方图主峰附近的像素（焊料主材）

    示范区域里除了焊料，还可能混入空洞暗像素、以及灰度相近的邻层。
    焊料是区域内占多数的材料，取直方图主峰（平滑后）± 降到峰值 rel 倍
    以内的范围，可把两端杂质排掉——比"取中位数以上的亮半边"更抗污染
    （邻层比焊料亮时会被亮半边法带进来）。
    """
    px = np.asarray(px).ravel()
    if px.size == 0:
        return px
    hist = np.bincount(px.astype(np.uint8), minlength=256).astype(np.float64)
    sm = np.convolve(hist, np.ones(win) / win, mode='same')
    mode = int(np.argmax(sm))
    peak = sm[mode]
    lo = mode
    while lo > 0 and sm[lo - 1] > rel * peak:
        lo -= 1
    hi = mode
    while hi < 255 and sm[hi + 1] > rel * peak:
        hi += 1
    core = px[(px >= lo) & (px <= hi)]
    return core if core.size >= max(20, px.size * 0.2) else px


def grab_local_dark_blob(gray, cx, cy, t_ref, radius=40, region_mask=None):
    """从点击位置抓取局部暗核（示范空洞点选用）

    以点击点灰度锚定生长阈值（点击值 + 25% 的"焊层-点击值"差距），
    而非 patch 全局 Otsu——后者在空洞较小、焊层占满 patch 时会把
    边界线/邻侧暗区一起并进暗核，污染空洞类统计。
    region_mask 提供时（示范焊层区域），暗核被裁剪在内，防止抓到区域外结构。

    Returns:
        (blob_mask, area) 或 (None, 0)
    """
    h_img, w_img = gray.shape[:2]
    x1, y1 = max(0, int(cx) - radius), max(0, int(cy) - radius)
    x2, y2 = min(w_img, int(cx) + radius), min(h_img, int(cy) + radius)
    if x2 - x1 < 5 or y2 - y1 < 5:
        return None, 0
    patch = gray[y1:y2, x1:x2]
    px, py = int(cy) - y1, int(cx) - x1
    if not (0 <= py < patch.shape[0] and 0 <= px < patch.shape[1]):
        return None, 0
    click_v = float(patch[py, px])
    if click_v >= t_ref:
        return None, 0          # 点在了亮处，不是空洞
    grow_t = click_v + 0.25 * (float(t_ref) - click_v)
    dark = (patch <= grow_t).astype(np.uint8) * 255
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark)
    lab = labels[py, px]
    if lab == 0:
        return None, 0
    blob = np.zeros_like(dark)
    blob[labels == lab] = 255
    if region_mask is not None:
        sub = region_mask[y1:y2, x1:x2]
        blob = cv2.bitwise_and(blob, sub)
    area = int(cv2.countNonZero(blob))
    if area < 4:
        return None, 0
    # 暗度守卫：暗核中位数须明显暗于焊层阈值，挡掉边界线/浅色结构
    if float(np.median(gray[y1:y2, x1:x2][blob > 0])) > 0.7 * float(t_ref):
        return None, 0
    full = np.zeros((h_img, w_img), dtype=np.uint8)
    full[y1:y2, x1:x2] = blob
    return full, area


def detect_voids_in_band(gray, band_mask, t_void, min_area=1, max_area=None,
                         min_roundness=0.0, morph_kernel=3):
    """焊层带内空洞检测（暗核阈值 + 形态学 + 轮廓 + 过滤）

    与 detect_voids 的区别：不做 CLAHE / ROI 腐蚀（焊层带已由示教模型定位），
    阈值来自示教。返回空洞字典列表（schema 与 detect_voids 一致）。
    """
    _, dark = cv2.threshold(gray, float(t_void), 255, cv2.THRESH_BINARY_INV)
    dark = cv2.bitwise_and(dark, band_mask)
    if morph_kernel > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                      (morph_kernel, morph_kernel))
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, k)
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    voids = []
    void_id = 1
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue
        if min_roundness > 0:
            peri = cv2.arcLength(cnt, True)
            if peri > 0:
                rnd = min((4 * np.pi * area) / (peri ** 2), 1.0)
                if rnd < min_roundness:
                    continue
        x, y, w, h = cv2.boundingRect(cnt)
        M = cv2.moments(cnt)
        if M['m00'] != 0:
            cx, cy = M['m10'] / M['m00'], M['m01'] / M['m00']
        else:
            cx, cy = x + w / 2.0, y + h / 2.0
        voids.append({
            'id': void_id,
            'area_px': area,
            'rect': (int(x), int(y), int(w), int(h)),
            'cx': cx, 'cy': cy,
            'points': cnt.reshape(-1, 2).tolist(),
        })
        void_id += 1
    return voids


def learn_taught_model(gray, solder_mask, void_marks, px_per_um=0.0,
                       bar_length_px=0.0, bar_real_um=0.0,
                       bar_horizontal=True, bar_dark=True, void_blobs=None):
    """从示范学习示教模型（纯统计学习）

    Args:
        gray: 样板图灰度
        solder_mask: 用户示范的金锡区域掩码（区域外像素自动作为背景类）
        void_marks: 用户点选的空洞中心 [(cx, cy), ...]，点几个典型即可
        px_per_um: 标定得到的 像素/微米
        bar_length_px / bar_real_um: 示范时比例尺像素长度与实际微米值
        void_blobs: 调用方已抓好的空洞暗核掩码列表。提供时直接使用——
            保证"用户在画布上看到并确认的"与"模型学习的"是同一个暗核，
            避免此处重抓（参考阈值不同）导致对象不一致。
    Returns:
        dict: 示教模型（schema v2）；示范不合法返回 None
    """
    if solder_mask is None or cv2.countNonZero(solder_mask) < 50:
        return None
    # 焊层类只取示范区域内的"灰度主峰核"——区域内除焊料外可能混入空洞
    # 暗像素与灰度相近的邻层，取主峰附近可把两端杂质排掉
    # （比"取中位数以上的亮半边"更抗污染：邻层比焊料亮时会污染亮半边）
    poly_px = gray[solder_mask > 0]
    if poly_px.size < 50:
        return None
    bright_px = _dominant_gray_core(poly_px)
    stats_solder = array_stats(bright_px)
    # 背景类只取焊层周边环形带中"灰度不属于焊料"的像素。
    #
    # 关键：示范 ROI 通常只画在焊层中段，而焊层向左右延伸出去的部分是
    # 同灰度的——它们会落进背景类，使背景类含有焊料灰度，阈值被推到焊料
    # 灰度之上，导致焊料被漏、而灰度相近但更亮的邻层被误当成焊料。
    # 因此要把灰度落在焊料核心范围内的背景像素剔除。
    bx, by, bw, bh = cv2.boundingRect(solder_mask)
    ring = max(20, int(bh))
    rk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                   (ring * 2 + 1, ring * 2 + 1))
    ring_mask = cv2.dilate(solder_mask, rk)
    bg_mask = cv2.bitwise_and(ring_mask, cv2.bitwise_not(solder_mask))
    bg_px = gray[bg_mask > 0]
    if bg_px.size == 0:
        return None
    margin = max(8.0, 0.5 * stats_solder['std'])
    same_as_solder = ((bg_px >= stats_solder['p5'] - margin)
                      & (bg_px <= stats_solder['p95'] + margin))
    bg_used = bg_px[~same_as_solder]
    bg_same_frac = 1.0 - bg_used.size / float(bg_px.size)
    if bg_used.size < 50:      # 周边几乎全是同灰度像素：退回全环并留待自检
        bg_used = bg_px
        bg_same_frac = 0.0
    stats_bg = array_stats(bg_used)
    if not stats_solder or not stats_bg:
        return None
    hist_s = np.bincount(bright_px.ravel(), minlength=256)[:256]
    hist_b = np.bincount(np.asarray(bg_used).ravel(), minlength=256)[:256]
    t_solder = two_class_threshold(hist_s, hist_b)
    if t_solder is None:
        return None

    # 空洞类：优先用调用方已抓好的暗核；否则按点击位置重新抓取
    blob_areas = []
    void_pixels = []
    if void_blobs:
        for blob in void_blobs:
            if blob is None:
                continue
            area = int(cv2.countNonZero(blob))
            if area < 4:
                continue
            blob_areas.append(area)
            void_pixels.append(gray[blob > 0])
    else:
        for mark in void_marks or []:
            cx, cy = mark
            blob, area = grab_local_dark_blob(gray, int(cx), int(cy), t_solder,
                                              region_mask=solder_mask)
            if blob is None:
                continue
            blob_areas.append(area)
            void_pixels.append(gray[blob > 0])
    t_void, stats_void = None, None
    if void_pixels:
        all_void = np.concatenate(void_pixels)
        stats_void = array_stats(all_void)
        hist_v = np.bincount(all_void.ravel(), minlength=256)[:256]
        t_void = two_class_threshold(hist_v, hist_s)
    if blob_areas:
        v_min = max(4, int(min(blob_areas) * 0.5))
        v_max = int(max(blob_areas) * 2.0)
    else:
        v_min, v_max = 4, None

    return {
        'schema_version': 3,
        'type': 'taught',
        'name': '',
        'note': '',
        'updated': '',
        'solder': {
            'median': round(stats_solder['median'], 1),
            'std': round(stats_solder['std'], 1),
            'p5': round(stats_solder['p5'], 1),
            'p95': round(stats_solder['p95'], 1),
            'threshold': round(float(t_solder), 1),
        },
        'background': {
            'median': round(stats_bg['median'], 1),
            'std': round(stats_bg['std'], 1),
        },
        'void': {
            'threshold': round(float(t_void), 1) if t_void is not None else None,
            # 面积下限：0 = 自动（按带面积 0.02%，下限 12px²）；
            # 上限：None = 自动（按带面积 30%，仅作分割失败兜底）
            # 两者都不再默认取"点选尺寸的 0.5× / 2×"——那会把比点选更小的、
            # 以及最大的空洞分别排除掉
            'min_area': 0,
            'min_area_taught': v_min,
            'max_area': None,
            'max_area_taught': v_max,
            'min_roundness': 0.0,
            # 深度容差（灰阶偏移）：正值 = 更包容，可把偏浅的暗斑也算作空洞
            'depth_offset': 0.0,
            'taught_count': len(blob_areas),
            'median': round(stats_void['median'], 1) if stats_void else None,
        },
        'px_per_um': float(px_per_um or 0.0),
        # 示教样板图整体灰度中位数：批量时用于亮度补偿（阈值是绝对灰度）
        'ref_median': float(np.median(gray)),
        'band': {'min_aspect': 3.0, 'min_area_frac': 0.01, 'open_kernel': 5,
                 'min_thickness_px': 8},
        # 示教模板的焊层几何（用户修正后的 ROI 即基准），批量时用于偏差校验
        'band_ref': band_geometry(solder_mask),
        'scale_bar': {
            'horizontal': bool(bar_horizontal),
            'dark': bool(bar_dark),
            'length_px': float(bar_length_px or 0.0),
            'real_um': float(bar_real_um or 0.0),
        },
        'diagnostics': {
            'solder_bg_separability': round(
                class_separability(stats_solder, stats_bg), 2),
            'solder_void_separability': round(
                class_separability(stats_solder, stats_void), 2) if stats_void else None,
            # 周边环形带里"与焊料同灰度"的像素占比：占比高说明 ROI 周边有
            # 灰度相近的结构（例如焊层向左右延伸、或邻层与焊料同灰度），
            # 程序已把这类像素从背景类剔除，不会污染阈值
            'bg_same_gray_frac': round(bg_same_frac, 3),
        },
    }


def apply_taught_model(gray, model):
    """对单张批次图套用示教模型

    Returns:
        dict: {ok, band_mask, solder_area_px, voids, void_count, void_area_px,
               void_rate, t_void_used, brightness_drift, warnings, diagnostics}
    """
    warnings = []
    det = model.get('solder') or {}
    t_solder = det.get('threshold')
    if t_solder is None:
        return {'ok': False, 'warnings': ['模型缺少焊层阈值']}
    void_cfg = model.get('void') or {}
    t_void = void_cfg.get('threshold')
    band_cfg = model.get('band') or {}
    band, diag = locate_solder_band(
        gray, t_solder,
        min_aspect=band_cfg.get('min_aspect', 3.0),
        min_area_frac=band_cfg.get('min_area_frac', 0.01),
        band_ref=model.get('band_ref'),
        open_kernel=int(band_cfg.get('open_kernel', 5) or 5),
        min_thickness_px=int(band_cfg.get('min_thickness_px', 8) or 0))
    t_used = t_solder
    if band is None:
        # 阈值是绝对灰度，对整幅图的亮度漂移脆弱（同产品不同曝光/增益）。
        # 用"示教样板图整体中位数"做亮度补偿后重试一次。
        ref_med = model.get('ref_median')
        cur_med = float(np.median(gray))
        if ref_med and abs(cur_med - ref_med) >= 3:
            t_adj = float(t_solder) + (cur_med - float(ref_med))
            band2, diag2 = locate_solder_band(
                gray, t_adj,
                min_aspect=band_cfg.get('min_aspect', 3.0),
                min_area_frac=band_cfg.get('min_area_frac', 0.01),
                band_ref=model.get('band_ref'),
                open_kernel=int(band_cfg.get('open_kernel', 5) or 5),
        min_thickness_px=int(band_cfg.get('min_thickness_px', 8) or 0))
            if band2 is not None:
                band, diag, t_used = band2, diag2, t_adj
                warnings.append(
                    f"按图像整体亮度补偿阈值 {t_solder:.0f}→{t_adj:.0f}")
    if band is None:
        return {'ok': False,
                'warnings': [f"未找到焊层带({diag.get('reason')})"],
                'diagnostics': diag}
    solder_area = int(cv2.countNonZero(band))

    # 厚度过滤剔除较多面积时提示（细结构多，可能是界面层/过渡带或定位偏差）
    thin_frac = (diag or {}).get('thin_removed_frac') or 0.0
    if thin_frac > 0.02:
        warnings.append(
            f"厚度过滤剔除了 {thin_frac * 100:.1f}% 面积（细结构较多），建议核查")

    # 与示教模板的几何偏差校验：位置偏离/面积/长宽比超差即告警
    dev, dev_warns = compare_band_geometry(model.get('band_ref'),
                                          band_geometry(band),
                                          model.get('band_tol'))
    warnings.extend(dev_warns)

    # 亮度自检：本图焊层类中位数 vs 模型记录值
    drift = 0.0
    cur = array_stats(gray[band > 0])
    if cur and det.get('median'):
        drift = abs(cur['median'] - det['median']) / max(det['median'], 1.0)
        if drift > 0.25:
            warnings.append(f"焊层亮度漂移 {drift * 100:.0f}%，请确认拍摄条件一致")

    if t_void is None:
        t_void = otsu_threshold(gray, band)
        warnings.append('空洞阈值退回带内 Otsu')

    # 桥接"贴边空洞"造成的边界缺口：空洞是焊料内部的孔，贴到边界会把边界
    # 咬出缺口、把面积挖掉。放在空洞检测之前，新纳入的空洞才能被正常检出。
    # bridge_win_px：-1/缺省 = 自动，0 = 关闭，>1 = 指定窗口
    _bw = band_cfg.get('bridge_win_px', -1)
    bridge_win = -1 if _bw is None else int(_bw)
    if bridge_win == 0:
        diag = {**(diag or {}), 'bridge': {'reason': 'disabled'}}
    else:
        band_med = (float(np.median(gray[band > 0]))
                    if cv2.countNonZero(band) else 0.0)
        band2, br_diag = bridge_edge_voids(
            band, gray, t_void, band_med,
            win_px=(bridge_win if bridge_win > 1 else 0))
        if br_diag.get('reason') == 'ok':
            band = band2
            solder_area = int(cv2.countNonZero(band))
            if br_diag.get('bridged_frac', 0) > 0.005:
                warnings.append(
                    f"桥接了贴边空洞缺口 {br_diag['bridged_frac'] * 100:.1f}% 面积"
                    f"（{br_diag.get('zones_bot', 0) + br_diag.get('zones_top', 0)} 处）")
        diag = {**(diag or {}), 'bridge': br_diag}

    # 空洞参数：面积下限默认按带面积自动定（不再受"点选尺寸"牵连）；
    # 深度容差 offset 正值 = 更包容（能把偏浅的暗斑也算作空洞）
    min_area_cfg = void_cfg.get('min_area')
    min_area_used = (int(min_area_cfg) if min_area_cfg else
                     auto_min_void_area(solder_area))
    max_area_cfg = void_cfg.get('max_area')
    max_area_used = (int(max_area_cfg) if max_area_cfg else
                     auto_max_void_area(solder_area))
    depth_off = float(void_cfg.get('depth_offset') or 0)
    t_void_used = float(t_void) + depth_off
    # 「快速设定」路径：空i洞阈值按**相对深度 Δ** 逐图自适应
    #   t_空洞 = 本图焊层带中位灰度 − Δ
    # 这样同一批里亮度不同的图都用同一个"比焊料暗多少"的标准，而不是固定的绝对灰度。
    if model.get('quick') and model.get('delta') is not None \
            and float(model.get('delta')) > 0:
        _bm = float(np.median(gray[band > 0])) if np.count_nonzero(band) else None
        if _bm is not None:
            t_void_used = _bm - float(model['delta']) + depth_off

    voids_all = detect_voids_in_band(
        gray, band, t_void_used,
        min_area=1,
        max_area=None,
        min_roundness=void_cfg.get('min_roundness') or 0.0)
    # 按面积下限/上限筛选，并重新编号（避免编号出现空洞）
    voids = [v for v in voids_all
             if v['area_px'] >= min_area_used and v['area_px'] <= max_area_used]
    for i, v in enumerate(voids, 1):
        v['id'] = i
    # 因面积下限/上限未计入的候选数（让"漏检"可见）
    below_min = sum(1 for v in voids_all if v['area_px'] < min_area_used)
    above_max = sum(1 for v in voids_all if v['area_px'] > max_area_used)
    void_area = float(sum(v['area_px'] for v in voids))
    return {
        'ok': True,
        'band_mask': band,
        'solder_area_px': solder_area,
        'voids': voids,
        'void_count': len(voids),
        'void_area_px': void_area,
        'void_rate': (void_area / solder_area) if solder_area else 0.0,
        'max_void_px': float(max((v['area_px'] for v in voids), default=0.0)),
        't_void_used': float(t_void_used),
        'min_area_used': int(min_area_used),
        'max_area_used': int(max_area_used),
        'below_min_area_count': int(below_min),
        'above_max_area_count': int(above_max),
        't_solder_used': float(t_used),
        'brightness_drift': round(drift, 3),
        'deviation': dev,
        'warnings': warnings,
        'diagnostics': diag,
    }


def locate_scale_bar(gray, template, scales=(0.5, 0.75, 1.0, 1.5, 2.0),
                     min_score=0.55):
    """多尺度模板匹配定位比例尺

    Returns:
        dict {score, x, y, w, h, scale} 或 None（分数不足）
    """
    if template is None or getattr(template, 'size', 0) == 0:
        return None
    H, W = gray.shape[:2]
    th0, tw0 = template.shape[:2]
    best = None
    for s in scales:
        tw, th = int(tw0 * s), int(th0 * s)
        if tw < 4 or th < 4 or tw > W or th > H:
            continue
        if abs(s - 1.0) < 1e-6:
            tpl = template
        else:
            interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_CUBIC
            tpl = cv2.resize(template, (tw, th), interpolation=interp)
        res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if best is None or mx > best['score']:
            best = {'score': float(mx), 'x': int(loc[0]), 'y': int(loc[1]),
                    'w': int(tw), 'h': int(th), 'scale': float(s)}
    if best is None or best['score'] < min_score:
        return None
    return best


def measure_bar_length(gray, x, y, w, h, horizontal=True, dark=True):
    """在比例尺 patch 内测量条棒像素长度（最长同色连续段）

    用 Otsu 分离条棒与背景——不用百分位数：条棒占比接近分位点时
    百分位会落进背景，导致量到整个 patch 宽度。
    """
    patch = gray[int(y):int(y) + int(h), int(x):int(x) + int(w)]
    if patch.size == 0:
        return None
    t = otsu_threshold(patch)
    if dark:
        m = (patch <= t).astype(np.uint8)
    else:
        m = (patch >= t).astype(np.uint8)
    if not horizontal:
        m = m.T
    best = 0
    for row in m:
        run = 0
        for v in row:
            run = run + 1 if v else 0
            if run > best:
                best = run
    return int(best) if best >= 3 else None


def _min_filter1d(a, k):
    if k <= 1:
        return np.asarray(a).copy()
    p = k // 2
    ap = np.pad(np.asarray(a), p, mode='edge')
    return np.lib.stride_tricks.sliding_window_view(ap, k).min(axis=1)


def _max_filter1d(a, k):
    if k <= 1:
        return np.asarray(a).copy()
    p = k // 2
    ap = np.pad(np.asarray(a), p, mode='edge')
    return np.lib.stride_tricks.sliding_window_view(ap, k).max(axis=1)


def bridge_edge_voids(band, gray, t_void, band_gray_med, win_px=0,
                      dark_ratio=0.5, max_comp_frac=0.02,
                      max_bridge_frac=0.05, min_run=5):
    """桥接"贴边空洞"造成的边界缺口（逐列包络 + 只跨暗缺口）

    问题：焊层带边界通常是材料界面（相对平缓），而贴到边界的空洞是暗的，
    会在边界上咬出缺口。缺口处面积被挖掉 → 空洞率的分母偏小、空洞率偏大，
    局部形状也失真。物理上空洞是焊料**内部**的孔，它占的位置应算作焊料。

    做法：
      1. 逐列取上下边界曲线；
      2. 下边界做一维闭运算（填谷）、上边界做一维开运算（削峰）得到"包络"——
         只桥接窄于 win_px 的缺口，其余保持原样；
      3. **只在缺口内像素确实是"暗且独立"时才接受桥接**：
         - 暗：灰度 < t_void + dark_ratio×(焊料亮度 − t_void)
         - 独立：这些暗像素的连通域不能很大——与下方基板连成一片的暗区
           属于"基板侵入/裂纹"，不能桥（否则把基板算成焊料）
      4. 太短的接受段（< min_run 列）当噪声丢弃；
      5. 桥接总面积超过 band 的 max_bridge_frac 时整体放弃（防误桥）。

    Returns:
        (new_band, diag)；未做任何桥接时返回原掩码
    """
    h, w = band.shape[:2]
    cols = np.arange(w)
    top = np.full(w, -1, np.int32)
    bot = np.full(w, -1, np.int32)
    for x in range(w):
        idx = np.nonzero(band[:, x])[0]
        if idx.size:
            top[x], bot[x] = int(idx[0]), int(idx[-1])
    valid = top >= 0
    if valid.sum() < 10:
        return band, {'bridged_px': 0, 'reason': 'band_empty'}
    x0 = int(np.argmax(valid))
    x1 = int(w - 1 - np.argmax(valid[::-1]))
    xs = np.arange(x0, x1 + 1)
    tv = np.interp(xs, cols[valid], top[valid]).round().astype(np.int32)
    bv = np.interp(xs, cols[valid], bot[valid]).round().astype(np.int32)
    xs_valid = valid[x0:x1 + 1]

    if not win_px or win_px <= 1:
        win_px = int(max(60, 0.12 * w))
    k = int(max(3, win_px) | 1)

    tv_open = _max_filter1d(_min_filter1d(tv, k), k)   # 削掉上边界的下凹
    bv_close = _min_filter1d(_max_filter1d(bv, k), k)  # 填掉下边界的上凹
    add_top = np.clip(tv_open - tv, 0, None)
    add_bot = np.clip(bv_close - bv, 0, None)

    # 暗且独立的判据
    dark_cut = float(t_void) + dark_ratio * max(float(band_gray_med) - float(t_void), 0.0)
    darks = (gray < dark_cut).astype(np.uint8)
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(darks)
    comp_area = stats[:, 4] if n_lab > 1 else np.zeros(1, np.int64)
    big_comp = np.zeros(n_lab, bool)
    big_comp[1:] = comp_area[1:] > (max_comp_frac * h * w)

    def _comp_ok(rows, x):
        """扩展段能不能接受桥接

        要求：① 段内暗像素占多数（说明缺口确实是被暗的东西咬出来的，
        而不是灰阶过渡带）；② 这些暗像素不属于"大暗区"（下方基板）。
        两者缺一不可——否则会把界面起伏或基板侵入一起桥掉。
        """
        seg = np.arange(rows.start, rows.stop)
        if seg.size == 0:
            return False
        lab = labels[rows, x]
        lab = lab[lab > 0]
        if lab.size == 0 or lab.size < 0.5 * seg.size:
            return False
        return not big_comp[lab].any()

    accept_top = np.zeros(len(xs), bool)
    accept_bot = np.zeros(len(xs), bool)
    for i, x in enumerate(xs):
        if not xs_valid[i]:
            continue
        if add_bot[i] > 0:
            accept_bot[i] = _comp_ok(slice(int(bv[i]), int(bv_close[i]) + 1), int(x))
        if add_top[i] > 0:
            accept_top[i] = _comp_ok(slice(int(tv_open[i]), int(tv[i]) + 1), int(x))

    def _drop_short(mask, m):
        if m < 2 or not mask.any():
            return mask
        out = mask.copy()
        i = 0
        n = len(out)
        while i < n:
            if not out[i]:
                i += 1
                continue
            j = i
            while j < n and out[j]:
                j += 1
            if j - i < m:
                out[i:j] = False
            i = j
        return out

    accept_top = _drop_short(accept_top, min_run)
    accept_bot = _drop_short(accept_bot, min_run)

    new = band.copy()
    for i, x in enumerate(xs):
        if not xs_valid[i]:
            continue
        y0 = int(tv_open[i]) if accept_top[i] else int(tv[i])
        y1 = int(bv_close[i]) if accept_bot[i] else int(bv[i])
        if y1 >= y0:
            new[y0:y1 + 1, x] = 255
    new = fill_holes(new)

    a0 = int(cv2.countNonZero(band))
    a1 = int(cv2.countNonZero(new))
    bridged = a1 - a0
    diag = {'bridged_px': int(bridged),
            'bridged_frac': round(bridged / a0, 4) if a0 else 0.0,
            'zones_top': int(np.count_nonzero(accept_top)),
            'zones_bot': int(np.count_nonzero(accept_bot)),
            'win_px': k}
    if bridged <= 0:
        return band, {**diag, 'reason': 'nothing_to_bridge'}
    if bridged > max_bridge_frac * a0:
        return band, {**diag, 'reason': 'bridge_too_large'}
    return new, {**diag, 'reason': 'ok'}


def auto_min_void_area(band_area_px):
    """空洞面积下限（自动档）：按焊层带面积尺度定，而不是按点选尺寸定

    原先取"0.5 × 点选的最小空洞面积"——但用户通常只点几个明显的大空洞，
    结果比它小的空洞全被排除；一旦换到空洞更小的子系列（或别的倍率），
    就成片漏检。改为按带面积定：0.02%，下限 12px²（约 4×4 像素，挡噪点）。
    """
    return int(max(12, round(float(band_area_px) * 0.0002)))


def auto_max_void_area(band_area_px):
    """空洞面积上限（自动档）：只作为"分割失败"的兜底，不是"点选过的最大"

    原先取"2 × 点选的最大空洞面积"——用户教的时候往往点几个小的，
    上限就压到了小空洞的量级，于是**最大的空洞反被排除**（实测：配方上限
    626px²，把 680/812px² 的纯黑大空洞全挡掉）。空洞大小本无上限，
    只保留一个物理常识兜底：单个空洞不可能超过焊层带面积的 30%。
    """
    return int(max(400, round(float(band_area_px) * 0.30)))


def make_thumb(img_bgr, band_mask, voids, target_h=46):
    """生成结果缩略图（供结果胶片条）：焊层淡绿 + 空洞红框，不带文字"""
    if img_bgr is None or band_mask is None:
        return None
    if img_bgr.ndim == 2:                       # 单通道灰度图要先转 BGR
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    h, w = img_bgr.shape[:2]
    s = target_h / float(max(h, 1))
    out = cv2.resize(img_bgr, (max(1, int(round(w * s))), target_h),
                     interpolation=cv2.INTER_AREA)
    mb = cv2.resize(band_mask, (out.shape[1], out.shape[0]),
                    interpolation=cv2.INTER_NEAREST)
    layer = out.copy()
    layer[mb > 0] = (0, 140, 0)
    out = cv2.addWeighted(layer, 0.42, out, 0.58, 0)
    for v in voids or []:
        x, y, ww, hh = v['rect']
        cv2.rectangle(out, (int(x * s), int(y * s)),
                      (max(int((x + ww) * s), int(x * s) + 2),
                       max(int((y + hh) * s), int(y * s) + 2)),
                      (0, 0, 220), 1)
    return out


def render_summary_sheet(entries, summary_lines, sheet_width=1600, gap=10,
                         layout='vertical', cols=2, tile_h=340, bg=None):
    """把所有图拼成"汇总大图"，顶部带汇总统计块

    Args:
        entries: [{'img','band_mask','voids','lines','warn'}...]
        summary_lines: 顶部汇总统计的文字行
        sheet_width: 纵向/网格模式下的整幅宽度（横向模式下用于封顶）
        gap: 图间空隙
        layout: 'vertical' 纵向堆叠 | 'horizontal' 横向排一行 | 'grid' 网格(cols 列)
        cols: 网格列数
        tile_h: 横向模式下统一高度
        bg: 间隙/表头/留白的背景灰度（None=沿用旧的浅灰235/白255；
            传入时表头仍是深底白字，浅灰会被替换成该灰度）
    Returns:
        np.ndarray: 汇总大图（BGR）
    """
    tiles = []
    warns = []
    for e in entries:
        img = e.get('img')
        if img is None:
            continue
        t = annotate_result(img, e['band_mask'], e.get('voids') or [],
                            lines=e.get('lines') or [])
        tiles.append((t, bool(e.get('warn'))))
    if not tiles:
        return None

    def _resize_w(t, w):
        h, ww = t.shape[:2]
        return cv2.resize(t, (w, max(1, int(round(h * (w / float(ww)))))),
                          interpolation=cv2.INTER_AREA)

    def _resize_h(t, hh):
        h, ww = t.shape[:2]
        return cv2.resize(t, (max(1, int(round(ww * (hh / float(h))))), hh),
                          interpolation=cv2.INTER_AREA)

    GAPC = np.full((gap, 1, 3), 235, np.uint8)

    if layout == 'horizontal':
        # 统一高度，横向排一行（宽图会变得很宽，超限则自动退回纵向）
        row = [_resize_h(t, tile_h) for t, _ in tiles]
        total_w = sum(r.shape[1] for r in row) + gap * (len(row) - 1)
        if total_w > 60000:
            layout = 'vertical'
            warns.append('横向总宽超过 60000px，已自动改用纵向堆叠')
        else:
            _bgc = 235 if bg is None else int(bg)
            parts = []
            for i, r in enumerate(row):
                if i:
                    parts.append(np.full((tile_h, gap, 3), _bgc, np.uint8))
                parts.append(r)
            body = np.hstack(parts)
            if any(w for _, w in tiles):
                cv2.rectangle(body, (0, 0), (body.shape[1] - 1, body.shape[0] - 1),
                              (0, 0, 220), 3)
            sheet_w = body.shape[1]

    elif layout == 'grid':
        cols = max(1, int(cols))
        cell_w = (sheet_width - gap * (cols - 1)) // cols
        cells = []
        for t, w in tiles:
            c = _resize_w(t, cell_w)
            if w:
                cv2.rectangle(c, (0, 0), (c.shape[1] - 1, c.shape[0] - 1),
                              (0, 0, 220), 3)
            cells.append(c)
        rows = []
        for i in range(0, len(cells), cols):
            grp = cells[i:i + cols]
            grp += [np.full_like(grp[0], 235)] * (cols - len(grp))
            rows.append(np.hstack([x for j, x in enumerate(grp)
                                   if j == 0] + sum(
                [[np.full((x.shape[0], gap, 3), 235, np.uint8), x]
                 for x in grp[1:]], [])))
        # 各行高度不一，补背景后纵向拼
        max_w = max(r.shape[1] for r in rows)
        rows = [np.hstack([r, np.full((r.shape[0], max_w - r.shape[1], 3),
                                      235, np.uint8)]) for r in rows]
        body = np.vstack(sum([[r, np.full((gap, max_w, 3), 235, np.uint8)]
                              for r in rows], [])[:-1])
        sheet_w = max_w

    if layout == 'vertical':
        parts = []
        for t, w in tiles:
            r = _resize_w(t, sheet_width)
            if w:
                cv2.rectangle(r, (0, 0), (r.shape[1] - 1, r.shape[0] - 1),
                              (0, 0, 220), 3)
            parts.append(r)
            parts.append(np.full((gap, sheet_width, 3), 235, np.uint8))
        body = np.vstack(parts[:-1]) if parts else None
        sheet_w = sheet_width

    if body is None:
        return None
    # 顶部汇总块（宽度对齐最终画布）
    out = []
    if summary_lines:
        lh = 10 + (18 + 7) * len(summary_lines)
        _hbg = 255 if bg is None else int(bg)
        header = np.full((lh, sheet_w, 3), _hbg, np.uint8)
        header = _draw_text_block(header, summary_lines, font_size=18)
        out.append(header)
        out.append(np.full((gap, sheet_w, 3), 235 if bg is None else int(bg),
                           np.uint8))
    if body.shape[1] != sheet_w:
        pad = np.full((body.shape[0], sheet_w - body.shape[1], 3), 235, np.uint8)
        body = np.hstack([body, pad]) if sheet_w > body.shape[1] else body
    out.append(body)
    return np.vstack(out)


def crop_solder_region(img_bgr, band_mask, voids=None, pad=0, bg=(0, 0, 0)):
    """把原图裁剪到金锡（焊层带）区域的外接矩形

    区域外的像素一律填 bg（默认黑——金锡多为浅色，黑底出图更清晰），
    空洞沿用现有的红色掩膜填充形式叠加。

    Returns:
        np.ndarray: 抠出的金锡区域图（BGR）；无有效区域时返回 None
    """
    if img_bgr is None or band_mask is None:
        return None
    if img_bgr.ndim == 2:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    ys, xs = np.where(band_mask > 0)
    if len(xs) == 0:
        return None
    h, w = img_bgr.shape[:2]
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(w - 1, int(xs.max()) + pad)
    y1 = min(h - 1, int(ys.max()) + pad)
    crop = img_bgr[y0:y1 + 1, x0:x1 + 1]
    m = band_mask[y0:y1 + 1, x0:x1 + 1]
    out = np.zeros_like(crop)
    if tuple(bg) != (0, 0, 0):
        out[:] = bg
    sel = m > 0
    out[sel] = crop[sel]
    # 空洞红填充（与 annotate_result 同一套画法：整层叠加一次）
    if voids:
        void_layer = out.copy()
        for v in voids:
            pts = np.array(v['points'], dtype=np.int32).copy()
            pts[:, 0] -= x0
            pts[:, 1] -= y0
            cv2.fillPoly(void_layer, [pts], (0, 0, 220))
        out = cv2.addWeighted(void_layer, 0.40, out, 0.60, 0)
    return out


def render_solder_strip(entries, header_lines, gap=0, tile_h=None,
                        bg=(64, 64, 64), max_width=60000):
    """把每张图的金锡部分抠图后，按顺序横向拼接成一张大图

    Args:
        entries: [{'img','band_mask','voids'}...]（按检测顺序）
        header_lines: 大图左上角标注文字（与汇总大图一致）
        gap: 图间空隙（**默认 0 = 无缝衔接** ✗ 相邻金锡抠图紧贴）
        tile_h: 统一高度；None 时按最高者对齐，其余居中以 bg 补空
        bg: 空白填充色（**默认深灰 64**；原来纯黑，按需求改深灰 ✔）
        max_width: 总宽上限，超出则整体等比缩小
    Returns:
        np.ndarray: 横向拼接大图（BGR）；无有效图时返回 None
    """
    crops = []
    for e in entries:
        c = crop_solder_region(e.get('img'), e.get('band_mask'),
                               e.get('voids') or [], bg=bg)
        if c is not None and c.size:
            crops.append(c)
    if not crops:
        return None
    if tile_h:
        crops = [cv2.resize(
            c, (max(1, int(round(c.shape[1] * tile_h / c.shape[0]))), tile_h),
            interpolation=cv2.INTER_AREA) for c in crops]
        H = tile_h
    else:
        H = max(c.shape[0] for c in crops)
    parts = []
    for i, c in enumerate(crops):
        if c.shape[0] != H:                      # 居中补空
            top = (H - c.shape[0]) // 2
            bot = H - c.shape[0] - top
            c = np.vstack([np.full((top, c.shape[1], 3), bg, np.uint8), c,
                           np.full((bot, c.shape[1], 3), bg, np.uint8)])
        if i:
            parts.append(np.full((H, gap, 3), bg, np.uint8))
        parts.append(c)
    body = np.hstack(parts)
    if body.shape[1] > max_width:                # 超宽整体等比缩小
        s = max_width / body.shape[1]
        body = cv2.resize(body, (max_width, max(1, int(round(body.shape[0] * s)))),
                          interpolation=cv2.INTER_AREA)
    if not header_lines:
        return body
    # 左上角标注：顶部黑色文字条（不遮挡金锡抠图）
    lh = 10 + (18 + 7) * len(header_lines)
    header = np.zeros((lh, body.shape[1], 3), np.uint8)
    header = _draw_text_block(header, header_lines, font_size=18)
    return np.vstack([header, np.full((gap, body.shape[1], 3), bg, np.uint8), body])


def read_scale_bar(gray, template, model_bar, fallback_px_per_um=0.0):
    """批量图中自动识别比例尺并计算 px/μm

    带合理性校验：期望长度 = 示范长度 × 模板命中缩放，实测须落在其
    0.6~1.6 倍内（留条棒端点/抗锯齿的测量误差余量）。超出即判定模板误命中
    （例如匹配到纹理，最长同色段量到整片背景），退回示范值并在 info 里给出
    原因——比例尺测错的代价是 μm² 成倍偏差，宁可不自动。
    多尺度匹配本身覆盖 0.5~2 倍倍率变化；更大倍率差异匹配不上，
    走 found=False 分支同样退回示范值。

    Returns:
        (px_per_um, info)；失败/存疑时退回 fallback 并在 info 标注原因
    """
    loc = locate_scale_bar(gray, template)
    if loc is None:
        return fallback_px_per_um, {'found': False}
    length = measure_bar_length(gray, loc['x'], loc['y'], loc['w'], loc['h'],
                                horizontal=model_bar.get('horizontal', True),
                                dark=model_bar.get('dark', True))
    real_um = model_bar.get('real_um') or 0.0
    if not length or real_um <= 0:
        return fallback_px_per_um, {'found': True, 'score': loc['score'],
                                    'length_px': length,
                                    'reason': 'length_measure_failed'}
    taught_len = float(model_bar.get('length_px') or 0.0)
    matched_scale = float(loc.get('scale') or 1.0)
    if taught_len > 0:
        expected = taught_len * matched_scale
        if not (0.6 * expected <= length <= 1.6 * expected):
            return fallback_px_per_um, {'found': True, 'score': loc['score'],
                                        'length_px': length,
                                        'taught_px': taught_len,
                                        'match_scale': matched_scale,
                                        'reason': 'length_implausible'}
    return (length / real_um,
            {'found': True, 'score': loc['score'],
             'length_px': length, 'scale': matched_scale})


def _draw_text_block(bgr, lines, font_size=15):
    """在图像左上角画半透明多行文字块（支持中文）

    cv2.putText 只支持 ASCII（中文会变方块），故用 PIL + 系统字体；
    PIL/字体不可用时退回 cv2.putText（此时中文不可读，但不影响图像标注）。
    """
    if not lines:
        return bgr
    line_h = font_size + 6
    hh = min(bgr.shape[0], 8 + line_h * len(lines))
    try:
        from PIL import Image, ImageDraw, ImageFont
        font = None
        for fp in (r"C:\Windows\Fonts\msyh.ttc",
                   r"C:\Windows\Fonts\simhei.ttf",
                   r"C:\Windows\Fonts\simsun.ttc"):
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, font_size)
                break
        if font is None:
            font = ImageFont.load_default()
        img = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).convert('RGBA')
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle([0, 0, img.size[0], hh],
                                          fill=(25, 25, 25, 185))
        img = Image.alpha_composite(img, overlay).convert('RGB')
        draw = ImageDraw.Draw(img)
        for i, ln in enumerate(lines):
            draw.text((6, 4 + i * line_h), str(ln), fill=(255, 255, 255), font=font)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    except Exception:
        out = bgr.copy()
        cv2.rectangle(out, (0, 0), (out.shape[1], hh), (25, 25, 25), -1)
        for i, ln in enumerate(lines):
            cv2.putText(out, str(ln).encode('ascii', 'replace').decode(),
                        (6, 15 + i * line_h), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (255, 255, 255), 1, cv2.LINE_AA)
        return out


def annotate_result(img_bgr, band_mask, voids, lines=None):
    """把焊层带 + 空洞 + 指标文字画到图上（导出标注图用）

    画法：焊层带淡绿填充（可看清测的是哪块面积）→ 空洞红填充 →
    焊层带绿描边 → 空洞编号 → 半透明文字块（支持中文，不遮挡图像内容）。

    Args:
        img_bgr: 原图（BGR 或灰度）
        band_mask: 焊层带掩码
        voids: 空洞列表（detect_voids_in_band 的 schema）
        lines: 左上角文字行列表
    Returns:
        np.ndarray: BGR 标注图
    """
    if img_bgr.ndim == 2:
        out = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    else:
        out = img_bgr.copy()
    cnts, _ = cv2.findContours(band_mask, cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    # 焊层带淡绿填充
    band_layer = out.copy()
    cv2.drawContours(band_layer, cnts, -1, (0, 140, 0), -1)
    out = cv2.addWeighted(band_layer, 0.18, out, 0.82, 0)
    # 空洞红填充
    void_layer = out.copy()
    for v in voids:
        cv2.fillPoly(void_layer, [np.array(v['points'], dtype=np.int32)], (0, 0, 220))
    out = cv2.addWeighted(void_layer, 0.40, out, 0.60, 0)
    # 焊层带描边 + 空洞编号
    cv2.drawContours(out, cnts, -1, (0, 140, 0), max(1, out.shape[0] // 400))
    for v in voids:
        cv2.putText(out, str(v['id']), (int(v['cx']) - 5, int(v['cy']) + 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
    return _draw_text_block(out, lines)