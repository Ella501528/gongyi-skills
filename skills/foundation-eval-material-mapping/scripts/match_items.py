#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""存量材料盘点 2/4：把 inventory.json 匹配到指标末级要点，生成 match_report.json。

匹配内核（v2，倒排索引 + 词长加权 + 特异性门控）：
  1. 规则层：强规则命中决定"候选范围"（概念对口）；
  2. 词面层：用倒排索引把要点特征词反查文件，词长加权（4字=3分/3字=2分/2字=1分）；
  3. 门控：**词面分必须 >= 2** 才可能被指派——防止"这条规则覆盖 3.2 全部要点，
     于是整个业务库同时命中十几个要点"的过配（v1 的真实教训：某要点命中 1154 个文件）；
  4. 多指派：得分达到最优值 85% 的候选都保留（同一文件可支撑多个要点）；
  5. 置信度：仅"该文件的最优要点"且词面分 >= 4 且规则分 >= 3 才算 high，其余一律 medium。

状态四档：已归位 / 待确认 / 外部征询 / 缺项。
  「外部征询」用于登记管理机关评价、业务主管单位评价这类由评估机构发函取得的外部评价项，
  机构侧本就没有可交材料——不应计入缺项，也不应算作已归位。

用法：
  python match_items.py --work "<工作目录>" --inventory "<inventory.json>" --out "<工作目录>"
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# ---------------- 强规则库（详见 references/match-rules.md） ----------------
# (标签, 正则, 目标编号前缀, 权重)
STRONG_RULES = [
    ('章程', r'章程', ['1.3', '4.2'], 4),
    ('理事会/监事会/换届', r'理事|监事|换届|选举|会员大会|决议', ['1.2'], 4),
    ('审计与专项审核', r'审计|专项审核|财务审计|专项信息审核', ['1.4', '3.1', '4.2'], 4),
    ('年检与年度报告', r'年检|年度报告|年报|年度工作报告', ['4.2', '4.3', '1.4', '5.3'], 4),
    ('党建', r'党建|党组织|党支部|党员|党委|联党委|三会一课|意识形态|集体学习|主题党日', ['2.'], 4),
    ('信息公开与平台', r'信息公开|公示|慈善中国|统一信息平台|fti|中基透明', ['4.3', '5.2'], 4),
    ('传播与官网', r'官网|网站|公众号|微信|微博|抖音|小程序|媒体|报道|新闻稿|宣传|logo|二维码', ['5.1'], 3),
    ('内部制度', r'制度|管理办法|内控|内部控制|工作规则|议事规则', ['1.3', '4.4'], 3),
    ('资产与保值增值', r'资产|固定资产|保值增值|投资|理财|存货', ['1.4', '4.4'], 3),
    ('人事与用工', r'人事|人力资源|员工|工资|薪酬|社保|劳动合同|考勤', ['1.1', '1.3', '4.4'], 3),
    ('财务与票据', r'财务|会计|凭证|账簿|票据|发票|税务|报销|预算|决算|记账', ['1.4', '3.1'], 3),
    ('捐赠与募捐', r'捐赠|受赠|捐赠人|募捐|公益支出|慈善财产', ['3.1', '4.5'], 4),
    ('项目与执行', r'项目|立项|结项|执行|受益|资助|救助|活动方案', ['3.2', '3.1'], 3),
    # 机构专属规则（项目名称库、业务领域专名）不写在这里——
    # 通过 <工作目录>/extra_rules.json 注入，见 references/match-rules.md §五
    ('志愿者', r'志愿者|志愿服务|义工', ['1.3', '3.2'], 3),
    ('合作与协议', r'合作|协议|合同|战略合作|备忘录', ['3.3', '4.4'], 3),
    ('办公与证照', r'办公|用房|匾额|设备|证照|印章|档案|证书|法人证书|登记证书|统一社会信用代码', ['1.1', '4.1'], 3),
    ('重大事项与备案', r'重大事项|备案|审批|许可|变更登记', ['1.3', '4.1', '4.4'], 3),
    ('信用与表彰处罚', r'信用|失信|处罚|违法|投诉|举报|诉讼|表彰|荣誉|奖励|奖项|信用中国', ['5.3'], 4),
    ('诚信建设专项', r'诚信承诺|诚信档案|承诺书|诚信', ['5.4'], 4),
    ('国家重大任务', r'重大任务|国家重大|四个中心|乡村振兴|京津冀|重大活动|服务大局|对口支援', ['3.4'], 4),
    ('社会治理与职能转移', r'政府购买|职能转移|社会治理|承接|购买服务', ['3.4'], 3),
    ('业务领域-医疗健康', r'医疗|患者|健康|科普|学术|医学', ['3.2'], 3),
    ('业务领域-教育助学', r'教育|助学|学生|读书|奖学|红色', ['3.2'], 3),
    ('工作汇总与计划', r'汇总|计划|工作总结|年度计划|台账|清单', ['1.2', '1.4', '4.2'], 2),
]
RULES = [(lbl, re.compile(pat, re.I), pfx, w) for lbl, pat, pfx, w in STRONG_RULES]

