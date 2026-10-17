# -*- coding: utf-8 -*-
"""合作方准入与协议体检 —— 八条规则（逐条见 references/判定规则索引.md）

用法:
    python check_partner.py --input sample_data/sample_input.json --out ./合作方体检报告.xlsx

输入: 一份 JSON，合作方清单 partners（结构见 sample_data/sample_input.json）
输出: Excel 四表 —— 汇总 / 合作方明细 / 异常清单 / 待补材料

未安装 openpyxl 时自动降级为 CSV（同目录，按表分文件，内容一致）。
命中的均为【待核项】，不是违规结论，须人工确认。
本技能不替代法律意见；重大、复杂合作应请专业律师判断。

聚焦：慈善组织作为受赠/运营方与外部合作方（企业/社会组织/事业单位/个人）的合作。
合作【募捐】的专门合规见另一技能 gongyi-cofundraising-check。
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter

SEV_ORDER = {"高": 0, "中": 1, "低": 2}

RULE_NAME = {
    "P1": "未做主体资格或资质核验",
    "P2": "商业公司作为受益方或受资助方",
    "P3": "未签书面协议",
    "P4": "协议要素缺失",
    "P5": "未定期对账",
    "P6": "涉关联关系未按关联交易程序处理",
    "P7": "联合宣传口径未确认或超范围",
    "P8": "未做合作方评估或无评估结论",
}
RULE_FIX = {
    "P1": "补核主体资格与专业资质并留证",
    "P2": "调整合作性质或角色；实质为资助的须重新审视合规性",
    "P3": "补签书面协议",
    "P4": "补齐权责、资金走向、成果归属、宣传口径",
    "P5": "按协议节点对账并留确认记录",
    "P6": "转关联交易程序（回避、审查、披露）",
    "P7": "发布前送机构确认；超范围内容及时更正",
    "P8": "补评估，形成续约/有条件续约/不续约的明确结论",
}
AGREEMENT_REQUIRED = ["权责", "资金走向", "成果归属", "宣传口径"]

# 报告里对机构名做轻度处理：保留姓氏式首字，其余打码（避免体检报告流转时外泄）
def mask_org(name):
    if not name:
        return "（未填）"
    s = str(name).strip()
    return s if len(s) <= 2 else s[0] + "×" * (len(s) - 1)


def ensure_dir(path):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def run_rules(data, org_has_public_fundraising):
    partners = data.get("partners", []) or []
    issues = []   # [合作方号, 名称, 规则, 严重度, 说明]
    detail = []

    def add(pid, pname, rule, sev, note):
        issues.append([pid, pname, rule, sev, note])

    for p in partners:
        pid = p.get("id", "")
        pname = mask_org(p.get("name", ""))
        ptype = p.get("type", "")
        role = p.get("role", "")

        # P1 资质核验
        if not p.get("qualification_verified", False):
            add(pid, pname, "P1", "高", "未核主体资格/专业资质")

        # P2 商业公司作为受益方/受资助方
        if ptype == "企业" and role in ("受资助方", "受益方"):
            add(pid, pname, "P2", "高", "企业不得作为受益方或受资助方（当前角色：%s）" % role)

        # P3 协议
        if not p.get("agreement_signed", False):
            add(pid, pname, "P3", "高", "未签书面协议")
        else:
            # P4 要素
            miss = [f for f in AGREEMENT_REQUIRED if f not in (p.get("agreement_fields") or [])]
            if miss:
                add(pid, pname, "P4", "中", "协议缺要素: " + "、".join(miss))

        # P5 对账
        if not p.get("reconciled", False):
            add(pid, pname, "P5", "中", "未见定期对账记录")

        # P6 关联关系
        if p.get("is_related_party") and not p.get("related_party_handled", False):
            add(pid, pname, "P6", "高", "涉关联关系但未按关联交易程序处理")

        # P7 宣传口径
        if (not p.get("publicity_confirmed", True)) or (p.get("publicity_scope_ok", True) is False):
            add(pid, pname, "P7", "中", "联合宣传口径未确认或超范围使用机构名义")

        # P8 评估
        if not p.get("evaluated", False) or not str(p.get("evaluation_conclusion", "")).strip():
            add(pid, pname, "P8", "低", "未做评估或无评估结论")

        detail.append([pid, pname, ptype, role,
                       "是" if p.get("qualification_verified") else "否",
                       "是" if p.get("agreement_signed") else "否",
                       "是" if p.get("reconciled") else "否",
                       "是" if p.get("is_related_party") else "否",
                       "是" if p.get("evaluated") else "否",
                       p.get("evaluation_conclusion", "")])

    return issues, detail


def build_tables(issues, detail, partners):
    high = sum(1 for i in issues if i[3] == "高")
    mid = sum(1 for i in issues if i[3] == "中")
    low = sum(1 for i in issues if i[3] == "低")

    summary = [
        ["项", "值"],
        ["合作方数", len(partners)],
        ["命中总条数", len(issues)],
        ["高危条数（须人工确认）", high],
        ["中危条数", mid],
        ["低危条数（待办）", low],
        ["体检结论", "存在高危待核项，合作前须逐条确认" if high
         else ("仅中低危待核项，建议确认后放行" if (mid or low) else "未发现明显缺陷")],
        [],
        ["规则", "命中数"],
    ]
    cnt = Counter(i[2] for i in issues)
    for r in ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]:
        summary.append(["%s %s" % (r, RULE_NAME[r]), cnt.get(r, 0)])

    sheet_detail = [["合作方号", "名称", "主体类型", "角色", "资质已核", "已签协议",
                     "已对账", "涉关联方", "已评估", "评估结论"]]
    sheet_detail.extend(detail)

    issues_sorted = sorted(issues, key=lambda x: SEV_ORDER.get(x[3], 9))
    sheet_issues = [["合作方号", "名称", "规则", "规则名", "严重度", "说明"]]
    for i in issues_sorted:
        sheet_issues.append([i[0], i[1], i[2], RULE_NAME[i[2]], i[3], i[4]])

    per_rule = Counter(i[2] for i in issues)
    fixes = [["规则", "需补材料／动作", "涉及条数"]]
    for r in ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]:
        if per_rule.get(r):
            fixes.append([r + " " + RULE_NAME[r], RULE_FIX[r], per_rule[r]])

    return {"汇总": summary, "合作方明细": sheet_detail, "异常清单": sheet_issues, "待补材料": fixes}


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
        if name == "异常清单":
            for r in range(2, ws.max_row + 1):
                if ws.cell(r, 5).value == "高":
                    for cc in range(1, 7):
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
    ap = argparse.ArgumentParser(description="合作方准入与协议体检")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="./合作方体检报告.xlsx")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print("输入文件不存在: %s" % args.input)
        sys.exit(2)

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    issues, detail = run_rules(data, (data.get("org", {}) or {}).get("has_public_fundraising_qualification"))
    tables = build_tables(issues, detail, data.get("partners", []) or [])
    ensure_dir(args.out)

    try:
        write_xlsx(tables, args.out)
        print("已生成 Excel: %s" % args.out)
    except ImportError:
        paths = write_csv(tables, args.out)
        print("未安装 openpyxl，已降级输出 CSV：")
        for p in paths:
            print("  " + p)

    print("合作方 %d 个，命中 %d 条（高危 %d）" % (
        len(data.get("partners", []) or []), len(issues),
        sum(1 for i in issues if i[3] == "高")))
    print("说明：命中项为待核项，不是违规结论，须人工确认后使用。")


if __name__ == "__main__":
    main()
