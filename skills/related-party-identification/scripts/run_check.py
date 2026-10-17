#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
慈善组织关联方与关联交易合规体检工具
=====================================
输入一份结构化事实 JSON，对照规则库（rules.json）逐条扫描，输出：
  1) 控制台 Markdown 摘要（合规评分 + 按严重度排序的缺陷清单 + 待确认项）
  2) Excel 体检报告（4 个 Sheet：体检摘要 / 缺陷清单 / 待确认项 / 评分明细）

用法：
  python scripts/run_check.py -i sample_data/sample_input.json
  python scripts/run_check.py -i facts.json -o out/我的报告.xlsx
  python scripts/run_check.py -i facts.json --no-excel
  python scripts/run_check.py -i facts.json --md-out out/摘要.md

输出路径规则：
  未指定 -o 时，默认写到「输入文件所在目录 / out / 关联方合规体检报告_YYYYMMDD.xlsx」。

口径：
  - 字段缺失 -> 该条规则状态为「待确认」，不计入评分分母，不会被当作通过，也不会被当作命中。
  - 严重度赋权：高 3 / 中 2 / 低 1。
    评分 = 100 ×（已评估规则权值和 − 命中规则权值和）÷ 已评估规则权值和。
  - 本工具为辅助自查，不构成法律意见；具体交易的定性以登记管理机关与专业机构的意见为准。
