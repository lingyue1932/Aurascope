"""CSV 导出：用标准库 csv 替代 pandas，只为写表 + 行的几处调用。

等价点：
- 编码统一 utf-8-sig（Excel 双击不乱码）；
- 列名按首次出现顺序合并，不同行键集不同也不丢列（等价 pandas 的列对齐）；
- 缺失字段写空串，不做 NaN；
- 先写同目录临时文件再 os.replace，避免中途失败留下半截文件。
"""

import csv
import os
import tempfile


def collect_headers(rows):
    """按首次出现顺序收集列名——各行键集不同时仍保留全部列。"""
    headers = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                headers.append(key)
    return headers


def write_csv(path, rows, headers=None):
    """把 [{列: 值}] 写成 CSV，返回写入行数。"""
    rows = list(rows)
    headers = list(headers) if headers is not None else collect_headers(rows)
    directory = os.path.dirname(os.path.abspath(path)) or '.'
    handle, temp_path = tempfile.mkstemp(
        prefix='.csv_', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8-sig', newline='') as stream:
            if not headers:
                return 0
            writer = csv.DictWriter(stream, fieldnames=headers,
                                    extrasaction='ignore')
            writer.writeheader()
            for row in rows:
                writer.writerow({key: '' if row.get(key) is None else row[key]
                                 for key in headers})
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
    return len(rows)
