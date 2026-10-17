# -*- coding: utf-8 -*-
"""名录库的存储层：SQLite schema 与读写接口。

四张表：
    org        机构主表（一机构一行）
    qual       资质表（机构 × 资质类型）
    snapshot   快照表（按抓取批次保留历史值，用于比对）
    changelog  变更日志（新增 / 失效 / 值变更）
"""
import csv
import io
import os
import sqlite3
import time

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS org (
    org_id          TEXT PRIMARY KEY,
    uscc            TEXT,
    name            TEXT NOT NULL,
    org_type        TEXT,
    establish_date  TEXT,
    registrar       TEXT,
    prov            TEXT,
    city            TEXT,
    dist            TEXT,
    charity_date    TEXT,
    legal_person    TEXT,
    address         TEXT,
    business_scope  TEXT,
    status          TEXT,
    credit_status   TEXT,
    supervisor_unit TEXT,
    first_seen      TEXT,
    last_seen       TEXT
);
CREATE INDEX IF NOT EXISTS idx_org_name ON org(name);
CREATE INDEX IF NOT EXISTS idx_org_uscc ON org(uscc);
CREATE INDEX IF NOT EXISTS idx_org_reg  ON org(registrar);
CREATE INDEX IF NOT EXISTS idx_org_cred ON org(credit_status);

CREATE TABLE IF NOT EXISTS qual (
    org_id      TEXT NOT NULL,
    qual_type   TEXT NOT NULL,
    has_flag    INTEGER,
    grade       TEXT,
    valid_from  TEXT,
    valid_to    TEXT,
    source      TEXT,
    source_url  TEXT,
    evidence    TEXT,
    fetched_at  TEXT,
    PRIMARY KEY (org_id, qual_type)
);
CREATE INDEX IF NOT EXISTS idx_qual_type ON qual(qual_type);

CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_date TEXT NOT NULL,
    org_id        TEXT NOT NULL,
    qual_type     TEXT NOT NULL,
    value         TEXT,
    PRIMARY KEY (snapshot_date, org_id, qual_type)
);

CREATE TABLE IF NOT EXISTS changelog (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT,
    org_id      TEXT,
    name        TEXT,
    qual_type   TEXT,
    change_type TEXT,
    old_value   TEXT,
    new_value   TEXT,
    source_url  TEXT
);
CREATE INDEX IF NOT EXISTS idx_log_date ON changelog(date);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def today():
    return time.strftime("%Y-%m-%d")


def connect(path):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(path):
        _seed_from_csv(path)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---- 首次使用的种子建库 ----
# 发布包不携带二进制库文件（发布平台不接受 .db），改为携带 data/seed_org.csv 与
# data/seed_qual.csv 两份文本种子；首次连接、库文件尚不存在时，自动从种子建库。
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED_FILES = [("org", "seed_org.csv"), ("qual", "seed_qual.csv")]
INT_COLS = {"has_flag"}


def _seed_from_csv(db_path):
    """从 data/seed_*.csv 建库。成功返回写入行数，缺种子文件返回 0。"""
    root = os.path.join(SKILL_ROOT, "data")
    paths = [(t, os.path.join(root, fn)) for t, fn in SEED_FILES]
    if not all(os.path.exists(p) for _, p in paths):
        return 0
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    total = 0
    for table, path in paths:
        with io.open(path, encoding="utf-8", newline="") as f:
            rd = csv.reader(f)
            cols = next(rd)
            sql = "INSERT OR REPLACE INTO %s (%s) VALUES (%s)" % (
                table, ",".join(cols), ",".join(["?"] * len(cols)))
            batch = []
            for row in rd:
                vals = []
                for k, v in zip(cols, row):
                    if v == "":
                        vals.append(None)
                    elif k in INT_COLS:
                        try:
                            vals.append(int(v))
                        except ValueError:
                            vals.append(v)
                    else:
                        vals.append(v)
                batch.append(vals)
            if batch:
                conn.executemany(sql, batch)
                total += len(batch)
    row = conn.execute("SELECT MAX(fetched_at) FROM qual").fetchone()
    if row and row[0]:
        conn.execute("INSERT OR REPLACE INTO meta(k, v) VALUES ('last_update', ?)", (row[0][:10],))
    conn.commit()
    conn.close()
    return total


def set_meta(conn, k, v):
    conn.execute("INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)", (k, str(v)))


def get_meta(conn, k, default=None):
    row = conn.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
    return row["v"] if row else default


