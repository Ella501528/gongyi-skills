# -*- coding: utf-8 -*-
"""批次输出校验器：batches/output_*.json 对 enriched_meta.json 做四项校验

校验：
1. 覆盖率   —— 批次 code 集合 == 源 code 集合（无缺失/无重复/无多余）
2. 字段非空 —— basis_enh / method_enh / matlist_enh / why 均非空
3. 依据完整性 —— basis_enh 含正式文件名称《》；无法定依据者须标[实操指引，非法定依据]
4. 法规口径统一 —— 同一法规不得出现两个文号版本（冲突清单见 regulation-currency-check）

用法：
  python check_batches.py --work "<工作目录>"
退出码：0=全部通过；1=存在 FAIL
"""
import argparse
import glob
import json
import os
import re
import sys


try:  # Windows 控制台中文输出保护
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


# 法规口径冲突检测：同名法规 + 竞争性文号（可扩展）
CONFLICTS = [
    ('慈善组织信息公开办法', [r'令第\s*61\s*号|第\s*61\s*号令', r'令第\s*81\s*号|第\s*81\s*号令']),
    ('年度支出和管理费用规定', [r'民发〔2016〕189号', r'民发〔2016〕99号', r'民发〔2026〕12号']),
    ('慈善法公益支出比例', [r'第\s*六十条', r'第\s*六十一条']),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    a = ap.parse_args()

    meta = json.load(open(os.path.join(a.work, 'enriched_meta.json'), encoding='utf-8'))
    src_codes = [x['code'] for x in meta]

    outs = sorted(glob.glob(os.path.join(a.work, 'batches', 'output_*.json')))
    if not outs:
        sys.exit(f'未找到批次输出文件: {os.path.join(a.work, "batches", "output_*.json")}')

    allout, per_file = [], {}
    for p in outs:
        d = json.load(open(p, encoding='utf-8'))
        per_file[os.path.basename(p)] = len(d)
        allout += d
        print(f'{os.path.basename(p)}: {len(d)} 项')

    codes = [x['code'] for x in allout]
    ok = True

    def chk(name, cond, detail=''):
        nonlocal ok
        print(('PASS' if cond else 'FAIL'), name, detail)
        if not cond:
            ok = False

    chk('总项数一致', len(codes) == len(src_codes), f'{len(codes)} vs {len(src_codes)}')
    chk('无缺失', not (set(src_codes) - set(codes)), str(sorted(set(src_codes) - set(codes))[:10]))
    chk('无多余', not (set(codes) - set(src_codes)), str(sorted(set(codes) - set(src_codes))[:10]))
    dup = sorted({c for c in codes if codes.count(c) > 1})
    chk('无重复', not dup, str(dup[:10]))

    keys = ('basis_enh', 'method_enh', 'matlist_enh', 'why')
    empty = [x.get('code') for x in allout
             if not all(str(x.get(k, '') or '').strip() for k in keys)]
    chk('四字段均非空', not empty, str(empty[:10]))

    nobook = [x['code'] for x in allout if '《' not in str(x.get('basis_enh', ''))]
    chk('依据均含《》', not nobook, str(nobook[:10]))

    for law, pats in CONFLICTS:
        # 同一条目内同时出现多个版本 = 明确写了"替代关系"，属正常表述；
        # 只有不同条目各自坚持不同版本，才算真正的口径冲突。
        exclusives, both = {}, []
        for x in allout:
            t = str(x.get('basis_enh', ''))
            ms = [p for p in pats if re.search(p, t)]
            if len(ms) > 1:
                both.append(x['code'])
            elif ms:
                exclusives.setdefault(ms[0], []).append(x['code'])
        if len(exclusives) > 1:
            ok = False
            print(f'FAIL 口径冲突 [{law}]：同一法规出现互斥版本')
            for p, v in exclusives.items():
                print(f'      {p} → {len(v)} 项 {v[:8]}')
        else:
            cur = list(exclusives) or ['未出现']
            print(f'PASS 口径唯一 [{law}]  现行版本: {cur[0]}  已注明替代关系: {len(both)} 项')

    tiers = {}
    for x in meta:
        tiers[x.get('tier')] = tiers.get(x.get('tier'), 0) + 1
    print('源档位分布:', tiers)
    why_len = [len(str(x.get('why', ''))) for x in allout]
    print(f'why 平均长度: {sum(why_len) // max(len(why_len), 1)} 字')
    print('RESULT:', 'ALL PASS' if ok else 'HAS FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
