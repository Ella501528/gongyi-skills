#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""慈善资质名录库 · 命令行入口

用法：
    python cqr.py init                                  初始化名录库
    python cqr.py update --only R6                      更新指定名录
    python cqr.py update --only R2 --max-pages 5        限量更新（用于抽查）
    python cqr.py update --all                          更新全部已实现名录
    python cqr.py query --name 中国红十字基金会          按名称查询
    python cqr.py query --uscc 51150000MJ22100518       按统一社会信用代码查询
    python cqr.py stats                                 库统计
    python cqr.py changes --days 30                     查看近期变更
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import db  # noqa: E402

ROOT = os.path.dirname(HERE)
DB_PATH = os.environ.get("CQR_DB") or os.path.join(ROOT, "data", "cqr.db")

SOURCE_CSZG = {"R1", "R2", "R6"}
SOURCE_TAX = {"R3"}
SOURCE_LOCAL = {"R4", "R5"}
ALL_KEYS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]


def load():
    return db.connect(DB_PATH)


def cmd_init(a):
    conn = load()
    conn.commit()
    s = db.stats(conn)
    print(f"名录库已就绪：{DB_PATH}")
    print(f"  org={s['org']} qual={s['qual']} snapshot={s['snapshot']} changelog={s['changelog']}")
    conn.close()


def cmd_update(a):
    import fetch_cszg

    keys = ALL_KEYS if a.all else [k.strip().upper() for k in (a.only or "").split(",") if k.strip()]
    if not keys:
        print("请指定 --only R1,R2,R6 或 --all")
        return 2

    conn = load()
    results = []
    try:
        for k in keys:
            if k in SOURCE_CSZG:
                if k == "R1":
                    res = fetch_cszg.fetch(conn, fetch_cszg.QUAL_ORG,
                                           max_pages=a.max_pages, verbose=True,
                                           start_page=a.start_page)
                elif k == "R2":
                    res = fetch_cszg.fetch(conn, fetch_cszg.QUAL_MJZG, mjzg=1,
                                           max_pages=a.max_pages, verbose=True,
                                           start_page=a.start_page)
                elif k == "R6":
                    seen = set()
                    res = fetch_cszg.fetch(conn, fetch_cszg.QUAL_CREDIT, xyzk=2,
                                           max_pages=a.max_pages, verbose=True,
                                           mark_expired=False, seen_out=seen)
                    res2 = fetch_cszg.fetch(conn, fetch_cszg.QUAL_CREDIT, xyzk=3,
                                            max_pages=a.max_pages, verbose=True,
                                            mark_expired=False, seen_out=seen)
                    if not a.max_pages:
                        res["expired"] = db.mark_missing(
                            conn, fetch_cszg.QUAL_CREDIT, seen, fetch_cszg.LIST_URL,
                            change_type="移出名单")
                        conn.commit()
                    res["rows"] += res2["rows"]
                    res["new"] += res2["new"]
                    res["total"] = (res.get("total") or 0) + (res2.get("total") or 0)
                results.append(res)
                print(f"[{k}] {json.dumps(res, ensure_ascii=False)}")
            elif k in SOURCE_TAX:
                import fetch_tax
                res = fetch_tax.fetch(conn, verbose=True, max_items=a.max_pages)
                results.append(res)
                print(f"[{k}] {json.dumps(res, ensure_ascii=False)}")
            else:
                print(f"[{k}] 该名录的取数器尚未实现")
    finally:
        conn.commit()
        s = db.stats(conn)
        conn.close()
    print(f"\n完成。库内：org={s['org']} qual={s['qual']} changelog={s['changelog']}")
    return 0


def cmd_query(a):
    conn = load()
    try:
        if a.uscc:
            rows = conn.execute(
                "SELECT * FROM org WHERE uscc = ? OR uscc LIKE ?",
                (a.uscc, f"%{a.uscc}%")).fetchall()
        elif a.name:
            rows = conn.execute(
                "SELECT * FROM org WHERE name LIKE ? LIMIT 30", (f"%{a.name}%",)).fetchall()
        else:
            print("请提供 --name 或 --uscc")
            return 2
        if not rows:
            print("库内未找到。若为本地无记录，可能尚未收录或名称不匹配。")
            return 1
        for o in rows:
            print("=" * 60)
            print(f"机构：{o['name']}")
            print(f"  统一社会信用代码：{o['uscc']}")
            print(f"  组织类别：{o['org_type'] or '—'}   状态：{o['status'] or '—'}"
                  f"   信用状况：{o['credit_status'] or '—'}")
            print(f"  成立时间：{o['establish_date'] or '—'}")
            print(f"  登记管理机关：{o['registrar'] or '—'}")
            qs = conn.execute(
                "SELECT qual_type, has_flag, grade, valid_to, source FROM qual "
                "WHERE org_id = ? ORDER BY qual_type", (o["org_id"],)).fetchall()
            if qs:
                print("  资质：")
                for q in qs:
                    flag = {1: "有", 0: "无"}.get(q["has_flag"], "—")
                    extra = f"  有效期至 {q['valid_to']}" if q["valid_to"] else ""
                    print(f"    · {q['qual_type']}：{flag}{extra}（来源：{q['source']}）")
            else:
                print("  资质：库内暂无记录")
    finally:
        conn.close()
    return 0


