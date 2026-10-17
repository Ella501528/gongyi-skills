# -*- coding: utf-8 -*-
"""物资发放台账体检 —— 八条规则（逐条见 references/判定规则索引.md）

用法:
    python check_ledger.py --input sample_data/sample_input.json --out ./台账体检报告.xlsx --threshold 5000

输入: 一份 JSON（结构见 sample_data/sample_input.json，字段即填表说明）
输出: Excel 四表 —— 汇总 / 三数对账 / 异常清单 / 待补材料

未安装 openpyxl 时自动降级为 CSV（同目录，按表分文件，内容一致）。
命中的均为【待核项】，不是违规结论，须人工确认后再写入正式报告。
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter

SEV_ORDER = {"高": 0, "中": 1, "低": 2}

RULE_NAME = {
    "M1": "三数对账不成立",
    "M2": "缺三方比价",
    "M3": "关联关系未回避",
    "M4": "入库要素缺失",
    "M5": "出库要素缺失",
    "M6": "接收方对不上名册",
    "M7": "剩余物资无处置记录",
    "M8": "数量金额异常",
}
RULE_FIX = {
    "M1": "逐笔核对出入库；差额须能说明去向",
    "M2": "补比价记录与审批；走招标/竞争性磋商的不重复要求",
    "M3": "补回避申报；涉关联方的按关联交易程序处理",
    "M4": "补齐入库要素；验收人与经办人不应为同一人",
    "M5": "补签收单；补不出的写情况说明",
    "M6": "补名册或说明资格依据；无依据的不得发放",
    "M7": "清点、登记、审批、处置并入账留档",
    "M8": "核对单据；负数多为登记口径错误，须改账",
}

IN_FIELDS = ["name", "spec", "qty_in", "unit_price", "supplier", "invoice_no", "inspection_signer"]
OUT_FIELDS = ["date", "receiver", "qty", "signer", "purpose"]


def mask_name(name):
    if not name:
        return "（未填）"
    s = str(name).strip()
    return s if len(s) <= 1 else s[0] + "×" * (len(s) - 1)


def ensure_dir(path):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def run_rules(data, threshold, tol):
    project = data.get("project", {}) or {}
    mats = data.get("materials", []) or []
    roster = set(project.get("beneficiary_ids") or [])

    issues = []       # [物资号, 名称, 规则, 严重度, 说明]
    balance = []      # [物资号, 名称, 入库, 发放合计, 剩余, 差值, 结论]

    def add(mid, mname, rule, sev, note):
        issues.append([mid, mname, rule, sev, note])

    for m in mats:
        mid = m.get("id", "")
        mname = m.get("name", "")

        outs = m.get("out_records", []) or []
        qty_out = sum((o.get("qty") or 0) for o in outs)
        qty_in = m.get("qty_in")
        qty_rem = m.get("qty_remaining")
        qty_in_v = qty_in if isinstance(qty_in, (int, float)) else 0
        qty_rem_v = qty_rem if isinstance(qty_rem, (int, float)) else 0

        # M1 三数对账
        diff = round(qty_in_v - (qty_out + qty_rem_v), 4)
        ok = (abs(diff) < 1e-6) and isinstance(qty_in, (int, float)) and isinstance(qty_rem, (int, float))
        balance.append([mid, mname, qty_in, qty_out, qty_rem, diff,
                        "对平" if ok else "不成立（入库≠发放+剩余）"])
        if not ok:
            add(mid, mname, "M1", "高",
                "入库 %s ≠ 发放 %s + 剩余 %s，差 %s" % (qty_in, qty_out, qty_rem, diff))

        # M4 入库要素缺失
        miss = [k for k in IN_FIELDS if m.get(k) in (None, "")]
        if miss:
            add(mid, mname, "M4", "中", "缺: " + "、".join(miss))

        # M2 缺三方比价
        method = m.get("procurement_method", "") or ""
        amount = m.get("amount")
        if method not in ("招标", "竞争性磋商"):
            if threshold is None:
                add(mid, mname, "M2", "中", "未设定采购额度，无法判定是否需比价")
            elif isinstance(amount, (int, float)) and amount >= threshold:
                quotes = m.get("quotes")
                if not isinstance(quotes, int) or quotes < 3:
                    add(mid, mname, "M2", "高",
                        "金额 %s ≥ 额度 %s，比价次数 %s < 3" % (amount, threshold, quotes))

        # M3 关联关系未回避
        if m.get("supplier_related_to_operator") is True:
            add(mid, mname, "M3", "高", "供应商与经办人存在关联关系，应回避")

        # M5 出库要素缺失 + M6 名册对应
        for i, o in enumerate(outs, 1):
            omit = [k for k in OUT_FIELDS if o.get(k) in (None, "")]
            if omit:
                add(mid, mname, "M5", "中", "第 %d 笔发放缺: %s" % (i, "、".join(omit)))
            rid = o.get("receiver_id")
            if rid:
                if not roster:
                    add(mid, mname, "M6", "中", "第 %d 笔：未提供受益对象名册，无法判定" % i)
                elif rid not in roster:
                    add(mid, mname, "M6", "中",
                        "第 %d 笔接收方 %s（%s）不在受益对象名册" % (i, rid, mask_name(o.get("receiver"))))

        # M7 剩余无处置
        if isinstance(qty_rem, (int, float)) and qty_rem > 0 and not m.get("remaining_disposal"):
            add(mid, mname, "M7", "高", "剩余 %s 但无处置方式或审批" % qty_rem)

        # M8 数量金额异常
        up, amt = m.get("unit_price"), m.get("amount")
        if isinstance(up, (int, float)) and isinstance(amt, (int, float)) and isinstance(qty_in, (int, float)):
            if abs(up * qty_in - amt) > tol:
                add(mid, mname, "M8", "高",
                    "单价 %s × 入库 %s = %s，与金额 %s 不符" % (up, qty_in, round(up * qty_in, 2), amt))
        if isinstance(qty_rem, (int, float)) and qty_rem < 0:
            add(mid, mname, "M8", "高", "结存为负（%s）" % qty_rem)
        if qty_out > qty_in_v:
            add(mid, mname, "M8", "高", "发放数 %s 超过入库数 %s" % (qty_out, qty_in_v))

    return issues, balance


def build_tables(issues, balance, mats):
    high = sum(1 for i in issues if i[3] == "高")
    mid = sum(1 for i in issues if i[3] == "中")
    bad_balance = sum(1 for b in balance if b[6] != "对平")

    summary = [
        ["项", "值"],
        ["物资条目数", len(mats)],
        ["三数对账", "全部对平" if bad_balance == 0 else "%d 条不成立" % bad_balance],
        ["命中总条数", len(issues)],
        ["高危条数（须人工确认）", high],
        ["中危条数", mid],
        ["体检结论", "存在高危待核项，提交前须逐条确认" if high
         else ("仅中危待核项，建议确认后放行" if mid else "未发现明显缺陷")],
        [],
        ["规则", "命中数"],
    ]
    cnt = Counter(i[2] for i in issues)
    for r in ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]:
        summary.append(["%s %s" % (r, RULE_NAME[r]), cnt.get(r, 0)])

    sheet_balance = [["物资号", "名称", "入库数", "发放合计", "剩余数", "差值", "结论"]]
    sheet_balance.extend(balance)

    issues_sorted = sorted(issues, key=lambda x: SEV_ORDER.get(x[3], 9))
    sheet_issues = [["物资号", "名称", "规则", "规则名", "严重度", "说明"]]
    for i in issues_sorted:
        sheet_issues.append([i[0], i[1], i[2], RULE_NAME[i[2]], i[3], i[4]])

    per_rule = Counter(i[2] for i in issues)
    fixes = [["规则", "需补材料", "涉及条数"]]
    for r in ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]:
        if per_rule.get(r):
            fixes.append([r + " " + RULE_NAME[r], RULE_FIX[r], per_rule[r]])

    return {"汇总": summary, "三数对账": sheet_balance, "异常清单": sheet_issues, "待补材料": fixes}


def write_xlsx(tables, out_path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    first = True
    head_fill = PatternFill("solid", fgColor="E8EEF7")
    warn_fill = PatternFill("solid", fgColor="FCE8E6")
    for name, rows in tables.items():
        ws = wb.active if first else wb.create_sheet()
        ws.title = name
        first = False
        for row in rows:
            ws.append(row)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = head_fill
            c.alignment = Alignment(vertical="center")
        if name == "三数对账":
            for r in range(2, ws.max_row + 1):
                if ws.cell(r, 7).value != "对平":
                    for cc in range(1, 8):
                        ws.cell(r, cc).fill = warn_fill
        for col in ws.columns:
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 52)
    wb.save(out_path)


def write_csv(tables, out_path):
    base, _ = os.path.splitext(out_path)
    written = []
    for name, rows in tables.items():
        p = "%s_%s.csv" % (base, name)
        ensure_dir(p)
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        written.append(p)
    return written


def main():
    ap = argparse.ArgumentParser(description="物资发放台账体检")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="./台账体检报告.xlsx")
    ap.add_argument("--threshold", type=float, default=None,
                    help="三方比价触发额度；不传则 M2 报无法判定")
    ap.add_argument("--tolerance", type=float, default=0.01)
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print("输入文件不存在: %s" % args.input)
        sys.exit(2)

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    thr = args.threshold
    if thr is None:
        thr = (data.get("project", {}) or {}).get("procurement_threshold")
        if thr == "":
            thr = None

    issues, balance = run_rules(data, thr, args.tolerance)
    tables = build_tables(issues, balance, data.get("materials", []) or [])
    ensure_dir(args.out)

    try:
        write_xlsx(tables, args.out)
        print("已生成 Excel: %s" % args.out)
    except ImportError:
        paths = write_csv(tables, args.out)
        print("未安装 openpyxl，已降级输出 CSV：")
        for p in paths:
            print("  " + p)
    bad = sum(1 for b in balance if b[6] != "对平")
    print("物资 %d 条，三数对账不成立 %d 条，命中 %d 条（高危 %d）" % (
        len(balance), bad, len(issues), sum(1 for i in issues if i[3] == "高")))
    print("说明：命中项为待核项，不是违规结论，须人工确认后写入正式报告。")


if __name__ == "__main__":
    main()