STOP = set("""
情况 是否 开展 工作 相关 有关 以及 进行 具有 应当 落实 规范 完善 提供 包括
要求 内容 方式 材料 说明 一定 以上 以下 其中 能够 可以 必须 不得 按照 根据
通过 对于 关于 并且 或者 但是 因为 所以 如果 这些 那些 我们 他们 什么 怎么
为了 已经 正在 需要 有效 及时 充分 建立 制定 执行 到位 合理 真实 完整 相关
""".split())

TRACE_PAT = re.compile(r'纪要|记录|签到|痕迹|照片|台账|留痕|会议|活动|开展情况|执行情况|案例|成效|反馈')
# 外部征询类：材料由评估机构发函取得，机构侧无可交材料
EXTERNAL_PAT = re.compile(r'登记管理机关评价|业务主管单位评价|有关部门评价|行业评价')
# 反向证明类：要的不是"有事迹"，而是"无相关情形"的证明（无违法说明、信用中国截图等）
REVERSE_PAT = re.compile(r'违反法律法规|失信行为|司法诉讼|结案执行|被处罚|媒体披露|投诉举报|金融信用信息')
CJK = re.compile(r'[\u4e00-\u9fff]')
WINDOW = (2023, 2025)
KIND_BONUS = {'doc': 0.5, 'image': 0.0, 'video': -0.5, 'raw': -1.0, 'other': -0.5}
CAND_CAP = 20          # 每要点最多保留多少候选（防过配洪水）
OVERBROAD = 60         # 候选数超过此值视为"规则过宽"，降级处理
OVERBROAD_CAP = 15     # 过宽要点保留前 N 个作为"人工挑选建议"（一律不实体化）
TOKEN_CAP = 12.0       # 词面分上限
MIN_TOKEN = 2.0        # 词面门控：低于此分不指派
HIGH_TOKEN = 4.0       # high 置信度所需词面分

# 同义词扩展：指标用词与文件命名用词常常不同（指标说"结项"，文件叫"总结"）。
# 只在这个尺度上做同义扩展——名字对不上，匹配就永远只能靠规则前缀，无法区分管理环节。
SYNONYM = {
    '结项': ['结题', '总结', '验收', '决算', '终期', '成果'],
    '论证': ['可行性', '方案', '计划书', '立项', '申请书'],
    '申报': ['申请', '立项', '报送', '备案'],
    '执行': ['实施', '进度', '中期', '拨付', '采购', '合同', '协议'],
    '评估': ['自评', '评价', '测评', '打分'],
    '选拔': ['评选', '推荐', '审评', '评审'],
    '公开': ['公示', '披露', '发布', '公告'],
    '培训': ['学习', '研修', '讲座', '分享会'],
    '志愿': ['义工', '志愿服务'],
    '党建': ['党组织', '党支部', '党员', '党委'],
    '资助': ['拨付', '拨款', '发放', '帮扶'],
    '受益': ['受助', '服务对象', '群众', '反馈'],
    '表彰': ['荣誉', '奖励', '称号', '先进'],
    '检查': ['抽查', '督查', '巡查', '核查'],
    '换届': ['选举', '改选', '产生'],
}


def grams(text, ns=(2, 3, 4)):
    out = set()
    for n in ns:
        for i in range(len(text) - n + 1):
            g = text[i:i + n]
            if g in STOP or not CJK.search(g):
                continue
            out.add(g)
    return out


def item_tokens(x):
    """特征词只取自三级指标名 + 考查要点。
    刻意**不取二级指标名**——二级名多为通名（如"财务资产管理"），
    混进来会让"会计人员配备"这类要点也被审计报告命中。"""
    txt = '%s %s' % (x.get('l3') or '', x.get('point_text') or '')
    txt = re.sub(r'[\s（）()【】\[\]、，。；：,.;:/\-—＋+%“”"\'’‘]', '', txt)
    toks = grams(txt)
    for k, syns in SYNONYM.items():
        if k in txt:
            for s in syns:
                toks |= grams(s)
    return toks


def load_extra_rules(path):
    """机构专用规则文件（JSON 列表），字段：label / pattern / prefixes / weight。

    通用规则之外，每家机构都有自己的项目名称库、业务专名——
    这些属于客户信息，**不进专家包**，放在工作目录里随任务注入：
      <工作目录>/extra_rules.json
    """
    data = json.load(open(path, encoding='utf-8'))
    out = []
    for r in data:
        out.append((r['label'], re.compile(r['pattern'], re.I),
                    list(r['prefixes']), int(r.get('weight', 4))))
    return out


