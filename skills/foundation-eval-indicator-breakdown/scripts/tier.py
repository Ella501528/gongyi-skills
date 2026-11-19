# -*- coding: utf-8 -*-
"""增强元数据计算器：source_extract.json → enriched_meta.json

计算内容：
- 简繁档位（分值 × 类型，规则见 references/tier-rules.md）
- 建议负责人（按二级指标段映射职能角色，可用 --owner-map 覆盖）
- 归档文件夹路径（编号-名称 四层）
- needs_verify（源依据缺条款号/文号 → 需定向核验，【不因此升档】）
- code_mismatch（末级编号与三级编号不一致 → 源表疑似笔误）
- name_short（去编号、去括注的短名，用于文件夹与标题）

用法：
  python tier.py --work "<工作目录>" [--owner-map "<自定义映射.json>"] [--org "<机构简称>"]
"""
import argparse
import sys
import json
import os
import re
from collections import Counter


try:  # Windows 控制台中文输出保护
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


# 默认负责人映射：二级指标段 → 职能角色（机构人少时可合并，见 references/owner-map.md）
DEFAULT_OWNER = {
    '1.1': '办公室主任',
    '1.2': '秘书长（主）/办公室主任',
    '1.3': '秘书长（主）/办公室主任',
    '1.4': '财务负责人（主）/秘书长',
    '2.1': '党务工作者（主）/秘书长',
    '2.2': '党务工作者（主）/秘书长',
    '3.1': '财务负责人（主）/筹资负责人',
    '3.2': '项目负责人（主）/秘书长',
    '3.3': '秘书长',
    '3.4': '项目负责人（主）/秘书长',
    '4.1': '办公室主任（主）/秘书长',
    '4.2': '办公室主任（主）/财务负责人',
    '4.3': '秘书长',
    '4.4': '秘书长（主）/财务负责人',
    '4.5': '秘书长（主）/项目负责人',
    '5.1': '办公室主任（主）/秘书长',
    '5.2': '办公室主任（主）/项目负责人',
    '5.3': '办公室主任（主）/财务负责人',
    '5.4': '秘书长',
}
FALLBACK_OWNER = '秘书长'

CLAUSE = re.compile(r'第.{1,8}条|令第.{1,6}号|〔\d{4}〕\s*\d+\s*号|\[\d{4}\]\s*\d+\s*号')
ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def short_name(text):
    """去编号前缀、去括注，得短名。"""
    s = re.sub(r'^\d+(?:\.\d+)*\s*', '', text or '')
    s = re.sub(r'[（(].*?[)）]', '', s)
    s = ILLEGAL.sub('', s).strip(' .：:，,。；;')
    return s or (text or '未命名')


def tier_of(score, typ):
    """档位：详 / 标准 / 简。参见 references/tier-rules.md

    规则（与已交付版本一致，保证复跑结果可比）：
      score >= 1.0                      -> 详（高分值重点项）
      纯主观 且 score >= 0.3            -> 详（几乎全靠现场呈现）
      score >= 0.3                      -> 标准
      score < 0.3：纯客观 -> 简；其余 -> 标准

    注意：仅"纯主观"项按主观规则升档；"客观+主观"项靠材料即可取得基础分，
    若一并升档，"详"会膨胀到 50% 以上，档位失去区分度。
    """
    score = score or 0
    typ = (typ or '客观').strip()
    if score >= 1.0:
        return '详'
    if typ == '主观' and score >= 0.3:
        return '详'
    if score >= 0.3:
        return '标准'
    return '简' if typ == '客观' else '标准'


def folder_of(x):
    """构建四层归档路径：编号 = 上级编号路径 + 本层序号。

    层级编号取自 一/二/三级指标文本中的编号，末级序号取自考查要点编号的末段。
    ⚠️ 这样处理的意义：当源表末级编号有笔误（如 3.3.2.5 实为 3.2.2.5 系列）时，
    文件夹会自动归到正确的上级路径下（0302 公益项目），与交付物备注口径一致；
    若直接拼末级完整编号，会生成一个孤立在 0303 下的错误目录。
    """
    def num(code, idx):
        try:
            return int(str(code).split('.')[idx])
        except (AttributeError, IndexError, ValueError):
            return None

    n1 = num(x.get('l1_code'), 0)
    n2 = num(x.get('l2_code'), 1)
    n3 = num(x.get('l3_code'), 2)
    n4 = num(x.get('code'), 3)
    if n1 is None:
        return '未分类'
    p1 = f'{n1:02d}'
    p2 = f'{p1}{n2:02d}' if n2 is not None else None
    p3 = f'{p2}{n3:02d}' if (p2 and n3 is not None) else None
    p4 = f'{p3}{n4:02d}' if (p3 and n4 is not None) else None
    parts = [(p1, x.get('l1')), (p2, x.get('l2')), (p3, x.get('l3')), (p4, x.get('point_text'))]
    return '/'.join(f'{code}-{short_name(text)}' for code, text in parts if code) or '未分类'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--owner-map', default=None, help='自定义负责人映射 JSON（二级段→角色）')
    ap.add_argument('--org', default='')
    a = ap.parse_args()

    src_path = os.path.join(a.work, 'source_extract.json')
    data = json.load(open(src_path, encoding='utf-8'))
    rows = data['rows'] if isinstance(data, dict) else data
    meta_info = data.get('_meta', {}) if isinstance(data, dict) else {}

    owner_map = dict(DEFAULT_OWNER)
    if a.owner_map:
        owner_map.update(json.load(open(a.owner_map, encoding='utf-8')))

    out = []
    for x in rows:
        t = tier_of(x.get('score'), x.get('type'))
        basis = x.get('basis') or ''
        lawtext = x.get('lawtext') or ''
        has_clause = bool(CLAUSE.search(lawtext) or CLAUSE.search(basis))
        code = x.get('code') or ''
        l3 = x.get('l3_code') or ''
        y = dict(x)
        y.update({
            'tier': t,
            'needs_verify': not has_clause,
            'owner': owner_map.get(x.get('l2_code'), FALLBACK_OWNER),
            'folder': folder_of(x),
            'name_short': short_name(x.get('point_text')),
            'code_mismatch': bool(l3) and not code.startswith(l3 + '.'),
        })
        out.append(y)

    total = round(sum(y['score'] or 0 for y in out), 2)
    print('机构:', a.org or meta_info.get('org', ''), '| 指标版本:', meta_info.get('version', ''))
    print('items:', len(out))
    print('sum(score):', total)
    print('tiers:', dict(Counter(y['tier'] for y in out)))
    print('needs_verify(缺条款号):', sum(1 for y in out if y['needs_verify']))
    print('code_mismatch:', [(y['code'], y['l3_code']) for y in out if y['code_mismatch']])
    missing_owner = sorted({(y['l2_code'] or '?') for y in out if y['l2_code'] not in owner_map})
    if missing_owner:
        print('⚠️ 未在映射表中定义的二级段（已回退为"%s"）: %s —— 请补全映射' % (FALLBACK_OWNER, missing_owner))
    dupf = [k for k, v in Counter(y['folder'] for y in out).items() if v > 1]
    print('dup folders:', dupf)
    print('per l1:', dict(Counter(y['l1_code'] for y in out)))

    p = os.path.join(a.work, 'enriched_meta.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('saved:', p)


if __name__ == '__main__':
    main()
