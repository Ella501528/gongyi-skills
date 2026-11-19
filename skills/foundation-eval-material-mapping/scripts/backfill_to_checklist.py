# -*- coding: utf-8 -*-
"""第 6 步：把「归位结果」回填到自评资料准备清单主表。

在主表【电子版自评资料清单】右侧新增三列，让使用者一眼看到
「这个文件夹里现在放了什么 / 对不对 / 还缺什么」：

  列A 当前文件夹内已有资料（存量已放入）  —— 文件名（大小），逐行列出
  列B 存量归位状态                        —— 已归位 / 待人工确认 / 缺项 / 外部征询
  列C 尚缺/待处理提示                     —— 下一步做什么、⚠同名多版本

用法：
  # 预演（默认）：只生成 CSV 与核对报告，不动 xlsx
  python backfill_to_checklist.py --work <工作目录> --archive <归档根> --xlsx <清单.xlsx>

  # 写入（会先自动备份 xlsx）
  python backfill_to_checklist.py --work <工作目录> --archive <归档根> --xlsx <清单.xlsx> --insert

前提：placement_plan.json、缺项清单.csv、同名多版本清单.csv 已由前五步产出；
     归档树已完成实体化（本脚本以**磁盘实际内容**为准，而非计划清单）。
"""
import argparse, csv, json, shutil, sys, re, collections, datetime
from pathlib import Path

SKIP_NAMES = {'说明.md', '取材指针.md', '00-总说明.md'}


# ---------------- 数据采集 ----------------
def human(n):
    return f'{n / 1024 / 1024:.1f}MB' if n >= 1024 * 1024 else f'{max(1, round(n / 1024))}KB'


def collect(archive: Path, plan_items):
    """以磁盘终态采集每个末级文件夹内的实际文件。"""
    out = []
    for it in plan_items:
        d = archive / it['folder']
        files = []
        if d.exists():
            for p in sorted(d.iterdir()):
                if p.is_file() and p.name not in SKIP_NAMES:
                    files.append((p.name, p.stat().st_size))
        out.append((it, files, (d / '取材指针.md').exists()))
    return out


def build_rows(collected, dup_by_code, gap_note):
    rows, stat = [], collections.Counter()
    for it, files, has_pointer in collected:
        code, n, st = it['code'], len(files), it['status']

        col_a = ('\n'.join(f'{nm}（{human(sz)}）' for nm, sz in files)
                 if files else '（暂无——本文件夹尚未放入存量材料）')

        if st == '已归位':
            col_b = f'已归位：已放入 {n} 个文件'; stat['已归位(有文件)'] += 1
        elif st == '待确认':
            if n:
                col_b = f'部分归位：已放入 {n} 个文件；其余存量候选是否采用需人工判断'
                stat['待确认(有文件)'] += 1
            else:
                col_b = '未放入：存量中有候选材料，但是否对应本要点需人工挑选'
                stat['待确认(无文件)'] += 1
        elif st == '缺项':
            col_b = '缺项：现有存量资料中未找到对应材料'; stat['缺项'] += 1
        elif st == '外部征询':
            col_b = '外部征询：属外部评价/第三方出具类，机构侧无需备料'; stat['外部征询'] += 1
        else:
            col_b = st

        tips = []
        if st == '缺项':
            what, how = gap_note.get(code, ('', ''))
            tips.append('需新备：' + (what or '存量未命中对应材料'))
            if how:
                tips.append(how)
            tips.append('请按【电子版自评资料清单】准备后放入本文件夹。')
        elif st == '外部征询':
            tips.append((f'属外部评价类材料，机构侧原则上无需专门备料（由评估方或第三方出具）；'
                         f'本文件夹内已放入存量命中的 {n} 个文件，可作佐证，请核对是否与本要点口径一致。')
                        if n else
                        '无需机构侧备料；如需留存，可放入向第三方征询的记录或对方出具的证明。')
        elif st == '已归位':
            tips.append(f'已有 {n} 个文件，请逐一核对文件名与【电子版自评资料清单】要求是否一致；'
                        '覆盖年度是否满足（财务/项目/报告类默认 2023—2025 年度）。')
        else:
            if it.get('overbroad'):
                tips.append(f'本要点范围较宽（存量候选 {it.get("candidate_total", 0)} 个），'
                            '程序未自动放入，需人工挑选。')
            if has_pointer:
                tips.append('打开本文件夹内《取材指针.md》，其中列出存量的候选材料及原始位置，'
                            '挑中后自行复制进本文件夹。')
            elif n == 0:
                tips.append('存量中未见明显匹配材料，请按【电子版自评资料清单】新备。')
            if n:
                tips.append(f'已放入的 {n} 个文件是存量自动命中的，仍需人工确认是否符合本要点口径。')

        dup = sorted(dup_by_code.get(code, []))
        if dup:
            shown = '；'.join(dup[:3]) + ('等' if len(dup) > 3 else '')
            tips.append(f'⚠ 同名多版本：{shown}，请确认归档的为最新且最完整版本。')

        rows.append({'指标编号': code,
                     '当前文件夹内已有资料（存量已放入）': col_a,
                     '存量归位状态': col_b,
                     '尚缺/待处理提示': '\n'.join(tips)})
    return rows, stat


