#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""存量材料盘点 附加：同名多版本检测。

为什么需要：机构存量里同一份文档常有多个版本散在不同目录（"制度原件版" vs
"官网截图版" vs "扫描件版"），文件名相同、内容与大小不同。评估现场如果出示了
旧版本或截图版，会直接影响"制度是否落实""材料是否规范"的判断——这是很现实
的失分点，且**只有先发现才能预防**。

输出：同名多版本清单.csv + 控制台摘要（含涉及哪些指标编号）。

用法：
  python report_duplicates.py --work "<工作目录>"
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def human(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return '%.1f%s' % (n, u)
        n /= 1024.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--min-versions', type=int, default=2)
    ap.add_argument('--only-placed', action='store_true',
                    help='只看已归入指标文件夹的文件族（推荐；过滤抓取脚本产物等噪音）')
    args = ap.parse_args()
    work = args.work

    inv = json.load(open(os.path.join(work, 'inventory.json'), encoding='utf-8'))
    rep = json.load(open(os.path.join(work, 'match_report.json'), encoding='utf-8'))
    plan = json.load(open(os.path.join(work, 'placement_plan.json'), encoding='utf-8'))

    # 文件 → 落到的指标编号
    where = defaultdict(list)
    for it in plan['items']:
        for r in it['materialize'] + it['index_only']:
            where[r['abs']].append(it['code'])

    # 同名同大小的多份副本不算"版本冲突"，因此只需要看证据类载体
    EVIDENCE_KINDS = ('doc', 'image', 'video', 'raw')
    groups = defaultdict(list)
    for f in inv['files']:
        if f.get('kind') not in EVIDENCE_KINDS or f.get('noise'):
            continue
        if args.only_placed and not where.get(f['abs']):
            continue
        groups[f['name'].strip().lower()].append(f)

    rows = []
    for name, fs in groups.items():
        if len(fs) < args.min_versions:
            continue
        sizes = {f['size'] for f in fs}
        if len(sizes) < 2:
            continue  # 大小完全相同视为重复副本，不算版本冲突
        codes = sorted({c for f in fs for c in where.get(f['abs'], [])})
        rows.append({
            'name': fs[0]['name'],
            'versions': fs,
            'sizes': sizes,
            'codes': codes,
            'spread': len({f['root'] for f in fs}),
        })
    rows.sort(key=lambda r: (-len(r['versions']), r['name']))

    out = os.path.join(work, '同名多版本清单.csv')
    with open(out, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['文件名', '版本数', '分布来源数', '文件大小', '来源路径', '对应指标编号', '风险提示'])
        for r in rows:
            w.writerow([
                r['name'], len(r['versions']), r['spread'],
                ' / '.join(human(s) for s in sorted(r['sizes'])),
                ' | '.join('%s（%s，%s）' % (f['abs'], human(f['size']), f['mtime']) for f in r['versions']),
                '、'.join(r['codes']) if r['codes'] else '未归位',
                '现场一律出示最新且最完整版本；建议归档前确认唯一权威版本',
            ])

    tot = sum(len(r['versions']) for r in rows)
    hit = sum(1 for r in rows if r['codes'])
    print('同名但内容不同（大小不一致）的文件族: %d 组，涉及 %d 个文件' % (len(rows), tot))
    print('其中已被归入指标文件夹的: %d 组' % hit)
    print('')
    if rows:
        print('TOP10（版本最多）：')
        for r in rows[:10]:
            print('  %d 版本 · %s' % (len(r['versions']), r['name'][:52]))
            print('      %s' % (' / '.join(human(s) for s in sorted(r['sizes']))))
    print('')
    print('OK  已写出 %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
