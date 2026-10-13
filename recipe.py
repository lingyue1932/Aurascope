"""检测配方管理 — 保存/加载空洞分析参数与 ROI

配方为 JSON 文件，默认存储于 <app_dir>/recipes/ 目录（frozen 后取 exe 同级）。
本模块不依赖 Qt，可独立单测；可用环境变量 AURASCOPE_RECIPE_DIR 覆盖存储目录。

字段语义注意：
- calibration 存的是 px_per_um（像素/微米），与 main_window.pixel_scale 一致，
  即 finish_calibration 里的 dist_px / real_len_um。
"""

import json
import os
import re
import sys
from datetime import datetime

import cv2
import numpy as np

SCHEMA_VERSION = 1

# 检测参数默认值（与 main_window「恢复默认设置」保持一致）
DETECTION_DEFAULTS = {
    'threshold': 80,
    'min_area': 1,
    'max_area': None,
    'roi_erosion_px': 3,
    'enhanced': True,
    'clahe_enabled': True,
    'clahe_clip_limit': 2.0,
    'morph_enabled': True,
    'morph_kernel': 3,        # UI 未暴露，固定默认
    'min_roundness': 0.0,
    'edge_verify': False,
    'edge_thresh': 0.3,       # UI 未暴露，固定默认
}

# 数值参数合法范围（加载时夹紧，防止手改 JSON 出错）
_RANGES = {
    'threshold': (0, 255),
    'min_area': (0, 10_000_000),
    'roi_erosion_px': (0, 20),
    'clahe_clip_limit': (1.0, 4.0),
    'min_roundness': (0.0, 1.0),
    'edge_thresh': (0.0, 1.0),
    'morph_kernel': (1, 15),
}

_BOOL_KEYS = ('enhanced', 'clahe_enabled', 'morph_enabled', 'edge_verify')
_FLOAT_KEYS = ('clahe_clip_limit', 'min_roundness', 'edge_thresh')


def _recipe_root():
    """配方存储根目录（可用环境变量覆盖，测试用）"""
    env = os.environ.get('AURASCOPE_RECIPE_DIR')
    if env:
        return os.path.abspath(env)
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'recipes')


def recipe_dir():
    """确保并返回配方目录"""
    path = _recipe_root()
    os.makedirs(path, exist_ok=True)
    return path


def safe_name(name):
    """过滤非法文件名字符，限制长度"""
    name = (name or '').strip()
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    return name[:64]


def recipe_filename(name):
    """显示名 → 文件名"""
    return safe_name(name) + '.json'


def _path_for(name):
    return os.path.join(recipe_dir(), recipe_filename(name))


def _taught_path_for(name):
    """示教配方文件名带 .taught 后缀，与参数型（v1）配方隔离命名空间

    否则同名时两类配方会互相覆盖（共用同一命名规则）。
    """
    return os.path.join(recipe_dir(), safe_name(name) + '.taught.json')


def _resolve_path(name_or_filename):
    """把显示名或文件名解析为实际路径，兼容 v1 与 taught 两种命名"""
    fn = name_or_filename or ''
    d = recipe_dir()
    if fn.endswith('.json'):
        return os.path.join(d, fn)
    base = safe_name(fn)
    for cand in (base + '.json', base + '.taught.json'):
        p = os.path.join(d, cand)
        if os.path.isfile(p):
            return p
    return os.path.join(d, base + '.json')


def list_recipes(kind=None):
    """返回 [(显示名, 文件名)]，按修改时间倒序（新的在前）

    kind: 'v1' 只要参数型配方；'taught' 只要示教模型；None 全部。
    读取失败的文件按 v1 处理（让用户能在界面上看到并删除）。
    """
    out = []
    d = recipe_dir()
    try:
        files = os.listdir(d)
    except OSError:
        return out
    for fn in files:
        if not fn.lower().endswith('.json'):
            continue
        full = os.path.join(d, fn)
        try:
            with open(full, 'r', encoding='utf-8') as f:
                data = json.load(f)
            disp = data.get('name') or os.path.splitext(fn)[0]
            rtype = data.get('type')
        except Exception:
            disp, rtype = os.path.splitext(fn)[0], None
        if kind == 'taught' and rtype != 'taught':
            continue
        if kind == 'v1' and rtype == 'taught':
            continue
        out.append((disp, fn))
    out.sort(key=lambda t: os.path.getmtime(os.path.join(d, t[1])), reverse=True)
    return out