def upsert_org(conn, o):
    """写入/更新机构主表。已有记录保留 first_seen，仅填非空字段。"""
    oid = o.get("org_id")
    if not oid:
        return
    ts = now()
    cur = conn.execute("SELECT first_seen FROM org WHERE org_id = ?", (oid,)).fetchone()
    if cur:
        cols = ["uscc", "name", "org_type", "establish_date", "registrar", "prov",
                "city", "dist", "charity_date", "legal_person", "address",
                "business_scope", "status", "credit_status", "supervisor_unit"]
        sets, vals = [], []
        for c in cols:
            if o.get(c) not in (None, ""):
                sets.append(f"{c} = COALESCE(NULLIF(?, ''), {c})")
                vals.append(o.get(c))
        sets.append("last_seen = ?")
        vals.append(ts)
        vals.append(oid)
        conn.execute(f"UPDATE org SET {', '.join(sets)} WHERE org_id = ?", vals)
    else:
        conn.execute(
            """INSERT INTO org (org_id, uscc, name, org_type, establish_date, registrar,
                   prov, city, dist, charity_date, legal_person, address, business_scope,
                   status, credit_status, supervisor_unit, first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (oid, o.get("uscc"), o.get("name"), o.get("org_type"), o.get("establish_date"),
             o.get("registrar"), o.get("prov"), o.get("city"), o.get("dist"),
             o.get("charity_date"), o.get("legal_person"), o.get("address"),
             o.get("business_scope"), o.get("status"), o.get("credit_status"),
             o.get("supervisor_unit"), ts, ts))


def set_qual(conn, org_id, qual_type, has_flag, source=None, source_url=None,
             evidence=None, valid_from=None, valid_to=None, grade=None,
             name=None):
    """写入资质；若值发生变化则记入 changelog。"""
    old = conn.execute(
        "SELECT * FROM qual WHERE org_id = ? AND qual_type = ?", (org_id, qual_type)
    ).fetchone()
    ts = now()
    if old is None:
        conn.execute(
            """INSERT INTO qual (org_id, qual_type, has_flag, grade, valid_from, valid_to,
                   source, source_url, evidence, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (org_id, qual_type, has_flag, grade, valid_from, valid_to,
             source, source_url, evidence, ts))
        conn.execute(
            """INSERT INTO changelog (date, org_id, name, qual_type, change_type,
                   old_value, new_value, source_url) VALUES (?,?,?,?,?,?,?,?)""",
            (today(), org_id, name, qual_type, "新增", None,
             _val(has_flag, grade), source_url))
    else:
        if old["has_flag"] != has_flag or (old["grade"] or "") != (grade or ""):
            conn.execute(
                """INSERT INTO changelog (date, org_id, name, qual_type, change_type,
                       old_value, new_value, source_url) VALUES (?,?,?,?,?,?,?,?)""",
                (today(), org_id, name, qual_type, "值变更",
                 _val(old["has_flag"], old["grade"]), _val(has_flag, grade), source_url))
        conn.execute(
            """UPDATE qual SET has_flag = ?, grade = COALESCE(?, grade),
                   valid_from = COALESCE(?, valid_from), valid_to = COALESCE(?, valid_to),
                   source = COALESCE(?, source), source_url = COALESCE(?, source_url),
                   evidence = COALESCE(?, evidence), fetched_at = ?
               WHERE org_id = ? AND qual_type = ?""",
            (has_flag, grade, valid_from, valid_to, source, source_url,
             evidence, ts, org_id, qual_type))


def _val(flag, grade):
    s = {1: "有", 0: "无"}.get(flag, "" if flag is None else str(flag))
    if grade:
        s = f"{s}/{grade}" if s else str(grade)
    return s or None


def snapshot(conn, org_id, qual_type, value, date=None):
    conn.execute(
        "INSERT OR REPLACE INTO snapshot (snapshot_date, org_id, qual_type, value) VALUES (?,?,?,?)",
        (date or today(), org_id, qual_type, str(value)))


def mark_missing(conn, qual_type, seen_ids, source_url=None, change_type="失效",
                 new_value="无"):
    """批次结束后：本类型中未出现的机构，标记为失效并记日志。

    seen_ids 为空集合时直接返回，避免误清空。

    注意：同一资质类型若由多个筛选条件（分多次 fetch）合并而成，
    必须把各次的 seen 合并后**只调用一次**，否则先抓的批次会被后抓的批次误清。
    """
    if not seen_ids:
        return 0
    rows = conn.execute(
        "SELECT q.org_id, q.has_flag, o.name FROM qual q LEFT JOIN org o ON o.org_id = q.org_id "
        "WHERE q.qual_type = ? AND q.has_flag = 1", (qual_type,)).fetchall()
    n = 0
    for r in rows:
        if r["org_id"] in seen_ids:
            continue
        conn.execute(
            "UPDATE qual SET has_flag = 0, fetched_at = ? WHERE org_id = ? AND qual_type = ?",
            (now(), r["org_id"], qual_type))
        conn.execute(
            """INSERT INTO changelog (date, org_id, name, qual_type, change_type,
                   old_value, new_value, source_url) VALUES (?,?,?,?,?,?,?,?)""",
            (today(), r["org_id"], r["name"], qual_type, change_type, "有",
             new_value, source_url))
        n += 1
    return n


def stats(conn):
    out = {}
    for t in ("org", "qual", "snapshot", "changelog"):
        out[t] = conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
    return out
