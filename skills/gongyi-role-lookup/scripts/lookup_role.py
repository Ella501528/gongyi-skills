#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
慈善组织岗位职责速查 · 查询脚本

用法：
  python lookup_role.py --q 秘书长              # 查一个岗位：它做什么、容易踩什么、资格要求
  python lookup_role.py --item 章程             # 查一件事：谁主责、谁协办
  python lookup_role.py --role 秘书长           # 列出该岗位主责/协办的全部事项
  python lookup_role.py --list                  # 列出全部章节与全部事项
  python lookup_role.py --q 财务 --full         # 输出完整正文（默认截断）
  python lookup_role.py --item 章程 --json      # JSON 输出

记号：● 主责　○ 协办　（空）不承担
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'data')


def load(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        sys.exit(f'缺少数据文件：{p}')
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def show_section(sec, full=False, limit=420):
    out = [f'◆ {sec["title"]}']
    for b in sec['blocks']:
        t = b['text']
        if not full and len(t) > limit:
            t = t[:limit].rstrip() + '…（要完整内容加 --full）'
        if b['title']:
            out.append(f'\n  〔{b["title"]}〕')
        out.append('  ' + t.replace('\n', '\n  '))
    return '\n'.join(out)


def mark(v):
    return {'●': '【主责】', '○': '【协办】'}.get(v, '')


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--q', help='查岗位或章节（关键词）')
    ap.add_argument('--item', help='查事项：谁主责、谁协办')
    ap.add_argument('--role', help='按角色列事项')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--full', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    secs = load('roles.json')
    mx = load('matrix.json')
    cols = [c for c in mx['columns'] if c != '事项']

    if a.list:
        if a.json:
            print(json.dumps({'sections': [s['title'] for s in secs],
                              'roles': cols,
                              'items': [r['item'] for r in mx['rows']]},
                             ensure_ascii=False, indent=1))
            return
        print('【章节】')
        for s in secs:
            print('  · ' + s['title'])
        print('\n【对照表里的角色】')
        print('  ' + '、'.join(cols))
        print(f'\n【对照表里的事项】共 {len(mx["rows"])} 项')
        for r in mx['rows']:
            print('  · ' + r['item'])
        return

    if a.item:
        q = a.item.strip()
        hit = [r for r in mx['rows'] if q in r['item']]
        if not hit:
            print(f'对照表里没有含「{q}」的事项。')
            print('相近的事项：')
            for r in [x for x in mx['rows'] if set(q) & set(x['item'])][:6]:
                print('  · ' + r['item'])
            return
        if a.json:
            print(json.dumps(hit, ensure_ascii=False, indent=1))
            return
        for r in hit:
            print(f'◆ {r["item"]}')
            lead, asst = [], []
            for c, v in zip(cols, r['roles']):
                if v == '●':
                    lead.append(c)
                elif v == '○':
                    asst.append(c)
            print('  主责：' + ('、'.join(lead) if lead else '（表内未标主责）'))
            print('  协办：' + ('、'.join(asst) if asst else '（无）'))
            print('  （对照表给的是"职责清晰时的一种分法"；实际机构一人可能兼几行。）')
            print()
        return

    if a.role:
        q = a.role.strip()
        if q not in cols:
            c2 = [c for c in cols if q in c or c in q]
            if not c2:
                print(f'对照表里没有「{q}」。可选：' + '、'.join(cols))
                return
            q = c2[0]
        i = cols.index(q)
        lead = [r['item'] for r in mx['rows'] if r['roles'][i] == '●']
        asst = [r['item'] for r in mx['rows'] if r['roles'][i] == '○']
        if a.json:
            print(json.dumps({'role': q, '主责': lead, '协办': asst}, ensure_ascii=False, indent=1))
            return
        print(f'◆ {q}')
        print(f'  主责 {len(lead)} 项：')
        for x in lead:
            print('   ● ' + x)
        print(f'  协办 {len(asst)} 项：')
        for x in asst:
            print('   ○ ' + x)
        print()
        return

    if not a.q:
        ap.print_help()
        return

    q = a.q.strip()
    hit = [s for s in secs if q in s['title']]
    if not hit:
        hit = [s for s in secs if any(q in b['text'] for b in s['blocks'])]
    if not hit:
        print(f'没有查到「{q}」。')
        print('本手册的章节：')
        for s in secs:
            print('  · ' + s['title'])
        return
    if a.json:
        print(json.dumps(hit, ensure_ascii=False, indent=1))
        return
    for s in hit:
        print(show_section(s, a.full))
        print()

    # 顺带把该词在对照表里的事项列出来
    rel = [r for r in mx['rows'] if q in r['item']]
    if rel:
        print('— 对照表里相关的事项 —')
        for r in rel:
            lead = [c for c, v in zip(cols, r['roles']) if v == '●']
            asst = [c for c, v in zip(cols, r['roles']) if v == '○']
            print(f'  · {r["item"]}：主责 {"、".join(lead) or "—"}；协办 {"、".join(asst) or "—"}')


if __name__ == '__main__':
    main()
