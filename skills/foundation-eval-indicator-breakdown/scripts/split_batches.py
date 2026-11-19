# -*- coding: utf-8 -*-
"""批次切分器：enriched_meta.json → batches/input_<n>_<一级指标名>.json

按一级指标切分，避免单次撰写上下文溢出。

用法：
  python split_batches.py --work "<工作目录>" [--batch-size 0]
      --batch-size 0  : 按一级指标切分（默认）
      --batch-size N  : 每个一级指标再按 N 项细切（大板块超长时使用）
"""
import argparse
import sys
import json
import os
import re
from collections import OrderedDict


try:  # Windows 控制台中文输出保护
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass



def safe(name):
    """批次名清洗：去编号前缀、去分值括注、去非法字符。"""
    s = re.sub(r'^\s*\d+(\.\d+)*[.、]?\s*', '', name or '')
    s = re.sub(r'[（(].*?[)）]', '', s)
    s = re.sub(r'[\\/:*?"<>|\s]', '', s)
    return s or '未命名'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--batch-size', type=int, default=0)
    a = ap.parse_args()

    meta = json.load(open(os.path.join(a.work, 'enriched_meta.json'), encoding='utf-8'))
    outdir = os.path.join(a.work, 'batches')
    os.makedirs(outdir, exist_ok=True)

    groups = OrderedDict()
    for x in meta:
        key = (x['l1_code'], x['l1'])
        groups.setdefault(key, []).append(x)

    total = 0
    for (l1c, l1t), sub in groups.items():
        name = f'{l1c}_{safe(l1t)}'
        if a.batch_size and a.batch_size > 0:
            for i in range(0, len(sub), a.batch_size):
                chunk = sub[i:i + a.batch_size]
                p = os.path.join(outdir, f'input_{name}_p{i // a.batch_size + 1}.json')
                json.dump(chunk, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                total += 1
                print(f'{name} part{i // a.batch_size + 1}: {len(chunk)} 项')
        else:
            p = os.path.join(outdir, f'input_{name}.json')
            json.dump(sub, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            total += 1
            print(f'{name}: {len(sub)} 项  (档位 {dict(__import__("collections").Counter(y["tier"] for y in sub))})')

    print(f'批次文件数: {total}  输出目录: {outdir}')
    print('提示：每个批次对应一个撰写回合，提示词模板见 references/batch-prompt-template.md')


if __name__ == '__main__':
    main()
