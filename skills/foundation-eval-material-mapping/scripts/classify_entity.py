# -*- coding: utf-8 -*-
"""
资料主体归属分类 —— 把混杂资料拆成 参评主体 / 关联方 / 共有 / 归属不明

用途：
    python classify_entity.py --work <work目录> --rules <entity_rules.json>
                              [--filter-match-report] [--inplace]

行为：
    - 读 work/inventory.json（由 scan_inventory.py 产出），对每个文件判定 entity
    - 写回 inventory.json（--inplace 时）或另存 inventory_entity.json
    - 产出 affiliate_index.json / entity_summary.json / 主体归属统计.csv / 待指派归属清单.csv
    - --filter-match-report 时，把 match_report.json 中非主体候剔除，输出 match_report_self.json

安全：全程只读原材料，不移动/复制/删除任何用户文件。
"""
import argparse
import csv
import json
import os
import sys

SELF, AFF, JOINT, UNKNOWN = "SELF", "AFFILIATE", "JOINT", "UNKNOWN"


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def build_matchers(rules):
    """返回 [(名字, 别名列表)]，别名按长度降序，先长后短避免子串误伤"""
    out = []
    for grp in ("self", "affiliates"):
        node = rules.get(grp)
        nodes = [node] if isinstance(node, dict) else (node or [])
        for n in nodes:
            if not isinstance(n, dict):
                continue
            aliases = [str(x) for x in n.get("aliases", []) if x]
            nm = str(n.get("name", "")).strip()
            if nm and nm not in aliases:
                aliases.append(nm)
            aliases = sorted(set(aliases), key=len, reverse=True)
            out.append((nm, aliases))
    return out


def classify_one(f, rules, self_m, aff_m):
    """判定单个文件归属，返回 (entity, hint)"""
    name = str(f.get("name", "") or "")
    rel = str(f.get("rel", "") or f.get("abs", "") or "")
    hay = rel + " " + name
    low = hay.lower()

    for seg in rules.get("excluded_path_segments", []) or []:
        if str(seg) and str(seg).lower() in low:
            return AFF, "路径含隔离段:%s" % seg

    hit_s = [a for a in self_m[0][1] if a and a.lower() in low]
    tail = str(rules.get("self", {}).get("tax_id_tail", "") or "")
    if tail and tail in hay:
        hit_s.append("信用代码尾号:%s" % tail)

    hit_a = None          # (关联方名称, 命中的最长别名)
    for nm, aliases in aff_m:
        hits = [a for a in aliases if a and a.lower() in low]
        if hits:
            hit_a = (nm, max(hits, key=len))
            break

    if hit_s and hit_a:
        # 主体简称常被关联方全名包含（"示例" ⊂ "示例社工中心"）。
        # 两者无包含关系 → 真·联合署名；有包含关系 → 取更长更具体的一方。
        ls = max(hit_s, key=len)
        la = hit_a[1]
        if ls.lower() in la.lower() or la.lower() in ls.lower():
            if len(la) > len(ls):
                return AFF, "关联方全名更具体(%s ⊃ %s)" % (la, ls)
            return SELF, "主体全名更具体(%s ⊃ %s)" % (ls, la)
        return JOINT, "双方独立署名:主体[%s]+关联方[%s]" % (ls, hit_a[0])
    if hit_s:
        return SELF, "主体署名:%s" % hit_s[0]
    if hit_a:
        return AFF, "关联方署名:%s(%s)" % (hit_a[1], hit_a[0])

    for kw in rules.get("joint_keywords", []) or []:
        if kw and str(kw) in hay:
            return JOINT, "联合线索关键词:%s" % kw
    return UNKNOWN, "无任何主体线索"


