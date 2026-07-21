"""图像处理工具函数"""

import cv2
import numpy as np
from PyQt6.QtWidgets import QApplication


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
            QApplication.processEvents()
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
            QApplication.processEvents()
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
            QApplication.processEvents()
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