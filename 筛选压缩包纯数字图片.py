# -*- coding: utf-8 -*-
"""从压缩包里筛出「纯数字编号」的图片

用途
----
拿到一批拍摄/切片压缩包（如 XC20260831022 刘道应.zip），里面的结构形如：
    XC20260831022 刘道应/切片/315/1/1.jpg、2.jpg、3.jpg … 10.jpg、10-1.jpg …
                                            └─ 只要纯数字的，10-1.jpg 这种不要
本脚本自动解压 → 找到「最后一排子文件夹」（没有下级目录的叶子文件夹）→ 把其中
文件名主干是纯数字的图片复制出来，按来源文件夹命名归到一个 _筛选 目录下：
    D:\\feishu\\_筛选\\315_1\\1.jpg、2.jpg …
    D:\\feishu\\_筛选\\325_1\\1.jpg、2.jpg …

用法
----
1) 直接运行（弹窗选压缩包，可多选）：
       python 筛选压缩包纯数字图片.py
2) 命令行：
       python 筛选压缩包纯数字图片.py "D:\\feishu\\XC20260831022 刘道应.zip"
       python 筛选压缩包纯数字图片.py a.zip b.zip --out D:\\结果
       python 筛选压缩包纯数字图片.py a.zip --dry-run      # 只看会筛出什么，不落地

说明
----
· 只认标准 .zip；.7z/.rar 需要额外库，暂不支持（需要可以再加）
· 叶子文件夹重名（如 切片/315/1 与 切片/325/1 都叫 1）时，自动用"上级_名字"
  区分成 315_1、325_1；仍冲突则再加序号
· 解压用临时目录，处理完自动删除（--keep-temp 可保留）
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.gif'}
NUM_RE = re.compile(r'^\d+$')          # 文件名主干必须全是数字
SELECT_DIR_NAME = '_筛选'              # 输出的一级目录名


# ---------------------------------------------------------------- 压缩包读取

def zip_entry_name(info):
    """取 zip 条目的真实文件名（兼容中文乱码）

    中文 Windows 打的包常常没置 UTF-8 标志位，zipfile 会按 CP437 解出乱码，
    这里再按 GBK 还原一次。
    """
    name = info.filename
    if info.flag_bits & 0x800:      # 已标 UTF-8，直接用
        return name
    try:
        return name.encode('cp437').decode('gbk')
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            return name.encode('cp437').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            return name


def safe_rel_parts(name):
    """把 zip 内的路径拆成安全的分段（防目录穿越 / 绝对路径）"""
    name = name.replace('\\', '/')
    parts = []
    for seg in name.split('/'):
        seg = seg.strip()
        if not seg or seg in ('.', '..'):
            continue
        seg = re.sub(r'[<>:"|?*\x00-\x1f]', '_', seg)   # 去掉 Windows 非法字符
        parts.append(seg)
    return parts


def extract_zip(zip_path, dest_dir, log=print):
    """解压到 dest_dir（自己按修好的名字逐个写，避免乱码与穿越）"""
    ok = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            parts = safe_rel_parts(zip_entry_name(info))
            if not parts:
                continue
            target = os.path.join(dest_dir, *parts)
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target) or dest_dir, exist_ok=True)
            with z.open(info) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            ok += 1
    log(f'  解压 {ok} 个文件')
    return ok


# ---------------------------------------------------------------- 目录与筛选

def find_leaf_dirs(root):
    """找「最后一排子文件夹」：内部不再含子目录的目录"""
    leaves = []
    for cur, dirs, _files in os.walk(root):
        if not dirs:                       # 没有下级目录 = 叶子
            leaves.append(cur)
    return leaves


def pick_numeric_images(dir_path):
    """取该目录下主干为纯数字的图片，按数字顺序返回 [(数字, 文件名)]"""
    out = []
    try:
        names = os.listdir(dir_path)
    except OSError:
        return out
    for fn in names:
        stem, ext = os.path.splitext(fn)
        if ext.lower() not in IMAGE_EXTS:
            continue
        if not NUM_RE.match(stem):          # 10-1、A、2026-09-08-18-42-33 都排除
            continue
        if not os.path.isfile(os.path.join(dir_path, fn)):
            continue
        out.append((int(stem), fn))
    out.sort(key=lambda t: t[0])
    return out


def build_out_names(leaves_info, temp_root, zip_stem):
    """给每个叶子目录定一个输出文件夹名

    leaves_info: [(叶子绝对路径, [图片...]), ...]（已确保有图）
    规则：名字唯一就用原名；重名 → 用「上级_名字」；仍重名 → 再加 _2、_3…
          若"叶子"就是解压根目录（包内没有子目录），用压缩包名当文件夹名。
    """
    from collections import Counter
    base = []
    for p, _ in leaves_info:
        b = os.path.basename(p)
        if os.path.normpath(p) == os.path.normpath(temp_root):
            b = zip_stem                     # 包内没有子目录：用压缩包名
        base.append(b)
    dup = {b for b, c in Counter(base).items() if c > 1}
    used, mapping = set(), []
    for (path, imgs), b in zip(leaves_info, base):
        cand = b
        if b in dup:
            parent = os.path.basename(os.path.dirname(path)) or '根'
            cand = f'{parent}_{b}'
        name, i = cand, 2
        while name in used:                 # 兜底去重
            name, i = f'{cand}_{i}', i + 1
        used.add(name)
        mapping.append((path, name, imgs))
    return mapping


# ---------------------------------------------------------------- 主流程

def process_zip(zip_path, out_root, dry_run=False, keep_temp=False, log=print):
    """处理一个压缩包，返回 (复制的图片数, 生成的文件夹数)"""
    if not os.path.isfile(zip_path):
        log(f'× 文件不存在：{zip_path}')
        return 0, 0
    if not zipfile.is_zipfile(zip_path):
        log(f'× 不是有效的 zip：{os.path.basename(zip_path)}'
            f'（.7z/.rar 需要额外库，暂不支持）')
        return 0, 0

    tpl_name = os.path.basename(zip_path)
    log(f'\n【{tpl_name}】')
    try:
        temp_root = tempfile.mkdtemp(
            prefix='._筛选临时_',
            dir=os.path.dirname(os.path.abspath(zip_path)))
    except OSError:
        temp_root = tempfile.mkdtemp(prefix='._筛选临时_')   # 同级不可写就退回系统临时
    try:
        extract_zip(zip_path, temp_root, log=log)

        leaves = find_leaf_dirs(temp_root)
        # 只保留"有纯数字图片"的叶子目录
        leaves_info = []
        for d in leaves:
            imgs = pick_numeric_images(d)
            if imgs:
                leaves_info.append((d, imgs))
        if not leaves_info:
            log('  × 没找到含纯数字编号图片的叶子文件夹')
            return 0, 0

        plan = build_out_names(leaves_info, temp_root,
                              os.path.splitext(tpl_name)[0])
        total = 0
        made = 0
        for src_dir, out_name, imgs in plan:
            rel = os.path.relpath(src_dir, temp_root).replace('\\', '/')
            dst_dir = os.path.join(out_root, out_name)
            if not dry_run:
                os.makedirs(dst_dir, exist_ok=True)
            made += 1
            log(f'  {rel}/  →  {SELECT_DIR_NAME}/{out_name}/   {len(imgs)} 张：'
                + ', '.join(fn for _, fn in imgs[:8])
                + (' …' if len(imgs) > 8 else ''))
            if dry_run:
                total += len(imgs)
                continue
            for _, fn in imgs:
                try:
                    shutil.copy2(os.path.join(src_dir, fn),
                                 os.path.join(dst_dir, fn))
                    total += 1
                except OSError as e:
                    log(f'    × 复制失败 {fn}：{e}')
        log(f'  小结：{made} 个文件夹，共 {total} 张图'
            + ('（dry-run，未落地）' if dry_run else ''))
        return total, made
    finally:
        if keep_temp:
            log(f'  临时目录保留在：{temp_root}')
        else:
            force_rmtree(temp_root, log=log)


def force_rmtree(path, log=print):
    """删除整棵目录树，能处理只读/隐藏文件

    压缩包里常有 Thumbs.db（Windows 会给它隐藏+只读属性），直接 rmtree 会
    报 PermissionError——所以先清属性再删；删不掉要如实报出来，不能静默吞掉。
    """
    import stat as _stat

    def _fix(func, p, _exc):
        try:
            os.chmod(p, _stat.S_IWRITE | _stat.S_IREAD)
            func(p)
        except Exception:
            pass

    try:
        shutil.rmtree(path, onexc=_fix)          # Python 3.12+
    except TypeError:
        shutil.rmtree(path, onerror=_fix)        # 老版本
    except Exception as e:
        log(f'  ⚠ 临时目录没能完全删除：{path}（{e}）')
        return False
    if os.path.exists(path):
        log(f'  ⚠ 临时目录仍有残留，可手动删除：{path}')
        return False
    return True


def pick_zips_by_dialog():
    """弹窗让用户选压缩包（支持多选）"""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except Exception as e:
        print(f'无法打开选择窗口（{e}），请在命令行里把压缩包路径作为参数传入。')
        return []
    root = tk.Tk()
    root.withdraw()
    root.update()
    files = filedialog.askopenfilenames(
        title='选择要筛选的压缩包（可多选）',
        filetypes=[('压缩包', '*.zip'), ('所有文件', '*.*')])
    if not files:
        return []
    # 再确认一次输出位置（默认在压缩包同级建 _筛选）
    first = files[0]
    default_out = os.path.join(os.path.dirname(os.path.abspath(first)), SELECT_DIR_NAME)
    messagebox.showinfo(
        '输出位置',
        f'筛选结果将放到：\n{default_out}\n\n'
        f'（每个来源文件夹在 _筛选 下建一个同名子文件夹）')
    return list(files)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='从压缩包里筛出纯数字编号的图片，按来源文件夹归到 _筛选 下')
    ap.add_argument('zips', nargs='*', help='压缩包路径（不填则弹窗选择）')
    ap.add_argument('--out', help='输出目录（默认：压缩包同级的 _筛选）')
    ap.add_argument('--dry-run', action='store_true', help='只预览，不复制文件')
    ap.add_argument('--keep-temp', action='store_true', help='保留解压临时目录')
    args = ap.parse_args(argv)

    zips = args.zips or pick_zips_by_dialog()
    if not zips:
        print('没有选择压缩包，已退出。')
        return 0

    # 输出根目录：--out 直接作为筛选根；否则"压缩包同级/_筛选"
    # 多个包时每个包再套一层以包名命名的子目录，避免不同包的叶子文件夹混在一起
    base_out = (os.path.abspath(args.out) if args.out
                else os.path.join(os.path.dirname(os.path.abspath(zips[0])),
                                  SELECT_DIR_NAME))
    multi = len(zips) > 1
    if not args.dry_run:
        os.makedirs(base_out, exist_ok=True)
    print('=' * 66)
    print(f'待处理 {len(zips)} 个压缩包')
    print(f'输出根目录：{base_out}'
          + ('（每个包再按包名分一层）' if multi else ''))
    print('=' * 66)

    grand = 0
    for zp in zips:
        out_root = base_out
        if multi:
            out_root = os.path.join(base_out, os.path.splitext(os.path.basename(zp))[0])
        if not args.dry_run:
            os.makedirs(out_root, exist_ok=True)
        n, _ = process_zip(zp, out_root, dry_run=args.dry_run,
                           keep_temp=args.keep_temp)
        grand += n
    print('\n' + '=' * 66)
    print(f'全部完成：共筛出 {grand} 张图片' + ('（dry-run）' if args.dry_run else ''))
    if not args.dry_run:
        print(f'结果目录：{base_out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
