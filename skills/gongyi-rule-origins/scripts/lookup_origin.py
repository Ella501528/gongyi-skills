#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
慈善规矩的来龙去脉 · 查询脚本

用法：
  python lookup_origin.py --q 管理费用          # 按关键词查一条"为什么"
  python lookup_origin.py --list                # 列出全部主题与每条的四个段落标题
  python lookup_origin.py --q 年检 --seg 规定     # 只看某一段
  python lookup_origin.py --q 监事会 --json      # JSON 输出

每条按四段组织：
  规定是什么 → 为什么会这样 → 它变过没有 → 对我们意味着什么
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'data')


def load():
    p = os.path.join(DATA, 'topics.json')
    if not os.path.exists(p):
        sys.exit(f'缺少数据文件：{p}')
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--q', help='关键词')
    ap.add_argument('--seg', help='只看含该词的段落（如 规定 / 变过 / 意味着）')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--full', action='store_true', help='不截断（默认截断长段）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    topics = load()

    if a.list:
        if a.json:
            print(json.dumps([{'title': t['title'],
                               'segments': [s['title'] for s in t['segments']]} for t in topics],
                             ensure_ascii=False, indent=1))
            return
        for i, t in enumerate(topics, 1):
            print(f'{i:>2}. {t["title"]}')
            for s in t['segments']:
                print(f'      · {s["title"] or "（正文）"}')
        return

    if not a.q:
        ap.print_help()
        return

    q = a.q.strip()
    hit = [t for t in topics if q in t['title']]
    if not hit:
        hit = [t for t in topics if any(q in s['text'] for s in t['segments'])]
    if not hit:
        print(f'没有查到「{q}」。')
        print('本手册回答的是这些问题：')
        for i, t in enumerate(topics, 1):
            print(f'  {i}. {t["title"]}')
        print('\n没回答到的，不要用这份材料去推断——请查现行法规原文。')
        return

    if a.json:
        print(json.dumps(hit, ensure_ascii=False, indent=1))
        return

    for t in hit:
        print(f'◆ {t["title"]}')
        print('─' * 46)
        for s in t['segments']:
            if a.seg and a.seg not in s['title']:
                continue
            if s['title']:
                print(f'\n〔{s["title"]}〕')
            txt = s['text']
            if not a.full and len(txt) > 700:
                txt = txt[:700].rstrip() + '…（要完整内容加 --full）'
            print(txt)
        print()


if __name__ == '__main__':
    main()
