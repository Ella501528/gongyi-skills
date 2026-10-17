# -*- coding: utf-8 -*-
"""志愿者招募培训与岗位适配体检 —— 八条规则（逐条见 references/判定规则索引.md）

用法:
    python check_onboarding.py --input sample_data/sample_input.json --out ./招募体检报告.xlsx

输入: 一份 JSON，含活动定义 activities 与人员安排 assignments（结构见 sample_data/sample_input.json）
输出: Excel 四表 —— 汇总 / 安排明细 / 异常清单 / 待补材料

未安装 openpyxl 时自动降级为 CSV（同目录，按表分文件，内容一致）。
命中的均为【待核项】，不是违规结论，须人工确认。

依据：《慈善法》第 62/64/65/67 条、《志愿服务条例》第 12/14/15/16/20/22 条。
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter

SEV_ORDER = {"高": 0, "中": 1, "低": 2}

RULE_NAME = {
    "O1": "招募公告要素不全或未公示",
    "O2": "未做风险告知或未留签收",
    "O3": "应当签协议而未签",
    "O4": "岗位与年龄或身体状况不匹配",
    "O5": "岗位与技能不匹配",
    "O6": "需专门技能而未培训",
    "O7": "需职业资格而未取得",
    "O8": "岗前培训未完成即安排上岗",
}
RULE_FIX = {
    "O1": "补齐公告七要素后发布；风险提示与保障条件不得省",
    "O2": "上岗前书面告知风险并留签收；已上岗的补充告知",
    "O3": "补签协议，写明内容方式时间地点与安全保障措施",
    "O4": "调整岗位或换人；不得安排明显超出身体条件的服务",
    "O5": "先培训或调岗；不得边干边学顶专业岗",
    "O6": "补相应培训并留记录；培训完成前不排班",
    "O7": "持证后再排该岗；无证不得顶岗",
    "O8": "先完成岗前培训（含风险与应急）再排班",
}
NOTICE_REQUIRED = ["服务内容", "时间地点", "岗位要求", "风险提示", "保障条件", "报名方式", "联系人"]


def mask_name(name):
    if not name:
        return "（未填）"
    s = str(name).strip()
    return s if len(s) <= 1 else s[0] + "×" * (len(s) - 1)


def ensure_dir(path):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def run_rules(data, minor_age, risk_for_agreement):
    acts = {a.get("id"): a for a in (data.get("activities", []) or [])}
    assigns = data.get("assignments", []) or []

    issues = []   # [志愿者号, 姓名, 活动, 规则, 严重度, 说明]
    detail = []

    def add(vid, vname, act, rule, sev, note):
        issues.append([vid, vname, act, rule, sev, note])

    # O1 招募公告（按活动）
    for a in acts.values():
        missing = [f for f in NOTICE_REQUIRED if f not in (a.get("notice_fields") or [])]
        if not a.get("notice_published", False):
            add("-", "（活动级）", a.get("name", ""), "O1", "中", "招募公告未发布")
        elif missing:
            add("-", "（活动级）", a.get("name", ""), "O1", "中", "公告缺要素: " + "、".join(missing))

    for s in assigns:
        vid = s.get("volunteer_id", "")
        vname = mask_name(s.get("volunteer_name", ""))
        a = acts.get(s.get("activity_id")) or {}
        aname = a.get("name", s.get("activity_id", ""))
        risk = a.get("risk_level", "低")
        req_skill = bool(a.get("requires_skill"))
        need_skill = a.get("skill", "")
        req_cert = bool(a.get("requires_cert"))
        need_cert = a.get("cert", "")
        minor_ok = bool(a.get("minor_allowed"))
        min_age = a.get("min_age")
        max_age = a.get("max_age")
        age = s.get("age")
        is_minor = bool(s.get("is_minor"))
        health = str(s.get("health_note", "") or "").strip()
        skills = s.get("skills") or []
        certs = s.get("certs") or []
        trainings = s.get("trainings") or []

        # O2 风险告知
        if not s.get("risk_brief_signed", False):
            add(vid, vname, aname, "O2", "高" if risk == "高" else "中", "未留风险告知签收")

        # O3 协议
        need_agree = (risk == "高") or req_skill or req_cert or bool(s.get("long_term"))
        if need_agree and not s.get("agreement_signed", False):
            add(vid, vname, aname, "O3", "中", "应签协议而未签（高风险/专业/长期）")

        # O4 年龄与健康
        if is_minor and not minor_ok:
            add(vid, vname, aname, "O4", "高", "未成年人参加不允许未成年人参加的活动")
        if isinstance(age, (int, float)) and isinstance(min_age, (int, float)) and age < min_age:
            add(vid, vname, aname, "O4", "高", "年龄 %s 低于该活动下限 %s" % (age, min_age))
        if isinstance(age, (int, float)) and isinstance(max_age, (int, float)) and age > max_age:
            add(vid, vname, aname, "O4", "高", "年龄 %s 高于该活动上限 %s" % (age, max_age))
        if health and risk == "高":
            add(vid, vname, aname, "O4", "高", "健康备注受限（%s）仍安排高风险活动" % health)

        # O5 技能
        if req_skill and need_skill and need_skill not in skills:
            add(vid, vname, aname, "O5", "高", "缺该岗位技能: %s" % need_skill)

        # O6 培训
        if req_skill and need_skill and need_skill not in trainings:
            add(vid, vname, aname, "O6", "中", "未培训该项专门技能: %s" % need_skill)

        # O7 资格
        if req_cert and need_cert and need_cert not in certs:
            add(vid, vname, aname, "O7", "高", "未取得该岗位职业资格: %s" % need_cert)

        # O8 岗前培训
        if not s.get("training_completed", False):
            add(vid, vname, aname, "O8", "高", "岗前培训未完成即排班")

        detail.append([vid, vname, aname,
                       "未成年人" if is_minor else age, risk,
                       need_skill or "-", need_cert or "-",
                       "是" if s.get("risk_brief_signed") else "否",
                       "是" if s.get("agreement_signed") else "否",
                       "是" if s.get("training_completed") else "否"])

    return issues, detail


def build_tables(issues, detail, assigns):
    high = sum(1 for i in issues if i[4] == "高")
    mid = sum(1 for i in issues if i[4] == "中")
    low = sum(1 for i in issues if i[4] == "低")

    summary = [
        ["项", "值"],
        ["人员安排条数", len(assigns)],
        ["命中总条数", len(issues)],
        ["高危条数（须人工确认）", high],
        ["中危条数", mid],
        ["低危条数（待办）", low],
        ["体检结论", "存在高危待核项，上岗前须逐条确认" if high
         else ("仅中低危待核项，建议确认后放行" if (mid or low) else "未发现明显缺陷")],
        [],
        ["规则", "命中数"],
    ]
    cnt = Counter(i[3] for i in issues)
    for r in ["O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8"]:
        summary.append(["%s %s" % (r, RULE_NAME[r]), cnt.get(r, 0)])

    sheet_detail = [["志愿者号", "姓名", "活动", "年龄", "活动风险", "要求技能", "要求资格",
                     "风险告知", "已签协议", "岗前培训"]]
    sheet_detail.extend(detail)

    issues_sorted = sorted(issues, key=lambda x: SEV_ORDER.get(x[4], 9))
    sheet_issues = [["志愿者号", "姓名", "活动", "规则", "规则名", "严重度", "说明"]]
    for i in issues_sorted:
        sheet_issues.append([i[0], i[1], i[2], i[3], RULE_NAME[i[3]], i[4], i[5]])

    per_rule = Counter(i[3] for i in issues)
    fixes = [["规则", "需补材料／动作", "涉及条数"]]
    for r in ["O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8"]:
        if per_rule.get(r):
            fixes.append([r + " " + RULE_NAME[r], RULE_FIX[r], per_rule[r]])

    return {"汇总": summary, "安排明细": sheet_detail, "异常清单": sheet_issues, "待补材料": fixes}


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
                if ws.cell(r, 6).value == "高":
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
    ap = argparse.ArgumentParser(description="志愿者招募培训与岗位适配体检")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="./招募体检报告.xlsx")
    ap.add_argument("--minor-age", type=int, default=18, help="未成年人年龄下限，默认 18")
    ap.add_argument("--risk-for-agreement", default="高",
                    help="触发协议的默认高风险级别，默认 高")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print("输入文件不存在: %s" % args.input)
        sys.exit(2)

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    issues, detail = run_rules(data, args.minor_age, args.risk_for_agreement)
    tables = build_tables(issues, detail, data.get("assignments", []) or [])
    ensure_dir(args.out)

    try:
        write_xlsx(tables, args.out)
        print("已生成 Excel: %s" % args.out)
    except ImportError:
        paths = write_csv(tables, args.out)
        print("未安装 openpyxl，已降级输出 CSV：")
        for p in paths:
            print("  " + p)

    print("安排 %d 条，命中 %d 条（高危 %d）" % (
        len(data.get("assignments", []) or []), len(issues),
        sum(1 for i in issues if i[4] == "高")))
    print("说明：命中项为待核项，不是违规结论，须人工确认后使用。")


if __name__ == "__main__":
    main()
