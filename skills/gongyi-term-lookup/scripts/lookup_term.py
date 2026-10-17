#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
慈善组织术语速查 · 查询脚本

用法：
  python lookup_term.py --q 公募              # 按关键词查（词条名优先，其次正文）
  python lookup_term.py --q 民非 --full       # 连完整解释一起输出
  python lookup_term.py --cat 治理            # 列出某一类的全部词条
  python lookup_term.py --list                # 列出九类与全部词条名
  python lookup_term.py --q 公募 --json       # 输出 JSON（供程序调用）

说明：
  · 命中词条名 → 直接给解释；命中正文 → 作为"提到过这个词"列出。
  · 若该词属于「容易混的六组」，自动附上对比表——这是本词典最容易被用错的地方。
  · 查不到时给近似建议，不编造解释。
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


def pretty(t, full=False):
    note = f'（{t["note"]}）' if t.get('note') else ''
    body = t['definition'] if full else t['definition'][:180].rstrip() + ('…' if len(t['definition']) > 180 else '')
    return f'【{t["term"]}】{note}\n  分类：{t["category"]}\n  {body.replace(chr(10), chr(10) + "  ")}'


def related_confusions(term, confs):
    """该词出现在哪些「容易混」对比组里"""
    out = []
    for g in confs:
        blob = g['title'] + ' ' + ' '.join(g['columns']) + ' ' + ' '.join(
            c for r in g['rows'] for c in r)
        if term and term in blob:
            out.append(g)
    return out


def show_confusion(g):
    lines = [f'◆ {g["title"]}']
    cols = g['columns']
    if cols:
        lines.append('  ' + ' ｜ '.join(c for c in cols))
        lines.append('  ' + '—' * 30)
    for r in g['rows']:
        first = r[0] if r else ''
        rest = r[1:] if len(r) > 1 else []
        if rest:
            lines.append(f'  · {first}：' + ' ｜ '.join(rest))
        else:
            lines.append(f'  · {first}')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--q', help='关键词')
    ap.add_argument('--cat', help='按分类列出')
    ap.add_argument('--list', action='store_true', help='列出全部分类与词条')
    ap.add_argument('--full', action='store_true', help='输出完整解释（不截断）')
    ap.add_argument('--json', action='store_true', help='以 JSON 输出')
    a = ap.parse_args()

    data = load('terms.json')
    terms = data['terms']
    confs = load('confusions.json')

    if a.list:
        if a.json:
            print(json.dumps({'count': data['count'], 'categories': data['categories'],
                              'terms': [t['term'] for t in terms]}, ensure_ascii=False, indent=1))
            return
        print(f'共 {data["count"]} 条 · {len(data["categories"])} 类\n')
        cur = None
        for t in terms:
            if t['category'] != cur:
                cur = t['category']
                print(f'\n【{cur}】')
            print('  ' + t['term'])
        print('\n另有「容易混的六组」对比：')
        for g in confs:
            print('  ' + g['title'])
        return

    if a.cat:
        hit = [t for t in terms if a.cat in t['category']]
        if not hit:
            print(f'没有分类含「{a.cat}」。可选分类：' + '、'.join(data['categories']))
            return
        for t in hit:
            print(pretty(t, a.full))
            print()
        return

    if not a.q:
        ap.print_help()
        return

    q = a.q.strip()
    exact = [t for t in terms if t['term'] == q]
    head = [t for t in terms if q in t['term'] and t not in exact]
    body = [t for t in terms if q not in t['term'] and q in t['definition']]

    if a.json:
        print(json.dumps({
            'query': q,
            'exact': exact,
            'term_matches': head,
            'mentioned_in': [t['term'] for t in body],
            'confusion_groups': related_confusions(q, confs),
        }, ensure_ascii=False, indent=1))
        return

    if not (exact or head or body):
        chars = set(q)
        sug = sorted(terms, key=lambda t: -len(chars & set(t['term'])))[:5]
        print(f'没有查到「{q}」。')
        print('字典里没有这个词条——不要据此推断它的含义。')
        print('\n可能相关的词条（按字面相近，供参考）：')
        for t in sug:
            print('  · ' + t['term'])
        print('\n如果它确实是行业里在用的说法，建议先确认：是老词、口语，还是新规。')
        return

    if exact:
        print('— 直接命中的词条 —\n')
        for t in exact:
            print(pretty(t, True))
            print()

    if head:
        print('— 词条名包含该词 —\n')
        for t in head:
            print(pretty(t, a.full))
            print()

    if body:
        print('— 在别的词条里被提到 —')
        for t in body:
            print('  · ' + t['term'] + f'（{t["category"]}）')
        print('  （这些词条的解释里出现过「%s」，需要看原文时查它们）' % q)
        print()

    groups = related_confusions(q, confs)
    if groups:
        print('— 容易混，务必对照 —\n')
        for g in groups:
            print(show_confusion(g))
            print()


if __name__ == '__main__':
    main()
