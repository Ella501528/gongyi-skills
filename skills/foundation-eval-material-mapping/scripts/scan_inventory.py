#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""存量材料盘点 1/4：只读扫描指定根目录，生成 inventory.json。

安全边界（硬规则）：
  - 全程只读：不新建、不移动、不重命名、不删除任何源文件；
  - 只扫用户显式指定的根目录，绝不自动扩展到盘符根或用户主目录；
  - 跳过系统与缓存目录（回收站、系统卷信息、node_modules、.git 等）。

用法：
  python scan_inventory.py --root "<目录1>" --root "<目录2>" --out "<工作目录>"
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

EXCLUDE_DIRS = {
    '$recycle.bin', 'system volume information', '__pycache__', '.git',
    'node_modules', '.idea', '.vscode', '$windows.~bt', '.trash', '.cache',
}
RAW_EXT = {'cr2', 'arw', 'nef', 'dng', 'raf', 'orf', 'rw2', 'pef', 'sr2'}
VIDEO_EXT = {'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'm4v', 'mpg', 'mpeg', 'ts'}
IMAGE_EXT = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'jfif', 'heic', 'tif', 'tiff'}
DOC_EXT = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'wps', 'et', 'dps',
           'ofd', 'txt', 'md', 'csv', 'rtf'}
# 未下载完成 / 临时中间件：体积可能很大但内容不完整，绝不可作为证据
PARTIAL_EXT = {'downloading', 'crdownload', 'part', 'tmp', 'partial', '!ut', 'bc!'}
PARTIAL_PAT = re.compile(r'\.(baiduyun|p)\.downloading$|\.crdownload$|\.part$', re.I)
YEAR_RE = re.compile(r'(20\d{2})')
YEAR_MIN, YEAR_MAX = 2000, 2030  # 超出范围视为文件名中的其他数字，不当作年份
# 噪音目录/文件：明显与迎评证据无关
NOISE_PAT = re.compile(r'(上线素材|未采用|废稿|临时|temp|备份|old|旧版)', re.I)


def kind_of(ext, name=''):
    e = (ext or '').lower().lstrip('.')
    if e in PARTIAL_EXT or PARTIAL_PAT.search(name or ''):
        return 'partial'
    if e in RAW_EXT:
        return 'raw'
    if e in VIDEO_EXT:
        return 'video'
    if e in IMAGE_EXT:
        return 'image'
    if e in DOC_EXT:
        return 'doc'
    return 'other'


def guess_year(name, dirs):
    m = YEAR_RE.search(name or '')
    if m and YEAR_MIN <= int(m.group(1)) <= YEAR_MAX:
        return int(m.group(1))
    for d in reversed(dirs or []):
        m = YEAR_RE.search(d)
        if m and YEAR_MIN <= int(m.group(1)) <= YEAR_MAX:
            return int(m.group(1))
    return None


def scan_root(root, label):
    files = []
    root = os.path.abspath(root)
    for cur, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in EXCLUDE_DIRS]
        for fn in filenames:
            abs_p = os.path.join(cur, fn)
            try:
                st = os.stat(abs_p)
            except OSError:
                continue
            rel = os.path.relpath(abs_p, root)
            parts = rel.split(os.sep)
            dirs = parts[:-1]
            ext = os.path.splitext(fn)[1]
            files.append({
                'root': label,
                'root_path': root,
                'rel': rel,
                'abs': abs_p,
                'name': fn,
                'stem': os.path.splitext(fn)[0],
                'ext': ext.lower().lstrip('.'),
                'size': st.st_size,
                'mtime': time.strftime('%Y-%m-%d', time.localtime(st.st_mtime)),
                'year': guess_year(fn, dirs),
                'kind': kind_of(ext, fn),
                'dirs': dirs,
                'noise': bool(NOISE_PAT.search(rel)),
            })
    return files


def human(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return '%.1f%s' % (n, unit)
        n /= 1024.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', action='append', required=True,
                    help='待扫描根目录，可重复；格式 "<标签>=<路径>" 或仅路径')
    ap.add_argument('--out', required=True, help='工作目录（输出 inventory.json）')
    args = ap.parse_args()

    roots = []
    for spec in args.root:
        if '=' in spec:
            label, path = spec.split('=', 1)
        else:
            path = spec
            label = os.path.basename(os.path.normpath(path))
        if not os.path.isdir(path):
            print('SKIP 目录不存在: %s' % path)
            continue
        roots.append((label, os.path.abspath(path)))

    if not roots:
        print('FAIL 没有任何有效根目录')
        return 1

    os.makedirs(args.out, exist_ok=True)
    all_files = []
    for label, path in roots:
        got = scan_root(path, label)
        all_files.extend(got)
        print('  扫描 %-28s %5d 文件' % (label, len(got)))

    # 去重：同绝对路径只留一次
    seen, uniq = set(), []
    for f in all_files:
        k = os.path.normcase(f['abs'])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(f)
    for i, f in enumerate(uniq):
        f['id'] = i

    total = sum(f['size'] for f in uniq)
    by_kind = Counter(f['kind'] for f in uniq)
    size_kind = Counter()
    for f in uniq:
        size_kind[f['kind']] += f['size']
    by_ext = Counter(f['ext'] for f in uniq)

    inv = {
        'scanned_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'roots': [{'label': l, 'path': p} for l, p in roots],
        'stats': {
            'files': len(uniq),
            'total_size': total,
            'total_size_human': human(total),
            'by_kind': dict(by_kind),
            'size_by_kind': {k: human(v) for k, v in size_kind.items()},
            'top_ext': by_ext.most_common(15),
            'noise_files': sum(1 for f in uniq if f['noise']),
        },
        'files': uniq,
    }
    out = os.path.join(args.out, 'inventory.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(inv, fh, ensure_ascii=False)

    print('')
    print('文件数: %d（去重后）' % len(uniq))
    print('总体积: %s' % human(total))
    print('按类型: ' + ', '.join('%s=%d(%s)' % (k, v, human(size_kind[k]))
                               for k, v in by_kind.most_common()))
    print('噪音文件(命名含临时/废稿等): %d' % inv['stats']['noise_files'])
    if by_kind.get('raw'):
        print('提示: 原始底片 %d 个（%s）——按规则不实体化，仅登记指针'
              % (by_kind['raw'], human(size_kind['raw'])))
    if by_kind.get('partial'):
        print('提示: 未下载完成/临时文件 %d 个（%s）——排除在匹配之外，不得作为证据'
              % (by_kind['partial'], human(size_kind['partial'])))
    print('OK  已写出 %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