def validate_detection(det):
    """校验并夹紧检测参数，补默认值"""
    merged = dict(DETECTION_DEFAULTS)
    for k, v in (det or {}).items():
        if k in merged:
            merged[k] = v
    out = {}
    for k, v in merged.items():
        if k == 'max_area':
            # 0 / None / 缺失都表示无上限
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = 0
            out[k] = v if v > 0 else None
            continue
        if k in _BOOL_KEYS:
            out[k] = bool(v)
        elif k in _FLOAT_KEYS:
            v = float(v)
            lo, hi = _RANGES[k]
            out[k] = round(max(lo, min(hi, v)), 4)
        else:
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = DETECTION_DEFAULTS[k]
            if k in _RANGES:
                lo, hi = _RANGES[k]
                v = max(lo, min(hi, v))
            out[k] = v
    return out


def validate_roi(roi):
    """校验 ROI，清洗多边形顶点"""
    roi = roi or {}
    clean = []
    for p in roi.get('polygon') or []:
        try:
            clean.append([round(float(p[0]), 1), round(float(p[1]), 1)])
        except (TypeError, ValueError, IndexError):
            continue
    try:
        layer_th = int(roi.get('layer_threshold', 100))
    except (TypeError, ValueError):
        layer_th = 100
    try:
        vertices = int(roi.get('vertices', 24))
    except (TypeError, ValueError):
        vertices = 24
    return {
        'type': 'polygon' if len(clean) >= 3 else 'none',
        'polygon': clean,
        'layer_threshold': max(0, min(255, layer_th)),
        'vertices': max(3, min(120, vertices)),
    }


def build_recipe(name, detection, roi, px_per_um=0.0, note=''):
    """组装配方字典（自动补默认值并校验）"""
    return {
        'schema_version': SCHEMA_VERSION,
        'name': (name or '').strip(),
        'note': note or '',
        'updated': datetime.now().isoformat(timespec='seconds'),
        'detection': validate_detection(detection),
        'roi': validate_roi(roi),
        'px_per_um': float(px_per_um or 0.0),
    }


def normalize_recipe(data):
    """把任意来源的字典规范化为完整配方；非法输入返回 None

    type=taught（示教模型，schema v2）走 validate_taught；其余按 v1 参数型处理。
    """
    if not isinstance(data, dict):
        return None
    if data.get('type') == 'taught':
        return validate_taught(data)
    return {
        'schema_version': data.get('schema_version', SCHEMA_VERSION),
        'name': data.get('name') or '',
        'note': data.get('note') or '',
        'updated': data.get('updated') or '',
        'detection': validate_detection(data.get('detection')),
        'roi': validate_roi(data.get('roi')),
        'px_per_um': _to_float(data.get('px_per_um'), 0.0),
    }


# ---------- 示教模型（schema v2, type=taught） ----------

def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def validate_taught(model):
    """校验示教模型，补默认值；非法输入返回 None"""
    if not isinstance(model, dict):
        return None
    solder = model.get('solder') or {}
    bg = model.get('background') or {}
    void = model.get('void') or {}
    band = model.get('band') or {}
    bar = model.get('scale_bar') or {}
    diag = model.get('diagnostics') or {}

    t_void = void.get('threshold')
    if t_void is not None:
        t_void = _clamp(t_void, 0, 255, None)
    max_area = void.get('max_area')
    try:
        max_area = int(max_area) if max_area and int(max_area) > 0 else None
    except (TypeError, ValueError):
        max_area = None

    return {
        'schema_version': 2,
        'type': 'taught',
        'name': (model.get('name') or '').strip(),
        'note': model.get('note') or '',
        'updated': model.get('updated') or '',
        'solder': {
            'median': _clamp(solder.get('median'), 0, 255, 128.0),
            'std': _clamp(solder.get('std'), 0, 255, 0.0),
            'p5': _clamp(solder.get('p5'), 0, 255, 0.0),
            'p95': _clamp(solder.get('p95'), 0, 255, 255.0),
            'threshold': _clamp(solder.get('threshold'), 0, 255, 128.0),
        },
        'background': {
            'median': _clamp(bg.get('median'), 0, 255, 128.0),
            'std': _clamp(bg.get('std'), 0, 255, 0.0),
        },
        'void': {
            'threshold': t_void,
            'min_area': max(0, int(_clamp(void.get('min_area'), 0, 10 ** 7, 1))),
            'max_area': max_area,
            'min_roundness': _clamp(void.get('min_roundness'), 0, 1, 0.0),
            'taught_count': max(0, int(_clamp(void.get('taught_count'), 0, 9999, 0))),
            'median': _clamp(void.get('median'), 0, 255, None) if void.get('median') is not None else None,
        },
        'px_per_um': _to_float(model.get('px_per_um'), 0.0),
        'ref_median': _clamp(model.get('ref_median'), 0, 255, 0.0),
        'band': {
            'min_aspect': _clamp(band.get('min_aspect'), 1.0, 50.0, 3.0),
            'min_area_frac': _clamp(band.get('min_area_frac'), 0.0, 1.0, 0.01),
            'open_kernel': max(1, int(_clamp(band.get('open_kernel'), 1, 21, 5))),
            # 竖向最小厚度（px）：剔除挂在本体上的薄碎片；0 = 关闭
            'min_thickness_px': max(0, int(_clamp(band.get('min_thickness_px'), 0, 60, 8))),
            # 贴边空洞缺口桥接窗口（px）：-1/缺省 = 自动（图宽 12%，最小 60）；
            # 0 = 关闭桥接；>1 = 指定窗口宽度
            'bridge_win_px': int(_clamp(band.get('bridge_win_px'), -1, 2000, -1)),
        },
        'band_ref': _validate_band_ref(model.get('band_ref')),
        'band_tol': _validate_band_tol(model.get('band_tol')),
        'scale_bar': {
            'horizontal': bool(bar.get('horizontal', True)),
            'dark': bool(bar.get('dark', True)),
            'length_px': _to_float(bar.get('length_px'), 0.0),
            'real_um': _to_float(bar.get('real_um'), 0.0),
        },
        'diagnostics': {
            'solder_bg_separability': _to_float(diag.get('solder_bg_separability'), 0.0),
            'solder_void_separability': _to_float(diag.get('solder_void_separability'), 0.0),
        },
    }