def main():
    global WINDOW
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--inventory', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--assign-min', type=float, default=4.0)
    ap.add_argument('--extra-rules', default=None,
                    help='机构专用规则 JSON 路径；缺省时自动尝试 <work>/extra_rules.json')
    ap.add_argument('--window', default='%d,%d' % WINDOW,
                    help='年度窗口（如 2023,2025＝参评年度前推三年），影响排序与置信度')
    args = ap.parse_args()

    work = args.work
    inv_p = args.inventory or os.path.join(work, 'inventory.json')
    out_dir = args.out or work

    try:
        lo, hi = [int(x) for x in re.split(r'[,\s]+', args.window) if x]
        WINDOW = (lo, hi)
    except ValueError:
        sys.exit('FAIL --window 格式应为 "2023,2025"')

    extra_p = args.extra_rules or os.path.join(work, 'extra_rules.json')
    if os.path.isfile(extra_p):
        n = 0
        for rule in load_extra_rules(extra_p):
            RULES.append(rule)
            n += 1
        print('已加载机构专用规则: %d 条 <- %s' % (n, extra_p))

    meta = json.load(open(os.path.join(work, 'enriched_meta.json'), encoding='utf-8'))
    inv = json.load(open(inv_p, encoding='utf-8'))

    items = []
    for x in meta:
        it = {
            'code': x['code'], 'l1_code': x['l1_code'], 'l2_code': x['l2_code'],
            'l3_code': x.get('l3_code'), 'l1': x.get('l1'), 'l2': x.get('l2'),
            'l3': x.get('l3'), 'point_text': x.get('point_text'),
            'score': x.get('score'), 'type': x.get('type'), 'tier': x.get('tier'),
            'folder': x['folder'],
            'trace': bool(TRACE_PAT.search(x.get('point_text') or '')),
            'external': bool(EXTERNAL_PAT.search(x.get('point_text') or '')),
            'reverse': bool(REVERSE_PAT.search(x.get('point_text') or '')),
            'tokens': item_tokens(x), 'files': [],
        }
        items.append(it)

    files = [f for f in inv['files'] if not f.get('noise') and f.get('kind') != 'partial']
    by_id = {f['id']: f for f in files}

    # ---------- 倒排索引：CJK 词 → 文件 id 集合 ----------
    t0 = time.time()
    index = defaultdict(set)
    path_of = {}
    for f in files:
        s = ('/'.join(f['dirs']) + '/' + f['name'])[:200]
        path_of[f['id']] = s
        for g in grams(s):
            index[g].add(f['id'])
    print('倒排索引: %d 词 / %d 文件，用时 %.1fs' % (len(index), len(files), time.time() - t0))

    # ---------- 规则层：规则 → 命中文件 ----------
    rule_files = {}
    for lbl, rx, pfx, w in RULES:
        ids = {f['id'] for f in files if rx.search(path_of[f['id']].lower())}
        rule_files[lbl] = ids

    # ---------- 逐要点打分 ----------
    for it in items:
        cand = defaultdict(float)
        rsc = defaultdict(float)
        tsc = defaultdict(float)
        why = defaultdict(list)
        for lbl, rx, pfx, w in RULES:
            hit = any(it['l2_code'].startswith(p) or it['code'].startswith(p)
                      or it['l1_code'] == p.rstrip('.') for p in pfx)
            if not hit:
                continue
            ids = rule_files[lbl]
            if not ids:
                continue
            for fid in ids:
                rsc[fid] += w
                why[fid].append(lbl)
        # 词面层（倒排反查）
        for t in it['tokens']:
            ids = index.get(t)
            if not ids:
                continue
            w = 3.0 if len(t) >= 4 else (2.0 if len(t) == 3 else 1.0)
            for fid in ids:
                tsc[fid] += w
        for fid in set(rsc) | set(tsc):
            tk = min(tsc.get(fid, 0.0), TOKEN_CAP)
            rs = rsc.get(fid, 0.0)
            # 门控：词面分达标，或"有词面重合 + 规则已明确指向该板块"
            if not (tk >= MIN_TOKEN or (tk >= 1.0 and rs >= 3.0)):
                continue
            f = by_id[fid]
            y = f['year']
            yok = (y is None) or (WINDOW[0] <= y <= WINDOW[1])
            cand[fid] = rsc.get(fid, 0.0) + tk + KIND_BONUS.get(f['kind'], 0.0) + (0.5 if yok else 0)
            if tk:
                why[fid].append('词面%d' % int(tk))
        if not cand:
            continue
        best = max(cand.values())
        keep = [(fid, s) for fid, s in cand.items()
                if s >= args.assign_min and s >= best * 0.85]
        keep.sort(key=lambda kv: -kv[1])
        for fid, s in keep[:CAND_CAP]:
            f = by_id[fid]
            y = f['year']
            yok = (y is None) or (WINDOW[0] <= y <= WINDOW[1])
            it['files'].append({
                'id': fid, 'abs': f['abs'], 'rel': f['rel'], 'root': f['root'],
                'name': f['name'], 'ext': f['ext'], 'kind': f['kind'],
                'size': f['size'], 'year': y, 'mtime': f['mtime'],
                'score': round(s, 2), 'token_score': round(min(tsc.get(fid, 0.0), TOKEN_CAP), 1),
                'rule_score': rsc.get(fid, 0.0),
                'why': '·'.join(dict.fromkeys(why[fid])), 'year_ok': yok,
            })
        it['candidate_total'] = len(cand)

    # ---------- 置信度：只给该文件的最优要点 ----------
    best_of = defaultdict(lambda: (None, -1.0))
    for it in items:
        for r in it['files']:
            if r['score'] > best_of[r['id']][1]:
                best_of[r['id']] = (it['code'], r['score'])
    for it in items:
        ob = it.get('candidate_total', 0) > OVERBROAD
        for r in it['files']:
            is_best = best_of[r['id']][0] == it['code']
            r['confidence'] = ('high'
                               if is_best and not ob
                               and r['token_score'] >= HIGH_TOKEN and r['rule_score'] >= 3
                               else 'medium')
        it['overbroad'] = ob

    for it in items:
        it['files'].sort(key=lambda r: (-r['score'], r['kind'] != 'doc'))
        hi = sum(1 for r in it['files'] if r['confidence'] == 'high')
        it['high_count'] = hi
        it['matched_count'] = len(it['files'])
        it['matched_size'] = sum(r['size'] for r in it['files'])
        it['kinds'] = dict(Counter(r['kind'] for r in it['files']))
        if it['external']:
            it['status'] = '外部征询'
        elif hi:
            it['status'] = '已归位'
        elif it['files']:
            it['status'] = '待确认'
        else:
            it['status'] = '缺项'
        del it['tokens']

    st = Counter(it['status'] for it in items)
    cov = (st['已归位'] + st['待确认']) / float(len(items)) * 100
    per_l1 = defaultdict(Counter)
    for it in items:
        per_l1['%s %s' % (it['l1_code'], it['l1'])][it['status']] += 1
    flood = [(it['code'], it['candidate_total']) for it in items
             if it.get('candidate_total', 0) > 60]

    rep = {
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'inventory_file': inv_p,
        'items': items,
        'summary': {
            'items': len(items), 'status': dict(st),
            'coverage_pct': round(cov, 1),
            'files_considered': len(files),
            'per_l1': {k: dict(v) for k, v in per_l1.items()},
            'overbroad_items': flood,
        },
    }
    os.makedirs(out_dir, exist_ok=True)
    outp = os.path.join(out_dir, 'match_report.json')
    with open(outp, 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, ensure_ascii=False)

    print('')
    print('要点总数: %d' % len(items))
    print('已归位: %d   待确认: %d   外部征询: %d   缺项: %d'
          % (st['已归位'], st['待确认'], st['外部征询'], st['缺项']))
    print('覆盖率（已归位+待确认）: %.1f%%' % cov)
    print('参与匹配文件: %d' % len(files))
    print('')
    print('按一级指标：')
    for k, v in per_l1.items():
        print('  %-22s 已归位%3d 待确认%3d 外部%2d 缺项%3d / %d 项'
              % (k, v['已归位'], v['待确认'], v['外部征询'], v['缺项'], sum(v.values())))
    if flood:
        print('')
        print('⚠ 候选数异常（>%d，规则过宽 → 已降级：仅留前 %d 个且不判 high，需人工指定）:'
              % (OVERBROAD, OVERBROAD_CAP))
        for c, n in sorted(flood, key=lambda x: -x[1])[:8]:
            print('  %-10s %d 个候选' % (c, n))
    gaps = sorted([i for i in items if i['status'] == '缺项'],
                  key=lambda i: -(i['score'] or 0))
    print('')
    print('缺项 TOP10（按分值，优先补料）：')
    for i in gaps[:10]:
        print('  %-10s %4s分 %-8s %s' % (i['code'], i['score'], '痕迹类' if i['trace'] else '材料类',
                                         (i['point_text'] or '')[:32]))
    print('')
    print('OK  已写出 %s' % outp)
    return 0


if __name__ == '__main__':
    sys.exit(main())
