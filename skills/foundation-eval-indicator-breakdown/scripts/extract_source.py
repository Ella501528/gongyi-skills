# -*- coding: utf-8 -*-
"""指标表抽取器：官方评估指标 xlsx → source_extract.json

通用化要点（相对一次性脚本）：
- 工作表名、表头行、数据起始行、结束条件全部可配置，不硬编码机构与版本
- 兼容"标准模板"（仅编号+要点）与"已填模板"（含依据/法规原文/考查方式/资料清单）
- 列缺失（小于14列）时自动降级，不报错
- 分值优先从考查要点文本"（X分）"解析，分值列仅作交叉核对

用法：
  python extract_source.py --src "<指标表.xlsx>" --sheet "<工作表名>" --out "<工作目录>" \
      [--org "<机构简称>"] [--version "<指标版本>"] [--header-row 2] [--data-start 3]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter


try:  # Windows 控制台中文输出保护
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass



def ensure_openpyxl():
    """导入 openpyxl；失败时尝试从 WorkBuddy 隔离目录加载。"""
    try:
        import openpyxl  # noqa
        return openpyxl
    except ImportError:
        pass
    home = os.path.expanduser('~')
    cfg = os.environ.get('WORKBUDDY_CONFIG_DIR', '')
    cands = [
        os.environ.get('WB_PY_PKGS', ''),
        os.path.join(cfg, 'binaries', 'python', 'tmp_pkgs') if cfg else '',
        os.path.join(cfg, 'binaries', 'python', 'envs', 'default', 'Lib', 'site-packages') if cfg else '',
        os.path.join(home, '.workbuddy', 'binaries', 'python', 'tmp_pkgs'),
    ]
    for c in cands:
        if c and os.path.isdir(c) and c not in sys.path:
            sys.path.insert(0, c)
    try:
        import openpyxl  # noqa
        return openpyxl
    except ImportError:
        sys.exit('缺少依赖 openpyxl。请安装到隔离目录后重试：\n'
                 '  python -m pip install openpyxl -q --target "<WorkBuddy python tmp_pkgs>"\n'
                 '  并设置环境变量 WB_PY_PKGS 指向该目录。')


openpyxl = ensure_openpyxl()

# 固定列位（1-based）：0序号 1一级 2二级 3三级 4考查要点 5分值 6类型 7考查方式 8资料清单 9未判 10现场看点 11备注 12规定依据 13法规原文
COL = {
    'l1': 2, 'l2': 3, 'l3': 4, 'point': 5, 'score': 6, 'type': 7,
    'method': 8, 'matlist': 9, 'weipan': 10, 'view': 11, 'note': 12,
    'basis': 13, 'lawtext': 14,
}


def clean(v):
    if v is None:
        return None
    s = str(v).replace('\r\n', '\n').replace('\r', '\n')
    return s.strip() or None


def parse_args():
    p = argparse.ArgumentParser(description='评估指标表抽取器')
    p.add_argument('--src', required=True, help='指标表 xlsx 路径')
    p.add_argument('--sheet', default=None, help='工作表名（默认取第一个非空表）')
    p.add_argument('--out', required=True, help='输出工作目录')
    p.add_argument('--org', default='', help='机构简称（写入产出，便于多机构隔离）')
    p.add_argument('--version', dest='version', default='', help='指标版本号')
    p.add_argument('--header-row', type=int, default=2, help='表头行号（默认2）')
    p.add_argument('--data-start', type=int, default=3, help='数据起始行号（默认3）')
    return p.parse_args()


def main():
    a = parse_args()
    os.makedirs(a.out, exist_ok=True)
    wb = openpyxl.load_workbook(a.src)          # 注意：不要用 read_only，会漏读后段列
    ws = wb[a.sheet] if a.sheet else wb.worksheets[0]
    ncol = ws.max_column
    if ncol < 14:
        print(f'⚠️ 工作表仅 {ncol} 列，后段列（规定依据/法规原文）可能缺失，将按空值处理')

    def cell(r, key):
        c = COL[key]
        return clean(ws.cell(row=r, column=c).value) if c <= ncol else None

    rows = []
    cur1 = cur2 = cur3 = None
    blank_streak = 0
    for r in range(a.data_start, ws.max_row + 1):
        v1, v2, v3 = cell(r, 'l1'), cell(r, 'l2'), cell(r, 'l3')
        point = cell(r, 'point')
        if not point and not v1 and not v2 and not v3:
            blank_streak += 1
            if blank_streak >= 3:               # 连续空行视为表尾（跳过合计行）
                break
            continue
        blank_streak = 0
        if v1:
            cur1 = v1.replace('\n', '')
        if v2:
            cur2 = v2.replace('\n', '')
        if v3:
            cur3 = v3.replace('\n', '')
        if not point:
            continue

        m = re.match(r'^(\d+(?:\.\d+){3})', point)
        code = m.group(1) if m else None
        m3 = re.match(r'^(\d+(?:\.\d+){2})', cur3 or '')
        m2 = re.match(r'^(\d+\.\d+)', cur2 or '')
        m1 = re.match(r'^(\d+)', cur1 or '')
        ms = re.search(r'[（(](\d+(?:\.\d+)?)\s*分\s*[)）]', point)
        score_c6 = cell(r, 'score')

        rows.append({
            'row': r,
            'code': code,
            'point_text': point,
            'l1_code': m1.group(1) if m1 else None, 'l1': cur1,
            'l2_code': m2.group(1) if m2 else None, 'l2': cur2,
            'l3_code': m3.group(1) if m3 else None, 'l3': cur3,
            'score': float(ms.group(1)) if ms else None,
            'score_c6': float(score_c6) if score_c6 and re.match(r'^-?\d+(\.\d+)?$', score_c6) else None,
            'type': cell(r, 'type'),
            'method': cell(r, 'method'),
            'matlist': cell(r, 'matlist'),
            'weipan': cell(r, 'weipan'),
            'view': cell(r, 'view'),
            'note': cell(r, 'note'),
            'basis': cell(r, 'basis'),
            'lawtext': cell(r, 'lawtext'),
        })

    total = sum(x['score'] or 0 for x in rows)
    no_code = [x['row'] for x in rows if not x['code']]
    no_score = [x['row'] for x in rows if x['score'] is None]
    mismatch = [(x['row'], x['score'], x['score_c6']) for x in rows
                if x['score_c6'] is not None and x['score'] is not None
                and abs(x['score'] - x['score_c6']) > 1e-6]
    dup = sorted({c for c in (x['code'] for x in rows if x['code'])
                  if sum(1 for y in rows if y['code'] == c) > 1})

    print(f'sheet: {ws.title}')
    print(f'items: {len(rows)}')
    print(f'sum(score from text): {round(total, 2)}')
    print(f'no code rows: {no_code}')
    print(f'no score rows: {no_score}')
    print(f'score mismatch (row, text, col): {mismatch}')
    print(f'dup codes: {dup}')
    print(f'per l1: {dict(Counter(x["l1_code"] for x in rows))}')
    print(f'types: {dict(Counter(x["type"] for x in rows))}')
    filled = {k: sum(1 for x in rows if x.get(k)) for k in ('method', 'matlist', 'basis', 'lawtext')}
    print(f'源列填充度: {filled}  (→ 全为0表示标准模板=从零撰写；有值=重构增强)')

    out = os.path.join(a.out, 'source_extract.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump({
            '_meta': {'org': a.org, 'version': a.version, 'source_file': a.src, 'sheet': ws.title},
            'rows': rows,
        }, f, ensure_ascii=False, indent=1)
    print('saved:', out)


if __name__ == '__main__':
    main()