def write_csv(p, head, rows):
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="资料主体归属分类（只读）")
    ap.add_argument("--work", required=True, help="工作目录，含 inventory.json")
    ap.add_argument("--rules", required=True, help="entity_rules.json 路径")
    ap.add_argument("--filter-match-report", action="store_true",
                    help="剔除非主体候选，生成 match_report_self.json")
    ap.add_argument("--inplace", action="store_true", help="直接回写 inventory.json")
    args = ap.parse_args()

    work = args.work
    inv_p = os.path.join(work, "inventory.json")
    if not os.path.isfile(inv_p):
        print("ERR: 未找到 %s" % inv_p, file=sys.stderr)
        return 2
    if not os.path.isfile(args.rules):
        print("ERR: 未找到规则文件 %s" % args.rules, file=sys.stderr)
        return 2

    rules = load_json(args.rules)
    inv = load_json(inv_p)
    files = inv.get("files", [])
    matchers = build_matchers(rules)
    if not matchers or not matchers[0][1]:
        print("ERR: entity_rules.json 缺少 self.aliases", file=sys.stderr)
        return 2
    self_m, aff_m = matchers[:1], matchers[1:]

    stat = {SELF: 0, AFF: 0, JOINT: 0, UNKNOWN: 0}
    aff_rows, unknown_rows = [], []
    for f in files:
        ent, hint = classify_one(f, rules, self_m, aff_m)
        f["entity"] = ent
        f["entity_hint"] = hint
        stat[ent] += 1
        if ent in (AFF, JOINT):
            aff_rows.append([f.get("name", ""), f.get("rel", f.get("abs", "")),
                             ent, hint, "仅可用于关联风险与资金穿透核查，不得计入主体评分"])
        elif ent == UNKNOWN:
            unknown_rows.append([f.get("name", ""), f.get("rel", f.get("abs", "")), hint])

    out_inv = inv_p if args.inplace else os.path.join(work, "inventory_entity.json")
    save_json(out_inv, inv)

    save_json(os.path.join(work, "affiliate_index.json"), {
        "note": "关联方/共有资料索引 —— 隔离于主体归档树，仅供风险核查",
        "usage_limit": "不得计入参评主体评分，不得顶替主体自证",
        "count": len(aff_rows),
        "rows": [{"name": r[0], "path": r[1], "entity": r[2], "hint": r[3], "limit": r[4]}
                 for r in aff_rows],
    })
    save_json(os.path.join(work, "entity_summary.json"), {
        "total": len(files), "stat": stat,
        "self_only_usable_for_scoring": stat[SELF],
        "pending_human_assign": stat[UNKNOWN] + stat[JOINT],
    })
    write_csv(os.path.join(work, "主体归属统计.csv"),
              ["归属", "文件数", "说明"],
              [[SELF, stat[SELF], "唯一可用于指标对标与得分判定"],
               [JOINT, stat[JOINT], "共有/联合材料，仅作旁证，需主体履职痕迹配套"],
               [AFF, stat[AFF], "关联方资料，隔离存放，仅用于风险穿透"],
               [UNKNOWN, stat[UNKNOWN], "归属不明，默认不计入主体，须人工指派"]])
    write_csv(os.path.join(work, "待指派归属清单.csv"),
              ["文件名", "相对路径", "判定线索"], unknown_rows)

    print("主体归属分类完成：总数 %d" % len(files))
    print("  SELF    %4d  可用于评分" % stat[SELF])
    print("  JOINT   %4d  仅作旁证" % stat[JOINT])
    print("  AFFILIATE %4d 隔离，仅供穿透核查" % stat[AFF])
    print("  UNKNOWN %4d 进人工确认队列" % stat[UNKNOWN])
    print("  -> %s" % os.path.join(work, "affiliate_index.json"))

    if args.filter_match_report:
        rp = os.path.join(work, "match_report.json")
        if not os.path.isfile(rp):
            print("WARN: 无 match_report.json，跳过过滤", file=sys.stderr)
            return 0
        rep = load_json(rp)
        by_id = {}
        for f in files:
            key = f.get("abs") or f.get("rel") or f.get("name")
            by_id[key] = f.get("entity")
        kept, demoted = 0, 0
        for it in rep.get("items", []):
            fs = [x for x in it.get("files", [])
                  if by_id.get(x.get("abs") or x.get("rel") or x.get("name")) == SELF]
            if len(fs) != len(it.get("files", [])):
                demoted += 1
            it["files"] = fs
            it["candidate_total"] = len(fs)
            if not fs and it.get("status") == "已归位":
                it["status"] = "缺项"
                it["status_note"] = "原候选均为非主体资料，已剔除"
            kept += len(fs)
        outp = os.path.join(work, "match_report_self.json")
        save_json(outp, rep)
        print("  -> %s  保留主体候选 %d 条，涉及 %d 个考查要点被降级/改判" % (outp, kept, demoted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