def cmd_stats(a):
    conn = load()
    try:
        s = db.stats(conn)
        print(f"库文件：{DB_PATH}")
        print(f"  机构 {s['org']} 家 | 资质记录 {s['qual']} 条 | "
              f"快照 {s['snapshot']} 条 | 变更 {s['changelog']} 条")
        print("\n按机构类别：")
        for r in conn.execute(
                "SELECT COALESCE(org_type,'未标注') t, COUNT(*) c FROM org "
                "GROUP BY t ORDER BY c DESC"):
            print(f"  {r['t']}：{r['c']}")
        print("\n按资质类型：")
        for r in conn.execute(
                "SELECT qual_type, COUNT(*) c, SUM(COALESCE(has_flag,0)) h FROM qual "
                "GROUP BY qual_type ORDER BY qual_type"):
            print(f"  {r['qual_type']}：{r['c']} 条（其中标记为「有」{r['h'] or 0}）")
        print("\n最后更新：", db.get_meta(conn, "last_update", "—"))
    finally:
        conn.close()


def cmd_changes(a):
    conn = load()
    try:
        rows = conn.execute(
            "SELECT * FROM changelog ORDER BY id DESC LIMIT ?", (a.limit,)).fetchall()
        if not rows:
            print("暂无变更记录。")
            return
        for r in rows:
            print(f"{r['date']}  [{r['change_type']}]  {r['name'] or r['org_id']}"
                  f"  ({r['qual_type']})  {r['old_value'] or '—'} → {r['new_value'] or '—'}")
    finally:
        conn.close()


def cmd_list(a):
    """按资质类型列出机构。"""
    conn = load()
    try:
        qt = a.qual.upper()
        where = ["q.qual_type LIKE ?"]
        params = [qt + "%"]
        if a.region:
            where.append("(o.registrar LIKE ? OR o.prov LIKE ? OR o.city LIKE ?)")
            params += ["%" + a.region + "%"] * 3
        if a.status:
            where.append("o.status = ?")
            params.append(a.status)
        if a.flag is not None:
            where.append("q.has_flag = ?")
            params.append(a.flag)
        base = "FROM qual q JOIN org o ON o.org_id = q.org_id WHERE " + " AND ".join(where)
        total = conn.execute("SELECT COUNT(*) c " + base, params).fetchone()["c"]
        if not total:
            print("没有符合条件的记录。")
            return

        cols = ["名称", "统一社会信用代码", "类别", "登记管理机关", "状态",
                "信用状况", "有效期至", "来源"]
        sql = ("SELECT o.name, o.uscc, o.org_type, o.registrar, o.status, "
               "o.credit_status, q.valid_to, q.source " + base +
               " ORDER BY o.registrar, o.name")
        p2 = list(params)
        if not a.export and a.limit:
            sql += " LIMIT ?"
            p2.append(a.limit)
        rows = conn.execute(sql, p2).fetchall()

        if a.export:
            import csv
            with open(a.export, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in rows:
                    w.writerow([r["name"], r["uscc"], r["org_type"], r["registrar"],
                                r["status"], r["credit_status"], r["valid_to"], r["source"]])
            print("已导出 %d 条到 %s" % (len(rows), a.export))
            return

        print("共 %d 条匹配。" % total)
        for r in rows:
            print("  %-32s %-18s %-10s %s" % (
                (r["name"] or "")[:32], r["uscc"] or "", r["org_type"] or "",
                r["registrar"] or ""))
        if total > len(rows):
            print("\n（仅显示前 %d 条，用 --limit 调整，或 --export 导出全部）" % len(rows))
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(prog="cqr", description="慈善资质名录库")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("init", help="初始化名录库").set_defaults(func=cmd_init)

    up = sub.add_parser("update", help="更新名录")
    up.add_argument("--only", help="要更新的名录编号，如 R1,R2,R6")
    up.add_argument("--all", action="store_true", help="更新全部已实现名录")
    up.add_argument("--max-pages", type=int, default=None, help="限制页数（用于抽查）")
    up.add_argument("--start-page", type=int, default=1, help="起始页（中断后续抓用）")
    up.set_defaults(func=cmd_update)

    q = sub.add_parser("query", help="查询机构")
    q.add_argument("--name", help="机构名称（模糊匹配）")
    q.add_argument("--uscc", help="统一社会信用代码")
    q.set_defaults(func=cmd_query)

    sub.add_parser("stats", help="库统计").set_defaults(func=cmd_stats)

    ls = sub.add_parser("list", help="按资质类型列出机构")
    ls.add_argument("--qual", required=True, help="资质编号，如 R1/R2/R3/R6")
    ls.add_argument("--region", help="地区关键词（匹配登记管理机关）")
    ls.add_argument("--status", help="组织状态：正常／注销／撤销")
    ls.add_argument("--flag", type=int, choices=[0, 1], help="1 具有／0 不具有")
    ls.add_argument("--limit", type=int, default=50, help="显示条数（默认 50）")
    ls.add_argument("--export", help="导出为 CSV 的路径（导出全部）")
    ls.set_defaults(func=cmd_list)

    ch = sub.add_parser("changes", help="近期变更")
    ch.add_argument("--days", type=int, default=30)
    ch.add_argument("--limit", type=int, default=50)
    ch.set_defaults(func=cmd_changes)

    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return 0
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
