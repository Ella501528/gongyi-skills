# -*- coding: utf-8 -*-
"""公益性捐赠税前扣除资格名单（R3）抓取与解析。

数据来源：
    财政部 + 税务总局 + 民政部联合公告，由各地税务局官网全文转载。
    公告正文即为纯文本编号名单，无需下载附件。

公告结构（例：2025 年第 21 号）：
    一、2025年度—2027年度符合公益性捐赠税前扣除资格的公益性社会组织名单
        1.中国民航科普基金会
        2、……
    二、2026年度—2028年度符合公益性捐赠税前扣除资格的公益性社会组织名单
        1.……
    三、取消公益性捐赠税前扣除资格的公益性社会组织名单
        1.……

「取消资格」段落是高价值负向信息，单独处理。
"""
import os
import re
import time

from core import db

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 候选公告页（多省互为备份；同一公告只需拿到一份）
SOURCES = [
    ("https://fujian.chinatax.gov.cn/sszczl/zjfgk/202601/t20260115_625017.htm", "福建·2025年第21号"),
    ("https://yunnan.chinatax.gov.cn/art/2026/1/9/art_7757_11621.html", "云南·2025年第21号"),
    ("https://tianjin.chinatax.gov.cn/11200000000/8000/800024/80002403/20260107162520176.shtml", "天津·2025年第21号"),
    ("https://fujian.chinatax.gov.cn/sszczl/zjfgk/202501/t20250108_589375.htm", "福建·2024年第22号"),
]

QUAL_R3 = "R3 公益性捐赠税前扣除资格"

HEAD_RE = re.compile(r"^([一二三四五六七八九十]+)\s*[、.．]\s*(.+)$")
YEAR_RE = re.compile(r"(\d{4})\s*年度\s*[—\-－~～至到]\s*(\d{4})\s*年度")
ITEM_RE = re.compile(r"^(\d{1,4})\s*[.．、]\s*(\S.*?)$")
DOCNO_RE = re.compile(r"公告\s*(\d{4})\s*年第\s*(\d+)\s*号")


def fetch_text(url, timeout=30):
    import httpx
    r = httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    r.encoding = r.charset_encoding or "utf-8"
    return r.text


def html_to_text(html):
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</(p|div|tr|li|h\d)>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", "", html)
    for a, b in (("&nbsp;", " "), ("&#160;", " "), ("&amp;", "&"),
                 ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        html = html.replace(a, b)
    return html


def parse(html):
    """解析公告：返回 {doc_no, batches[], cancelled[]}。"""
    text = html_to_text(html)
    lines = []
    for raw in text.split("\n"):
        s = raw.replace("\u3000", " ").replace("\xa0", " ").strip()
        if s:
            lines.append(s)

    doc_no = ""
    m = DOCNO_RE.search(text)
    if m:
        doc_no = f"{m.group(1)}年第{m.group(2)}号"

    batches, cancelled, cur = [], [], None
    for s in lines:
        hm = HEAD_RE.match(s)
        if hm and "名单" in hm.group(2):
            title = hm.group(2).strip()
            cur = {"title": title, "names": [], "from": None, "to": None}
            ym = YEAR_RE.search(title)
            if ym:
                cur["from"], cur["to"] = ym.group(1), ym.group(2)
            (cancelled if "取消" in title else batches).append(cur)
            continue
        if cur is None:
            continue
        im = ITEM_RE.match(s)
        if im:
            nm = re.sub(r"[，,。；;、\s]+$", "", im.group(2)).strip()
            if 3 <= len(nm) <= 60 and not nm.isdigit():
                cur["names"].append(nm)
    return {"doc_no": doc_no, "batches": batches, "cancelled": cancelled}


def _find_org(conn, name):
    """按名称精确匹配库内机构；匹配不到则返回 None。"""
    r = conn.execute("SELECT org_id, name FROM org WHERE name = ? LIMIT 1", (name,)).fetchone()
    return r


def _ensure_org(conn, name):
    """匹配不到时建立一条仅含名称的机构记录，便于后续补全。"""
    r = _find_org(conn, name)
    if r:
        return r["org_id"], False
    oid = "ext:" + name
    db.upsert_org(conn, {"org_id": oid, "name": name})
    return oid, True


def fetch(conn, verbose=True, max_items=None):
    """抓取并入库。多个候选源取第一个可解析成功且含名单的。"""
    t0 = time.time()
    parsed, used = None, None
    for url, tag in SOURCES:
        try:
            html = fetch_text(url)
        except Exception as e:
            if verbose:
                print(f"  [{tag}] 抓取失败：{type(e).__name__}", flush=True)
            continue
        p = parse(html)
        if p["batches"] or p["cancelled"]:
            parsed, used = p, (url, tag)
            if verbose:
                print(f"  [{tag}] 解析成功：文号 {p['doc_no']}｜"
                      f"{len(p['batches'])} 个批次｜取消 {len(p['cancelled'])} 段", flush=True)
            break

    if not parsed:
        return {"qual_type": QUAL_R3, "error": "所有候选源均未解析出名单",
                "seconds": round(time.time() - t0, 1)}

    url, tag = used
    n_list = n_new = n_cancel = n_ext = 0
    seen = []

    for b in parsed["batches"]:
        ev = f"{parsed['doc_no']} {b['title']}"
        for nm in b["names"]:
            if max_items and n_list >= max_items:
                break
            oid, created = _ensure_org(conn, nm)
            n_ext += 1 if created else 0
            seen.append(oid)
            db.set_qual(conn, oid, QUAL_R3, 1, name=nm,
                        source=f"财政部/税务总局/民政部公告 {parsed['doc_no']}",
                        source_url=url, evidence=ev,
                        valid_from=b["from"], valid_to=b["to"])
            db.snapshot(conn, oid, QUAL_R3, f"{b['from']}-{b['to']}")
            n_list += 1

    for c in parsed["cancelled"]:
        for nm in c["names"]:
            oid, created = _ensure_org(conn, nm)
            n_ext += 1 if created else 0
            db.set_qual(conn, oid, QUAL_R3, 0, name=nm,
                        source=f"财政部/税务总局/民政部公告 {parsed['doc_no']}",
                        source_url=url, evidence=c["title"])
            db.snapshot(conn, oid, QUAL_R3, "已取消")
            n_cancel += 1

    expired = 0
    if not max_items:
        expired = db.mark_missing(
            conn, QUAL_R3, set(seen), url, change_type="退出名单", new_value="无")
    conn.commit()

    if verbose:
        print(f"[R3] 入库 {n_list} 家｜取消资格 {n_cancel} 家｜"
              f"新建机构记录 {n_ext} 条｜退出名单 {expired}｜"
              f"{time.time()-t0:.1f}s", flush=True)

    return {"qual_type": QUAL_R3, "doc_no": parsed["doc_no"], "source": tag,
            "listed": n_list, "cancelled": n_cancel, "new_org": n_ext,
            "expired": expired, "batches": len(parsed["batches"]),
            "seconds": round(time.time() - t0, 1)}