# ---------------- 写入 xlsx ----------------
def _shift_ref(ref, at_col, amount):
    """把 A1 引用中列号 >= at_col 的部分右移 amount（1-based 列号）。
       结构操作（插列）后，筛选范围与数据验证不会自动跟随，须手工迁移。"""
    def one(cell):
        m = re.match(r'^(\$?)([A-Z]{1,3})(\$?)(\d+)$', cell.strip())
        if not m:
            return cell
        d1, col, d2, row = m.groups()
        idx = 0
        for ch in col:
            idx = idx * 26 + (ord(ch) - 64)
        if idx >= at_col:
            idx += amount
        letters = ''
        while idx:
            idx, r = divmod(idx - 1, 26)
            letters = chr(65 + r) + letters
        return f'{d1}{letters}{d2}{row}'
    if ':' in ref:
        a, b = ref.split(':', 1)
        return f'{one(a)}:{one(b)}'
    return one(ref)


def insert_into_xlsx(xlsx, sheet_name, anchor, rows, keys, backup=True, body_font='微软雅黑'):
    try:
        import openpyxl
    except ImportError:
        raise SystemExit('写入 xlsx 需要 openpyxl（pip install openpyxl）；'
                         '或先只跑预演模式生成 CSV。')
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.worksheet.cell_range import MultiCellRange
    from openpyxl.utils import get_column_letter

    if backup:
        bak = Path(xlsx).with_name(f'{Path(xlsx).stem}_回填前备份_{datetime.date.today():%Y%m%d}.xlsx')
        if not bak.exists():
            shutil.copy2(xlsx, bak)
        print('备份：', bak)

    wb = openpyxl.load_workbook(xlsx)
    ws = wb[sheet_name]

    anchor_col = None
    for c in range(1, ws.max_column + 1):
        if ws.cell(1, c).value == anchor:
            anchor_col = c
            break
    if anchor_col is None:
        raise SystemExit(f'未找到锚点列「{anchor}」，请用 --anchor 指定')
    at = anchor_col + 1

    old_w = {i: ws.column_dimensions[get_column_letter(i)].width for i in range(1, ws.max_column + 1)}
    ws.insert_cols(at, len(keys))

    # 列宽重排（insert_cols 不迁移列宽）
    new_w = list(old_w.values())[:at - 1] + [46, 26, 46] + list(old_w.values())[at - 1:]
    for i, w in enumerate(new_w, 1):
        if w:
            ws.column_dimensions[get_column_letter(i)].width = w

    HDR_FILL = PatternFill('solid', fgColor='305496')
    HDR_FONT = Font(name=body_font, size=10, bold=True, color='FFFFFF')
    BODY = Font(name=body_font, size=10)
    WRAP = Alignment(wrap_text=True, vertical='top')
    CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
    THIN = Border(*[Side(style='thin', color='BFBFBF')] * 4)
    BANDS = {'1': 'EEF4FB', '2': 'FBF3EE', '3': 'EFF8F1', '4': 'F7F0FA', '5': 'FBF9E8'}

    for j, k in enumerate(keys):
        c = ws.cell(1, at + j, k)
        c.fill, c.font, c.alignment, c.border = HDR_FILL, HDR_FONT, CENTER, THIN

    last = 1
    for i, r in enumerate(rows):
        rr = i + 2
        band = BANDS.get(str(r.get('_l1', '1'))[0], 'FFFFFF')
        for j, k in enumerate(keys):
            c = ws.cell(rr, at + j, r[k])
            c.font, c.alignment, c.border = BODY, WRAP, THIN
            c.fill = PatternFill('solid', fgColor=band)
        last = rr

    # 合计行 / 数据验证 / 筛选
    total_row = last + 1
    for j in range(len(keys)):
        c = ws.cell(total_row, at + j)
        c.border = THIN
        c.fill = PatternFill('solid', fgColor='D9E1F2')
    if ws.auto_filter.ref:
        ws.auto_filter.ref = _shift_ref(ws.auto_filter.ref, at, len(keys))
    for dv in ws.data_validations.dataValidation:
        dv.sqref = MultiCellRange(','.join(_shift_ref(str(r), at, len(keys))
                                           for r in str(dv.sqref).split()))
    wb.save(xlsx)
    print(f'已写入 {sheets_msg(ws, at, keys)}')


