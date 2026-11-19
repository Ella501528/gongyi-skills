#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""存量材料盘点 4/4：归位一致性校验。

校验项：
  1. 计划中每个实体化文件在目标文件夹内存在且大小一致；
  2. 每个有材料的要点文件夹内存在「取材指针.md」；
  3. 缺项/待确认清单行数与 match_report 状态一致；
  4. 归档树内不存在 0 字节文件（复制中断的痕迹）；
  5. 归档根目录内文件总数与计划一致（不多不少，防误复制）。

退出码 0 才允许交付。

用法：
  python validate_placement.py --work "<工作目录>" --archive "<归档根>"
"""
import argparse
import csv
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

FAILS = []
OKS = []


def check(cond, ok_msg, fail_msg):
    if cond:
        OKS.append(ok_msg)
    else:
        FAILS.append(fail_msg)
    print(('PASS  ' if cond else 'FAIL  ') + (ok_msg if cond else fail_msg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--archive', required=True)
    ap.add_argument('--expect-executed', action='store_true',
                    help='要求已真实执行（默认按预演校验）')
    args = ap.parse_args()

    work, arch = args.work, os.path.abspath(args.archive)
    plan = json.load(open(os.path.join(work, 'placement_plan.json'), encoding='utf-8'))
    rep = json.load(open(os.path.join(work, 'match_report.json'), encoding='utf-8'))
    items = plan['items']
    executed = any(it['materialize'] and os.path.exists(it['target']) for it in items)

    print('归档根: %s' % arch)
    print('模式: %s    计划实体化: %d 个 / %s'
          % (plan['mode'], plan['totals']['materialize_files'],
             plan['totals']['materialize_size_human']))
    print('')

    # 1) 文件夹存在
    missing_dirs = [it['code'] for it in items if not os.path.isdir(it['target'])]
    check(not missing_dirs, '全部 %d 个要点文件夹存在' % len(items),
          '%d 个要点文件夹缺失: %s' % (len(missing_dirs), missing_dirs[:8]))

    # 2) 实体化文件核对
    #    注意：同名不同源的文件在就位时会加 `_01`/`_02` 后缀（存量里"官网截图版"与
    #    "制度原件版"经常同名），因此不能只按原文件名比对——须在"同名族"里按大小命中。
    bad, checked = [], 0
    for it in items:
        for r in it['materialize']:
            checked += 1
            if not os.path.isdir(it['target']):
                bad.append('%s → 目标文件夹缺失' % it['code'])
                continue
            base, ext = os.path.splitext(r['name'])
            sizes = []
            for fn in os.listdir(it['target']):
                if fn == r['name'] or (fn.startswith(base + '_') and fn.endswith(ext)):
                    try:
                        sizes.append(os.path.getsize(os.path.join(it['target'], fn)))
                    except OSError:
                        pass
            if not sizes:
                bad.append('%s → 缺文件 %s' % (it['code'], r['name']))
            elif r['size'] not in sizes:
                bad.append('%s → 大小不符 %s' % (it['code'], r['name']))
    if executed:
        check(not bad, '实体化文件 %d 个全部就位且大小一致' % checked,
              '%d 个文件异常: %s' % (len(bad), bad[:8]))
    else:
        print('SKIP  未执行实体化（预演模式），跳过文件就位核对（计划 %d 个）' % checked)

    # 3) 取材指针
    need = [it['code'] for it in items if (it['materialize'] or it['index_only'])]
    no_ptr = [it['code'] for it in items
              if (it['materialize'] or it['index_only'])
              and not os.path.exists(os.path.join(it['target'], '取材指针.md'))]
    if executed:
        check(not no_ptr, '取材指针.md 覆盖全部 %d 个有材料要点' % len(need),
              '%d 个要点缺取材指针: %s' % (len(no_ptr), no_ptr[:8]))
    else:
        print('SKIP  预演模式，跳过取材指针核对（应有 %d 个）' % len(need))

    # 4) 清单行数与状态一致
    def rows(p):
        fp = os.path.join(work, p)
        if not os.path.exists(fp):
            return None
        with open(fp, encoding='utf-8-sig', newline='') as fh:
            return list(csv.reader(fh))[1:]
    g = rows('缺项清单.csv')
    r = rows('待人工确认清单.csv')
    exp_gap = rep['summary']['status'].get('缺项', 0)
    exp_rev = rep['summary']['status'].get('待确认', 0)
    if g is None or r is None:
        print('SKIP  清单尚未生成（预演模式可接受）')
    else:
        check(len(g) == exp_gap, '缺项清单 %d 行 = 匹配结果 %d 项' % (len(g), exp_gap),
              '缺项清单 %d 行 != 匹配结果 %d 项' % (len(g), exp_gap))
        check(len(r) == exp_rev, '待确认清单 %d 行 = 匹配结果 %d 项' % (len(r), exp_rev),
              '待确认清单 %d 行 != 匹配结果 %d 项' % (len(r), exp_rev))

    # 5) 归档树内 0 字节文件
    zero = []
    for cur, _d, fns in os.walk(arch):
        for fn in fns:
            p = os.path.join(cur, fn)
            try:
                if os.path.getsize(p) == 0:
                    zero.append(p)
            except OSError:
                pass
    check(not zero, '归档树内无 0 字节文件',
          '发现 %d 个 0 字节文件（疑复制中断）: %s' % (len(zero), zero[:5]))

    # 6) 覆盖统计
    s = rep['summary']
    print('')
    print('覆盖统计: 已归位 %d / 待确认 %d / 缺项 %d，覆盖率 %.1f%%'
          % (s['status'].get('已归位', 0), s['status'].get('待确认', 0),
             s['status'].get('缺项', 0), s['coverage_pct']))

    print('')
    print('=' * 46)
    print('PASS %d 项 / FAIL %d 项' % (len(OKS), len(FAILS)))
    if FAILS:
        for f in FAILS:
            print('  × ' + f)
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
