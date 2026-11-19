#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""存量材料盘点 3/4：生成归位计划并按指定模式就位。

三种模式：
  index —— 只在归档文件夹内写「取材指针.md」，指向原文件（默认，零占用）
  link  —— 同盘硬链接（零占用，跨盘会失败并自动降级为 index）
  copy  —— 真实复制（体积翻倍，必须先看体积预演再 --execute）

载体政策（防止 37G 媒体灌爆归档树）：
  raw（CR2 等底片）—— 永不实体化，仅登记指针
  video —— 单文件 <= --max-video-mb 且每项最多 --max-video-per-item 个
  image —— 单文件 <= --max-image-mb 且每项最多 --max-image-per-item 张
  doc   —— 每项最多 --max-doc-per-item 个，年度在窗口内优先

默认 dry-run：只输出体积预演与计划，不动任何文件。真正执行需显式 --execute。

用法：
  python place_files.py --work "<工作目录>" --archive "<归档根>" --mode copy
  python place_files.py --work "<工作目录>" --archive "<归档根>" --mode copy --execute
"""
import argparse
import csv
import json
import os
import shutil
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HEAD_GAP = ['指标编号', '一级指标', '二级指标', '三级指标', '考查要点', '分值', '类型',
            '材料性质', '建议负责人', '对应文件夹', '缺什么', '补充要点']
HEAD_REVIEW = ['指标编号', '考查要点', '分值', '候选文件数', '候选总数', '最高分', '命中来源',
               '类别标注', '候选文件（前5）', '对应文件夹', '处置建议']


def human(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return '%.2f%s' % (n, unit)
        n /= 1024.0


def pick(item, inv_by_id, ap):
    """按载体政策挑选要实体化的文件。返回 (materialize, index_only)"""
    mat, idx = [], []
    if item.get('overbroad'):
        # 候选过量 → 机器无法判别对口性。此时**一律不实体化**：
        # 放几个"看起来相关"的文件进归档树，只会制造"材料已齐"的假象。
        # 改为全部登记在取材指针里，交人工从原始库挑选。
        idx.extend((r, '规则过宽·需人工挑选') for r in item['files'])
        return mat, idx
    docs = [r for r in item['files'] if r['kind'] == 'doc']
    imgs = [r for r in item['files'] if r['kind'] == 'image']
    vids = [r for r in item['files'] if r['kind'] == 'video']
    raws = [r for r in item['files'] if r['kind'] == 'raw']
    others = [r for r in item['files'] if r['kind'] == 'other']
    partials = [r for r in item['files'] if r['kind'] == 'partial']

    def rank(rs):
        # year_ok 由 match_items.py 写入；缺省按"年度不在窗口"处理，避免上游字段缺失直接崩溃
        return sorted(rs, key=lambda r: (not r.get('year_ok', False), r['kind'] != 'doc',
                                         -r.get('score', 0), r.get('name', '')))

    for r in rank(docs)[:ap.max_doc_per_item]:
        if r['size'] <= ap.max_doc_mb * 1024 * 1024:
            mat.append(r)
        else:
            idx.append((r, '文件过大(>%dMB)，仅登记' % ap.max_doc_mb))
    for r in rank(imgs)[:ap.max_image_per_item]:
        if r['size'] <= ap.max_image_mb * 1024 * 1024:
            mat.append(r)
        else:
            idx.append((r, '图片过大(>%dMB)，仅登记' % ap.max_image_mb))
    idx.extend((r, '超出每项 %d 张上限，仅登记' % ap.max_image_per_item)
               for r in rank(imgs)[ap.max_image_per_item:])
    for r in rank(vids)[:ap.max_video_per_item]:
        if r['size'] <= ap.max_video_mb * 1024 * 1024:
            mat.append(r)
        else:
            idx.append((r, '视频过大(>%dMB)，仅登记' % ap.max_video_mb))
    idx.extend((r, '超出每项 %d 个上限，仅登记' % ap.max_video_per_item)
               for r in rank(vids)[ap.max_video_per_item:])
    idx.extend((r, '原始底片不实体化，保留原片') for r in raws)
    idx.extend((r, '非证据类文件，仅登记') for r in others)
    idx.extend((r, '未下载完成/临时文件，不实体化') for r in partials)
    return mat, idx


def safe_name(name):
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--archive', required=True, help='归档根目录（应已存在）')
    ap.add_argument('--match', default=None)
    ap.add_argument('--mode', choices=['index', 'link', 'copy'], default='index')
    ap.add_argument('--execute', action='store_true', help='真正执行；不带则为体积预演')
    ap.add_argument('--max-doc-per-item', type=int, default=25)
    ap.add_argument('--max-doc-mb', type=int, default=150)
    ap.add_argument('--max-image-per-item', type=int, default=4)
    ap.add_argument('--max-image-mb', type=int, default=8)
    ap.add_argument('--max-video-per-item', type=int, default=1)
    ap.add_argument('--max-video-mb', type=int, default=60)
    args = ap.parse_args()

    ap_ = args
    work = args.work
    rep = json.load(open(args.match or os.path.join(work, 'match_report.json'), encoding='utf-8'))
    inv = json.load(open(os.path.join(work, 'inventory.json'), encoding='utf-8'))
    inv_by_id = {f['id']: f for f in inv['files']}
    arch = os.path.abspath(args.archive)
    if not os.path.isdir(arch):
        print('FAIL 归档根目录不存在: %s' % arch)
        return 1

    src_roots = [os.path.abspath(r['path']) for r in inv['roots']]
    for sr in src_roots:
        if arch == sr or arch.startswith(sr + os.sep):
            print('FAIL 归档根目录位于扫描源目录内部，会造成递归复制: %s' % arch)
            return 1

    plan = []
    tot_size = 0
    tot_mat = 0
    tot_idx = 0
    per_l1 = defaultdict(lambda: [0, 0])
    skip_reason = defaultdict(int)

    for item in rep['items']:
        mat, idx = pick(item, inv_by_id, ap_)
        target = os.path.join(arch, item['folder'])
        size = sum(r['size'] for r in mat)
        tot_size += size
        tot_mat += len(mat)
        tot_idx += len(idx)
        per_l1[item['l1']][0] += len(mat)
        per_l1[item['l1']][1] += size
        for r, why in idx:
            skip_reason[why.split('(')[0]] += 1
        plan.append({
            'code': item.get('code'), 'l1': item.get('l1'), 'l2': item.get('l2'), 'l3': item.get('l3'),
            'point_text': item.get('point_text'), 'score': item.get('score'), 'type': item.get('type'),
            'status': item.get('status'), 'target': target, 'folder': item.get('folder'),
            'trace': item.get('trace', False),
            'overbroad': item.get('overbroad', False),
            'reverse': item.get('reverse', False),
            'external': item.get('external', False),
            'candidate_total': item.get('candidate_total', 0),
            'materialize': [{k: r.get(k) for k in ('abs', 'rel', 'root', 'name', 'kind', 'size', 'year', 'score', 'confidence', 'why')} for r in mat],
            'index_only': [dict({k: r.get(k) for k in ('abs', 'rel', 'root', 'name', 'kind', 'size', 'year', 'score', 'confidence')}, note=why) for r, why in idx],
        })

    os.makedirs(work, exist_ok=True)
    plan_p = os.path.join(work, 'placement_plan.json')
    with open(plan_p, 'w', encoding='utf-8') as fh:
        json.dump({'mode': args.mode, 'archive': arch, 'items': plan,
                   'totals': {'materialize_files': tot_mat, 'index_only_files': tot_idx,
                              'materialize_size': tot_size,
                              'materialize_size_human': human(tot_size)}}, fh, ensure_ascii=False)

    # ---------- 体积预演报告 ----------
    lines = []
    lines.append('# 归位体积预演' + ('（已执行）' if args.execute else '（未执行·预演）'))
    lines.append('')
    lines.append('| 项目 | 数值 |')
    lines.append('|---|---|')
    lines.append('| 就位模式 | %s |' % args.mode)
    lines.append('| 实体化文件数 | %d |' % tot_mat)
    lines.append('| 实体化体积 | %s |' % human(tot_size))
    lines.append('| 仅登记指针的文件数 | %d |' % tot_idx)
    lines.append('| 归档根目录 | `%s` |' % arch)
    lines.append('')
    lines.append('## 分板块体积')
    lines.append('')
    lines.append('| 一级指标 | 实体化文件 | 体积 |')
    lines.append('|---|---|---|')
    for k, (n, s) in per_l1.items():
        lines.append('| %s | %d | %s |' % (k, n, human(s)))
    lines.append('')
    lines.append('## 未实体化原因分布')
    lines.append('')
    lines.append('| 原因 | 数量 |')
    lines.append('|---|---|')
    for k, v in sorted(skip_reason.items(), key=lambda kv: -kv[1]):
        lines.append('| %s | %d |' % (k, v))
    lines.append('')
    if args.mode == 'copy':
        lines.append('> 复制会占用约 **%s** 额外磁盘空间。执行前请确认目标盘剩余容量。' % human(tot_size))
    lines.append('')
    rp = os.path.join(work, '归位体积预演.md')
    with open(rp, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))

    print('就位模式: %s    执行: %s' % (args.mode, '是' if args.execute else '否（预演）'))
    print('实体化: %d 个文件 / %s' % (tot_mat, human(tot_size)))
    print('仅登记: %d 个文件' % tot_idx)
    print('')
    print('分板块：')
    for k, (n, s) in per_l1.items():
        print('  %-22s %4d 个  %s' % (k, n, human(s)))
    print('')
    print('未实体化原因：')
    for k, v in sorted(skip_reason.items(), key=lambda kv: -kv[1]):
        print('  %-24s %d' % (k, v))
    print('')
    print('OK  预演报告: %s' % rp)
    print('OK  就位计划: %s' % plan_p)

    # ---------- 缺口清单 ----------
    def write_csv(name, head, rows):
        # 列数守卫：表头与数据行必须严格等长，否则 CSV 会整行错位，
        # 负责人拿到的是"列对不上号"的废表，且这种错误肉眼极难发现。
        for i, r in enumerate(rows):
            if len(r) != len(head):
                print('FAIL %s 第 %d 行数据列数 %d ≠ 表头列数 %d，拒绝写出'
                      % (name, i + 1, len(r), len(head)))
                return None
        p = os.path.join(work, name)
        with open(p, 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(head)
            w.writerows(rows)
        return p

    meta_p = os.path.join(work, 'enriched_meta.json')
    if os.path.isfile(meta_p):
        try:
            meta = {x['code']: x for x in json.load(open(meta_p, encoding='utf-8'))}
        except Exception:
            print('WARN: enriched_meta.json 解析失败，负责人列留空', file=sys.stderr)
            meta = {}
    else:
        print('WARN: 未找到 enriched_meta.json（指标拆解产物），负责人列留空', file=sys.stderr)
        meta = {}
    gap_rows, rev_rows = [], []
    for item in plan:
        m = meta.get(item['code'], {})
        if item['status'] == '缺项':
            gap_rows.append([
                item['code'], item['l1'], item['l2'], item['l3'], item['point_text'],
                item['score'], item['type'], '执行痕迹类' if item['trace'] else '材料类',
                m.get('owner', ''), item['folder'],
                '执行痕迹缺失，需补活动记录/纪要/签到/照片' if item['trace'] else '对应材料未在存量中找到',
                '按清单准备并放入本文件夹；可参考同行模板',
            ])
        elif item['status'] == '待确认':
            cands = item['materialize'] + item['index_only']
            tags = []
            if item.get('overbroad'):
                tags.append('规则过宽')
            if item.get('reverse'):
                tags.append('反向证明类')
            if item.get('external'):
                tags.append('外部征询类')
            if item['trace']:
                tags.append('痕迹类')
            if item.get('overbroad'):
                sug = ('候选过量(%d)，机器无法判断对口性——请人工从原始库挑选；'
                       '建议在 match-rules.md §四 补本机构专有关键词后重跑' % item['candidate_total'])
            elif item.get('reverse'):
                sug = ('此类为"无相关情形"的反向自证：正确材料是《无违法/失信情形说明》+ 信用中国'
                       '查询截图，而不是把普通文件放进来')
            elif item.get('external'):
                sug = '外部评价类，由评估机构发函征询；机构侧只需日常合规与沟通留痕，无需自备材料'
            else:
                sug = '人工核对是否对口；对口则改判已归位，不对口则该文件移出并补料'
            rev_rows.append([
                item['code'], item['point_text'], item['score'], len(cands),
                item['candidate_total'], max([c['score'] for c in cands], default=0),
                '；'.join(sorted({c.get('why', '') for c in cands if c.get('why')}))[:80],
                '·'.join(tags) if tags else '—',
                ' / '.join('%s（%s）' % (c['name'], c.get('confidence')) for c in cands[:5]),
                item['folder'], sug,
            ])
    gp = write_csv('缺项清单.csv', HEAD_GAP, gap_rows)
    rvp = write_csv('待人工确认清单.csv', HEAD_REVIEW, rev_rows)
    if gp is None or rvp is None:
        return 1

    if not args.execute:
        print('')
        print('== 未执行任何文件操作。确认体积后追加 --execute 重跑 ==')
        return 0

    # ---------- 执行 ----------
    copied = failed = 0
    for item in plan:
        tdir = item['target']
        if not item['materialize'] and not item['index_only']:
            continue
        os.makedirs(tdir, exist_ok=True)
        used = set()
        for r in item['materialize']:
            dst = os.path.join(tdir, r['name'])
            base, ext = os.path.splitext(r['name'])
            n = 1
            while os.path.normcase(dst) in used or os.path.exists(dst):
                dst = os.path.join(tdir, '%s_%02d%s' % (base, n, ext))
                n += 1
            used.add(os.path.normcase(dst))
            try:
                if args.mode == 'copy':
                    if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(r['abs'])):
                        continue
                    shutil.copy2(r['abs'], dst)
                elif args.mode == 'link':
                    try:
                        os.link(r['abs'], dst)
                    except OSError:
                        shutil.copy2(r['abs'], dst)
                copied += 1
            except Exception as e:
                failed += 1
                print('  WARN 复制失败 %s: %s' % (r['abs'], e))
        # 取材指针
        pl = ['# 取材指针 · %s' % item['code'], '',
              '- 考查要点：%s' % item['point_text'],
              '- 分值/类型：%s 分 / %s' % (item['score'], item['type']),
              '- 状态：%s' % item['status'],
              '- 本文件夹内实体化文件：%d 个' % len(item['materialize']), '']
        if item['materialize']:
            pl.append('## 已就位')
            pl.append('')
            for r in item['materialize']:
                pl.append('- `%s`（%s，%s）← 原件：`%s`' % (r['name'], r['kind'], r['year'] or '年度未标注', r['abs']))
            pl.append('')
        if item['index_only']:
            pl.append('## 仅登记（未实体化）')
            pl.append('')
            for r in item['index_only']:
                pl.append('- `%s`（%s）← `%s`　〔%s〕' % (r['name'], r['kind'], r['abs'], r['note']))
            pl.append('')
        open(os.path.join(tdir, '取材指针.md'), 'w', encoding='utf-8').write('\n'.join(pl))


    print('')
    print('执行完成：复制/链接 %d 个文件，失败 %d 个' % (copied, failed))
    print('OK  缺项清单: %s（%d 项）' % (gp, len(gap_rows)))
    print('OK  待确认清单: %s（%d 项）' % (rvp, len(rev_rows)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