"""

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SEVERITY_WEIGHT = {"高": 3, "中": 2, "低": 1}
SEVERITY_ORDER = {"高": 0, "中": 1, "低": 2}

KNOWN_COND_TYPES = {
    "flag_true", "flag_false", "missing", "eq",
    "gt", "lt", "ge", "le", "diff_pct", "all", "any",
}
COND_REQUIRED = {
    "flag_true": ["path"], "flag_false": ["path"], "missing": ["path"],
    "eq": ["path", "value"],
    "gt": ["path", "threshold"], "lt": ["path", "threshold"],
    "ge": ["path", "threshold"], "le": ["path", "threshold"],
    "diff_pct": ["path_a", "path_b", "max_pct"],
    "all": ["conds"], "any": ["conds"],
}
EXPECTED_FACT_GROUPS = ["identification", "transaction", "procedure", "disclosure", "mechanism"]
STATUS_CN = {"hit": "命中（存在缺陷）", "pass": "通过", "pending": "待确认"}

TEMPLATE_HINT = "请参照 sample_data/sample_input.json 的结构补全字段后重跑。"


class CheckError(Exception):
    """可控的业务错误：捕获后以友好、可操作的方式提示并退出。"""


# ----------------------------------------------------------------------------
# 友好错误提示
# ----------------------------------------------------------------------------

def errbox(title, body):
    bar = "-" * 66
    print("\n[错误] " + title + "\n" + bar, file=sys.stderr)
    for line in body:
        print("  " + line, file=sys.stderr)
    print(bar + "\n", file=sys.stderr)


def warnbox(title, body):
    print("\n[提示] " + title, file=sys.stderr)
    for line in body:
        print("  " + line, file=sys.stderr)
    print("", file=sys.stderr)


def load_json(path, what):
    if not os.path.exists(path):
        errbox("找不到{}: {}".format(what, path), [
            "请检查文件路径是否正确（相对路径相对于当前工作目录）。",
            "可用 -i / --input 指定完整路径，例如：",
            "  python scripts/run_check.py -i /绝对路径/facts.json -o report.xlsx",
            "路径含空格或中文时，请用双引号包裹。",
        ])
        raise CheckError("file_not_found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        errbox("{}编码不是 UTF-8: {}".format(what, path), [
            "文件需以 UTF-8 编码保存。",
            "怎么做：用编辑器打开该文件，另存时选择 UTF-8 编码（无 BOM）。",
        ])
        raise CheckError("bad_encoding")
    except PermissionError:
        errbox("无权限读取{}: {}".format(what, path), [
            "文件可能正被其他程序占用，或当前用户无读权限。",
            "怎么做：关闭占用该文件的程序后重试，或检查文件读写权限。",
        ])
        raise CheckError("permission_denied")
    except json.JSONDecodeError as e:
        errbox("JSON 解析失败: {}".format(path), [
            "第 {} 行第 {} 列：{}".format(e.lineno, e.colno, e.msg),
            "出错位置附近：..." + e.doc[max(0, e.pos - 20): e.pos] + "<<此处>>",
            "常见原因：对象或数组末尾多了逗号、字符串引号未闭合、键名未加双引号、使用了注释。",
            "怎么做：定位到上述行列，删除多余逗号、补齐引号、去掉注释。",
            TEMPLATE_HINT,
        ])
        raise CheckError("json_decode")


def validate_rules(rules_doc):
    if not isinstance(rules_doc, dict) or "rules" not in rules_doc:
        errbox("规则库格式错误", [
            "rules.json 顶层应包含一个 \"rules\" 数组。",
            "期望结构：{\"meta\": {...}, \"rules\": [ {\"id\": ...}, ... ]}",
        ])
        raise CheckError("rules_shape")
    rules = rules_doc["rules"]
    if not isinstance(rules, list) or not rules:
        errbox("规则库为空", ["rules.json 的 \"rules\" 必须是非空数组。"])
        raise CheckError("rules_empty")

    seen = set()
    for idx, r in enumerate(rules):
        rid = r.get("id", "第{}条".format(idx + 1))
        if "id" in r and r["id"] in seen:
            errbox("规则编号重复: {}".format(r["id"]), ["每条规则的 id 必须唯一，请修改后重跑。"])
            raise CheckError("dup_rule_id")
        seen.add(rid)
        for k in ("id", "category", "severity", "title", "condition"):
            if k not in r:
                errbox("规则 {} 缺少必填字段: \"{}\"".format(rid, k), [
                    "每条规则需包含 id / category / severity / title / condition。",
                ])
                raise CheckError("rule_missing_field")
        if r["severity"] not in SEVERITY_WEIGHT:
            errbox("规则 {} 的 severity 取值不支持: \"{}\"".format(rid, r["severity"]), [
                "支持的取值：高 / 中 / 低。",
            ])
            raise CheckError("bad_severity")
        cond = r["condition"]
        if not isinstance(cond, dict) or "type" not in cond:
            errbox("规则 {} 的 condition 缺少 \"type\"".format(rid), [
                "condition 应为对象且包含 type，例如 {\"type\": \"flag_true\", \"path\": \"facts.xxx\"}",
            ])
            raise CheckError("cond_no_type")
        t = cond["type"]
        if t not in KNOWN_COND_TYPES:
            errbox("规则 {} 的 condition.type 未知: \"{}\"".format(rid, t), [
                "支持类型：" + " / ".join(sorted(KNOWN_COND_TYPES)),
            ])
            raise CheckError("unknown_cond_type")
        for need in COND_REQUIRED.get(t, []):
            if need not in cond:
                errbox("规则 {}（type={}）缺少必填字段: \"{}\"".format(rid, t, need), [
                    "类型 {} 需要字段：".format(t) + " / ".join(COND_REQUIRED[t]),
                ])
                raise CheckError("cond_missing_field")
        if t in ("all", "any"):
            if not isinstance(cond["conds"], list) or not cond["conds"]:
                errbox("规则 {}（type={}）的 conds 必须是非空数组".format(rid, t), [
                    "示例：{\"type\": \"all\", \"conds\": [ {..}, {..} ]}",
                ])
                raise CheckError("conds_invalid")
    return rules


def validate_input(data, input_path):
    if not isinstance(data, dict):
        errbox("输入不是 JSON 对象: {}".format(input_path), [
            "顶层应是一个对象 { \"org\": {...}, \"facts\": {...} }。",
            TEMPLATE_HINT,
        ])
        raise CheckError("input_not_object")

    if "org" not in data:
        warnbox("输入缺少 'org' 字段，报告将缺失机构信息（可继续运行）", [
            "建议补全：\"org\": {\"name\": \"机构名称\", \"org_type\": \"基金会\", \"period\": \"2025年度\"}",
        ])

    if "facts" not in data:
        errbox("输入缺少顶层 'facts' 字段: {}".format(input_path), [
            "facts 是必填对象，建议包含五个分组：",
            "  \"facts\": {",
            "    \"identification\": {...}, \"transaction\": {...}, \"procedure\": {...},",
            "    \"disclosure\": {...}, \"mechanism\": {...}",
            "  }",
            TEMPLATE_HINT,
        ])
        raise CheckError("missing_facts")

    if not isinstance(data["facts"], dict):
        errbox("'facts' 不是对象", ["facts 必须是一个 JSON 对象（键值对），不能是数组或字符串。", TEMPLATE_HINT])
        raise CheckError("facts_not_object")

    missing_groups = [g for g in EXPECTED_FACT_GROUPS if g not in data["facts"]]
    if missing_groups:
        warnbox("以下分组在 facts 中缺失 -> " + "、".join(missing_groups), [
            "这些分组下的规则将全部标记为「待确认」，不计入评分；补全后复评即可。",
        ])
    return missing_groups


# ----------------------------------------------------------------------------
# 取值与条件解释
# ----------------------------------------------------------------------------

def get_val(obj, path):
    cur = obj
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def is_absent(v):
    return v is None or v == "" or (isinstance(v, float) and math.isnan(v))


def to_number(v):
    if is_absent(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def truthy(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip() not in ("", "否", "无", "no", "false", "0", "f", "n")
    return bool(v)


def eval_cond(cond, data):
    """
    返回 hit / pass / pending 三态。
    字段缺失一律返回 pending —— 既不误判为通过，也不误判为命中。
    """
    t = cond.get("type")

    if t == "flag_true":
        v = get_val(data, cond["path"])
        if is_absent(v):
            return "pending"
        return "hit" if truthy(v) else "pass"

    if t == "flag_false":
        v = get_val(data, cond["path"])
        if is_absent(v):
            return "pending"
        return "hit" if not truthy(v) else "pass"

    if t == "missing":
        return "hit" if is_absent(get_val(data, cond["path"])) else "pass"

    if t == "eq":
        v = get_val(data, cond["path"])
        if is_absent(v):
            return "pending"
        return "hit" if v == cond["value"] else "pass"

    if t in ("gt", "lt", "ge", "le"):
        a = to_number(get_val(data, cond["path"]))
        b = to_number(cond.get("threshold"))
        if a is None or b is None:
            return "pending"
        if t == "gt":
            return "hit" if a > b else "pass"
        if t == "lt":
            return "hit" if a < b else "pass"
        if t == "ge":
            return "hit" if a >= b else "pass"
        return "hit" if a <= b else "pass"

    if t == "diff_pct":
        a = to_number(get_val(data, cond["path_a"]))
        b = to_number(get_val(data, cond["path_b"]))
        if a is None or b is None or abs(a) < 1e-9:
            return "pending"
        return "hit" if abs(a - b) / abs(a) > cond["max_pct"] else "pass"

    if t == "all":
        results = [eval_cond(c, data) for c in cond["conds"]]
        if "pass" in results:
            return "pass"
        if "pending" in results:
            return "pending"
        return "hit"

    if t == "any":
        results = [eval_cond(c, data) for c in cond["conds"]]
        if "hit" in results:
            return "hit"
        if "pending" in results:
            return "pending"
        return "pass"

    return "pending"


# ----------------------------------------------------------------------------
# 扫描与评分
# ----------------------------------------------------------------------------

def scan(rules, data, cat_names):
    results = []
    for r in rules:
        status = eval_cond(r["condition"], data)
        results.append({
            "id": r["id"],
            "category": cat_names.get(r["category"], r["category"]),
            "category_key": r["category"],
            "severity": r["severity"],
            "title": r["title"],
            "desc": r.get("desc", ""),
            "law": r.get("law", ""),
            "fix": r.get("fix", ""),
            "fields": r.get("fields", []),
            "status": status,
            "weight": SEVERITY_WEIGHT.get(r["severity"], 1),
        })
    return results


def compute_score(results):
    evaluated = [r for r in results if r["status"] in ("hit", "pass")]
    hits = [r for r in evaluated if r["status"] == "hit"]
    denom = sum(r["weight"] for r in evaluated)
    if denom == 0:
        return 0.0, 0, 0
    score = 100.0 * (denom - sum(r["weight"] for r in hits)) / denom
    return round(score, 1), len(evaluated), len(hits)


def missing_fields_of(item, data):
    fields = [f for f in item["fields"] if is_absent(get_val(data, f))]
    return "、".join(fields) if fields else "（复合条件数据不足，无法判定）"


def grade_of(score, evaluated):
    if evaluated == 0:
        return "无可评估项，请先补全材料后复评"
    if score >= 90:
        return "良好"
    if score >= 75:
        return "基本合规，需整改"
    if score >= 60:
        return "存在多处缺陷，需重点整改"
    return "缺陷较多，建议专项治理"


def score_text(score, evaluated):
    return "{:.1f}".format(score) if evaluated else "—"


# ----------------------------------------------------------------------------
# Markdown 摘要
# ----------------------------------------------------------------------------

def build_markdown(data, results, score, evaluated, hits, pending, rules_meta):
    org = data.get("org", {})
    sev_count = {"高": 0, "中": 0, "低": 0}
    for r in results:
        if r["status"] == "hit":
            sev_count[r["severity"]] += 1

    lines = []
    lines.append("# 关联方与关联交易合规体检摘要")
    lines.append("")
    lines.append("- 机构：{}　|　类型：{}　|　所属期：{}".format(
        org.get("name", "—"), org.get("org_type", "—"), org.get("period", "—")))
    lines.append("- 编制：{}　|　编制日期：{}".format(org.get("preparer", "—"), org.get("prepared_at", "—")))
    lines.append("- 生成时间：{}　|　规则库版本：{}".format(
        datetime.now().strftime("%Y-%m-%d %H:%M"), rules_meta.get("version", "—")))
    lines.append("")
    lines.append("## 合规评分：{} / 100（{}）".format(
        score_text(score, evaluated), grade_of(score, evaluated)))
    lines.append("")
    lines.append("- 已评估规则 {} 条　|　命中（缺陷）{} 条　|　待确认 {} 条".format(evaluated, hits, pending))
    lines.append("- 命中分布：高 {}　中 {}　低 {}".format(sev_count["高"], sev_count["中"], sev_count["低"]))
    lines.append("")

    hit_list = sorted([r for r in results if r["status"] == "hit"],
                      key=lambda x: (SEVERITY_ORDER[x["severity"]], x["id"]))
    lines.append("## 缺陷清单（按严重度排序）")
    lines.append("")
    if hit_list:
        lines.append("| 严重度 | 编号 | 类别 | 缺陷 | 依据 | 整改建议 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in hit_list:
            lines.append("| {} | {} | {} | {} | {} | {} |".format(
                r["severity"], r["id"], r["category"], r["title"],
                r["law"].replace("\n", " "), r["fix"].replace("\n", " ")))
    else:
        lines.append("未发现命中规则。")
    lines.append("")

    pend_list = [r for r in results if r["status"] == "pending"]
    lines.append("## 待确认项（材料补全后复评）")
    lines.append("")
    if pend_list:
        lines.append("| 编号 | 类别 | 严重度 | 事项 | 需补充的字段 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in pend_list:
            lines.append("| {} | {} | {} | {} | {} |".format(
                r["id"], r["category"], r["severity"], r["title"], missing_fields_of(r, data)))
    else:
        lines.append("无待确认项。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("评分口径：评分 = 100 ×（已评估规则权值和 − 命中规则权值和）÷ 已评估规则权值和；赋权 高 3 / 中 2 / 低 1；待确认项不计入分母。")
    lines.append("")
    lines.append("本工具为辅助自查，不构成法律意见。具体交易的定性以登记管理机关与专业机构的意见为准；引用的比例与时限以现行公布的规定为准。")
    if rules_meta.get("version_note"):
        lines.append("")
        lines.append("版本提示：" + rules_meta["version_note"])
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 降级输出：Markdown 文件 + CSV
# ----------------------------------------------------------------------------

def write_text(path, content):
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        print("[提示] 写出文本失败：{}: {}".format(type(e).__name__, e), file=sys.stderr)
        return False


def write_csv_fallback(path, results):
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["严重度", "编号", "类别", "缺陷", "评估状态", "依据", "整改建议"])
            for x in sorted(results, key=lambda y: (SEVERITY_ORDER[y["severity"]], y["id"])):
                w.writerow([x["severity"], x["id"], x["category"], x["title"],
                            STATUS_CN[x["status"]], x["law"], x["fix"]])
        return True
    except Exception as e:
        print("[提示] 写出 CSV 失败：{}: {}".format(type(e).__name__, e), file=sys.stderr)
        return False


# ----------------------------------------------------------------------------
# Excel 报告
# ----------------------------------------------------------------------------

def write_excel(path, data, results, score, evaluated, hits, pending, rules_meta):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        warnbox("未安装 openpyxl，跳过 Excel 报告", [
            "怎么做：pip install openpyxl，或改用已安装 openpyxl 的 Python 运行本脚本。",
            "替代方案：控制台 Markdown 摘要与 CSV 降级文件仍可正常使用。",
        ])
        return False

    org = data.get("org", {})
    wb = Workbook()

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    title_font = Font(bold=True, size=14, color="1F4E78")
    wrap = Alignment(wrap_text=True, vertical="top")
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    sev_fill = {
        "高": PatternFill("solid", fgColor="F4B0B0"),
        "中": PatternFill("solid", fgColor="FBE2A0"),
        "低": PatternFill("solid", fgColor="DDEBC8"),
    }

    def style_header(ws, ncols):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center
            cell.border = border

    def set_widths(ws, widths):
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    # Sheet 1 体检摘要
    ws = wb.active
    ws.title = "体检摘要"
    ws["A1"] = "关联方与关联交易合规体检报告"
    ws["A1"].font = title_font
    ws.merge_cells("A1:D1")

    info = [
        ("机构名称", org.get("name", "—")),
        ("机构类型", org.get("org_type", "—")),
        ("统一社会信用代码", org.get("credit_code", "—")),
        ("登记管理机关", org.get("authority", "—")),
        ("所属期", org.get("period", "—")),
        ("编制人", org.get("preparer", "—")),
        ("编制日期", org.get("prepared_at", "—")),
        ("规则库版本", rules_meta.get("version", "—")),
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M")),
    ]
    r = 3
    for k, v in info:
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v)
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="合规评分").font = Font(bold=True, size=12)
    sc = ws.cell(row=r, column=2, value=score)
    if evaluated:
        sc.value = float(score)
    sc.font = Font(bold=True, size=12, color="C00000")
    sc.alignment = center
    ws.cell(row=r, column=3, value="/ 100").font = Font(size=12)
    ws.cell(row=r, column=4, value=grade_of(score, evaluated)).font = Font(size=12)
    r += 2

    sev_count = {"高": 0, "中": 0, "低": 0}
    for x in results:
        if x["status"] == "hit":
            sev_count[x["severity"]] += 1
    summary = [
        ("已评估规则数", evaluated),
        ("命中（缺陷）数", hits),
        ("待确认数", pending),
        ("高严重度命中", sev_count["高"]),
        ("中严重度命中", sev_count["中"]),
        ("低严重度命中", sev_count["低"]),
    ]
    for k, v in summary:
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v).alignment = center
        r += 1

    r += 1
    note = ws.cell(row=r, column=1, value="评分口径：评分 = 100 ×（已评估规则权值和 − 命中规则权值和）÷ 已评估规则权值和；赋权 高 3 / 中 2 / 低 1；待确认项不计入分母。本工具为辅助自查，不构成法律意见。")
    note.font = Font(italic=True, size=9, color="808080")
    note.alignment = wrap
    ws.merge_cells(start_row=r, start_column=1, end_row=r + 1, end_column=4)
    r += 3

    if rules_meta.get("version_note"):
        vn = ws.cell(row=r, column=1, value="版本提示：" + rules_meta["version_note"])
        vn.font = Font(size=9, color="9C5700")
        vn.alignment = wrap
        ws.merge_cells(start_row=r, start_column=1, end_row=r + 2, end_column=4)

    set_widths(ws, [20, 34, 12, 16])

    # Sheet 2 缺陷清单
    ws2 = wb.create_sheet("缺陷清单")
    headers2 = ["严重度", "编号", "类别", "缺陷", "缺陷说明", "法规依据", "整改建议"]
    ws2.append(headers2)
    style_header(ws2, len(headers2))
    hit_list = sorted([x for x in results if x["status"] == "hit"],
                      key=lambda x: (SEVERITY_ORDER[x["severity"]], x["id"]))
    for x in hit_list:
        ws2.append([x["severity"], x["id"], x["category"], x["title"], x["desc"], x["law"], x["fix"]])
        row = ws2.max_row
        ws2.cell(row=row, column=1).fill = sev_fill.get(x["severity"])
        for c in range(1, len(headers2) + 1):
            ws2.cell(row=row, column=c).alignment = wrap
            ws2.cell(row=row, column=c).border = border
    if not hit_list:
        ws2.append(["—", "—", "—", "未发现命中规则", "—", "—", "—"])
    set_widths(ws2, [8, 10, 14, 26, 42, 46, 46])
    ws2.freeze_panes = "A2"

    # Sheet 3 待确认项
    ws3 = wb.create_sheet("待确认项")
    headers3 = ["编号", "类别", "严重度", "事项", "需补充的字段", "说明"]
    ws3.append(headers3)
    style_header(ws3, len(headers3))
    pend_list = [x for x in results if x["status"] == "pending"]
    for x in pend_list:
        ws3.append([x["id"], x["category"], x["severity"], x["title"], missing_fields_of(x, data), x["desc"]])
        row = ws3.max_row
        for c in range(1, len(headers3) + 1):
            ws3.cell(row=row, column=c).alignment = wrap
            ws3.cell(row=row, column=c).border = border
    if not pend_list:
        ws3.append(["—", "—", "—", "无待确认项", "—", "—"])
    set_widths(ws3, [10, 14, 8, 30, 40, 44])
    ws3.freeze_panes = "A2"

    # Sheet 4 评分明细
    ws4 = wb.create_sheet("评分明细")
    headers4 = ["编号", "类别", "严重度", "赋权", "事项", "评估状态", "法规依据"]
    ws4.append(headers4)
    style_header(ws4, len(headers4))
    for x in results:
        ws4.append([x["id"], x["category"], x["severity"], x["weight"], x["title"],
                    STATUS_CN[x["status"]], x["law"]])
        row = ws4.max_row
        if x["status"] == "hit":
            ws4.cell(row=row, column=6).fill = sev_fill.get(x["severity"])
        elif x["status"] == "pending":
            ws4.cell(row=row, column=6).fill = PatternFill("solid", fgColor="D9D9D9")
        for c in range(1, len(headers4) + 1):
            ws4.cell(row=row, column=c).alignment = wrap
            ws4.cell(row=row, column=c).border = border
    set_widths(ws4, [10, 14, 8, 6, 30, 16, 46])
    ws4.freeze_panes = "A2"

    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    try:
        wb.save(path)
    except PermissionError:
        warnbox("无法保存 Excel 报告（文件可能正被打开或锁定）：{}".format(path), [
            "怎么做：关闭正在打开该报告的 Excel 或 WPS，或换一个输出文件名（-o 新名字）再试。",
            "替代方案：控制台 Markdown 摘要与 CSV 降级文件仍可正常使用。",
        ])
        return False
    except Exception as e:
        warnbox("保存 Excel 报告失败：{}: {}".format(type(e).__name__, e), [
            "怎么做：确认输出目录有写权限；控制台 Markdown 摘要与 CSV 降级文件仍可正常使用。",
        ])
        return False
    return True


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def default_out_path(input_path):
    base = os.path.dirname(os.path.abspath(input_path))
    name = "关联方合规体检报告_{}.xlsx".format(datetime.now().strftime("%Y%m%d"))
    return os.path.join(base, "out", name)


def main():
    parser = argparse.ArgumentParser(description="慈善组织关联方与关联交易合规体检工具")
    parser.add_argument("-i", "--input", required=True, help="机构事实 JSON 路径")
    parser.add_argument("-o", "--out", default=None, help="Excel 报告输出路径（默认：输入文件同级 out 目录）")
    parser.add_argument("-r", "--rules", default=None, help="规则库 JSON 路径（默认：脚本同级 rules.json）")
    parser.add_argument("--md-out", default=None, help="同时把 Markdown 摘要写成文件")
    parser.add_argument("--no-excel", action="store_true", help="仅输出 Markdown 摘要，不生成 Excel")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    rules_path = args.rules or os.path.join(script_dir, "rules.json")

    try:
        data = load_json(args.input, "输入文件")
        rules_doc = load_json(rules_path, "规则库")
        rules = validate_rules(rules_doc)
        validate_input(data, args.input)
    except CheckError:
        sys.exit(2)

    meta = rules_doc.get("meta", {})
    cat_names = meta.get("categories", {})
    results = scan(rules, data, cat_names)
    score, evaluated, hits = compute_score(results)
    pending = len([r for r in results if r["status"] == "pending"])

    md = build_markdown(data, results, score, evaluated, hits, pending, meta)
    print(md)
    print("")

    if args.md_out:
        if write_text(args.md_out, md):
            print("Markdown 摘要已生成: {}".format(args.md_out))

    if args.no_excel:
        return

    out_path = args.out or default_out_path(args.input)
    ok = write_excel(out_path, data, results, score, evaluated, hits, pending, meta)
    if ok:
        print("Excel 报告已生成: {}".format(out_path))
    else:
        csv_path = os.path.splitext(out_path)[0] + ".csv"
        if write_csv_fallback(csv_path, results):
            print("已降级生成 CSV 清单: {}".format(csv_path))
        if not args.md_out:
            md_path = os.path.splitext(out_path)[0] + ".md"
            if write_text(md_path, md):
                print("已降级生成 Markdown 摘要: {}".format(md_path))


if __name__ == "__main__":
    main()