def sheets_msg(ws, at, keys):
    from openpyxl.utils import get_column_letter
    return (f'{ws.title}：新增 {len(keys)} 列（{get_column_letter(at)}~'
            f'{get_column_letter(at + len(keys) - 1)}）')


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True, help='工作目录（含 placement_plan.json 等）')
    ap.add_argument('--archive', required=True, help='归档根目录（自评资料归档）')
    ap.add_argument('--xlsx', required=True, help='自评资料准备清单（分发版）.xlsx')
    ap.add_argument('--sheet', default='自评资料准备清单')
    ap.add_argument('--anchor', default='电子版自评资料清单', help='在其右侧插入新列')
    ap.add_argument('--insert', action='store_true', help='真正写入 xlsx（默认只出 CSV）')
    ap.add_argument('--no-backup', action='store_true')
    a = ap.parse_args()

    W, A = Path(a.work), Path(a.archive)
    plan = json.load(open(W / 'placement_plan.json', encoding='utf-8'))
    items = plan['items']

    L1 = {it['code']: it['l1'] for it in items}
    collected = collect(A, items)

    dup_by_code = collections.defaultdict(set)
    fp = W / '同名多版本清单.csv'
    if fp.exists():
        for row in csv.DictReader(open(fp, encoding='utf-8-sig')):
            for code in row['对应指标编号'].split('、'):
                if code.strip():
                    dup_by_code[code.strip()].add(row['文件名'].strip())

    gap_note = {}
    gp = W / '缺项清单.csv'
    if gp.exists():
        for row in csv.DictReader(open(gp, encoding='utf-8-sig')):
            gap_note[row['指标编号'].strip()] = (row.get('缺什么', '').strip(),
                                                 row.get('补充要点', '').strip())

    rows, stat = build_rows(collected, dup_by_code, gap_note)
    for r in rows:
        r['_l1'] = L1[r['指标编号']]

    keys = ['当前文件夹内已有资料（存量已放入）', '存量归位状态', '尚缺/待处理提示']
    out = W / '主表_存量材料列.csv'
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['指标编号'] + keys, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)

    tot = sum(len(fs) for _, fs, _ in collected)
    print(f'要点 {len(rows)} 项 | 已放入实体文件 {tot} 个 | 空文件夹 '
          f'{sum(1 for r in rows if r[keys[0]].startswith("（暂无"))} 项')
    print('状态分布：', dict(stat))
    print('已写出：', out)

    if a.insert:
        insert_into_xlsx(a.xlsx, a.sheet, a.anchor, rows, keys, backup=not a.no_backup)
    else:
        print('（预演模式：未改 xlsx。确认无误后加 --insert 写入）')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