def _bar_template_path(name):
    return os.path.join(recipe_dir(), safe_name(name) + '_bar.png')


def _validate_band_ref(ref):
    """示教模板的焊层几何基准（缺失时返回 None，批量不做偏差校验）"""
    if not isinstance(ref, dict):
        return None
    keys = ('cx_norm', 'cy_norm', 'w_norm', 'h_norm', 'area_frac', 'aspect')
    out = {}
    for k in keys:
        if k not in ref:
            return None
        try:
            out[k] = round(float(ref[k]), 5)
        except (TypeError, ValueError):
            return None
    return out


def _validate_band_tol(tol):
    """偏差阈值（可手改 JSON 收紧/放宽）"""
    d = {'center_shift': 0.15, 'area_lo': 0.4, 'area_hi': 2.5,
         'aspect_lo': 0.5, 'aspect_hi': 2.0}
    if isinstance(tol, dict):
        for k in d:
            if k in tol:
                try:
                    d[k] = float(tol[k])
                except (TypeError, ValueError):
                    pass
    return d


def save_taught(model, bar_template=None):
    """保存示教模型（文件名带 .taught 后缀，与参数配方隔离）

    注意：cv2.imwrite 在 Windows 上不支持非 ASCII 路径（静默失败），
    这里走 imencode + Python 文件写入。
    """
    name = safe_name(model.get('name') or '')
    if not name:
        raise ValueError('配方名不能为空')
    path = _taught_path_for(name)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(model, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    if bar_template is not None:
        ok, buf = cv2.imencode('.png', bar_template)
        if ok:
            with open(_bar_template_path(name), 'wb') as f:
                f.write(buf.tobytes())
    return path


def load_bar_template(name_or_filename):
    """加载示教模型配套的比例尺模板图；不存在返回 None

    接受显示名、`<名>.json`、`<名>.taught.json` 三类入参——
    剥后缀时必须先剥 `.taught.json`，否则残留的 `.taught` 会拼出错误的文件名。
    同样绕开 cv2.imread 的中文路径问题：读字节 → imdecode。
    """
    fn = name_or_filename or ''
    if fn.endswith('.taught.json'):
        fn = fn[:-len('.taught.json')]
    elif fn.endswith('.json'):
        fn = fn[:-len('.json')]
    if not fn.endswith('_bar.png'):
        fn = safe_name(fn)
    path = _bar_template_path(fn)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'rb') as f:
            data = np.frombuffer(f.read(), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    except Exception:
        return None


def _to_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def save_recipe(recipe):
    """保存配方（先写临时文件再原子替换，避免写一半损坏）"""
    name = safe_name(recipe.get('name') or '')
    if not name:
        raise ValueError('配方名不能为空')
    path = _path_for(name)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(recipe, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def load_recipe(name_or_filename):
    """按显示名或文件名加载，返回规范化配方；失败返回 None"""
    path = _resolve_path(name_or_filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None
    return normalize_recipe(data)


def delete_recipe(name_or_filename):
    """删除配方，返回是否删除成功"""
    path = _resolve_path(name_or_filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return False
