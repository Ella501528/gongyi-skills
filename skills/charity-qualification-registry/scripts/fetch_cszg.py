# -*- coding: utf-8 -*-
"""慈善中国（cszg.mca.gov.cn）名录抓取。

覆盖：
    R1  慈善组织登记认定名录
    R2  公开募捐资格名录
    R6  活动异常名录 / 严重违法失信名单

实现要点：
    · 走站点自身的列表 AJAX 接口，不解析页面 DOM：
        /biz/ma/csmh/a/csmhaDoSortNew.html      列表（返回 HTML 表格片段）
        /biz/ma/csmh/a/csmhaDoSortCountNew.html 总数（返回 JSON）
      接口与页面共用同一会话，需先通过一次滑块校验。
    · 每页 15 条；翻页由 pageNo 参数控制，无需点击。
    · 组织类别可由统一社会信用代码前两位推断：
        51 社会团体 / 52 民办非企业单位 / 53 基金会

筛选参数取值（站点前端 choose* 函数定义）：
    zzlb  组织类别   0 全部 / 1 社会团体 / 2 民办非企业单位 / 3 基金会
    zzzt  组织状态   0 全部 / 1 正常 / 2 注销 / 3 撤销
    xyzk  信用状况   0 全部 / 1 正常 / 2 活动异常名录 / 3 严重违法失信名单
    mjzg  募捐资格   0 全部 / 1 是 / 2 否
    djnx  登记年限   0 全部 / 1 一年内 / 2 一到五年 / 3 五到十年 / 4 十年以上
    azzx0023  登记区域代码（12 位，如 110000000000 北京）
    benji     本级 0 / 1
"""
import re
import time

from core import session as S, db

LIST_URL = S.B + "/biz/ma/csmh/a/csmhaindex.html"
API_LIST = S.B + "/biz/ma/csmh/a/csmhaDoSortNew.html"
API_CNT = S.B + "/biz/ma/csmh/a/csmhaDoSortCountNew.html"

PAGE_SIZE = 15
PACE = float(__import__("os").environ.get("CQR_PACE", "0.8"))

QUAL_ORG = "R1 慈善组织登记认定"
QUAL_MJZG = "R2 公开募捐资格"
QUAL_CREDIT = "R6 信用状况"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

# 统一社会信用代码前两位 = 登记管理部门 + 机构类别。
# 1 系为机构编制部门登记（机关／事业／人民团体），5 系为民政部门登记的社会组织。
USCC_TYPE = {
    "51": "社会团体",
    "52": "民办非企业单位",
    "53": "基金会",
    "11": "机关法人",
    "12": "事业单位法人",
    "13": "人民团体",
}

# 常用区域代码
REGIONS = {
    "北京": "110000000000", "上海": "310000000000", "天津": "120000000000",
    "重庆": "500000000000", "广州": "440100000000", "深圳": "440300000000",
    "广东": "440000000000", "江苏": "320000000000", "浙江": "330000000000",
    "山东": "370000000000", "湖北": "420000000000", "四川": "510000000000",
}


def norm_date(s):
    """站点返回英文月份（Aug 27, 2026），统一转 ISO。"""
    s = (s or "").strip()
    m = re.match(r"([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})", s)
    if m:
        mo = MONTHS.get(m.group(1).title())
        if mo:
            return f"{m.group(3)}-{mo:02d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def type_from_uscc(uscc, name=None):
    """由统一社会信用代码推断组织类别。

    慈善中国同时公示慈善组织与红十字会：后者多为人民团体性质
    （代码 13 开头），此处按名称细分，便于按类别筛选。
    """
    t = USCC_TYPE.get((uscc or "")[:2])
    if t == "人民团体" and name and "红十字" in name:
        return "红十字会"
    return t


def _clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def parse_rows(html):
    """解析接口返回的 HTML 表格片段。"""
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        m = re.search(r"aaee0101=([0-9a-zA-Z]+)", tr)
        if not m:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 5:
            continue
        name_cell = tds[2]
        # 名称列结构：
        #   <a href="...csmhadetail...?aaee0101=X">机构名称</a>
        #   <span>组织状态</span>          ← 正常／注销／撤销
        #   <span>被列入活动异常名录</span>  ← 信用状况（仅信用类名单出现）
        # 名称一律取详情链接的锚文本，标签单独提取，避免混入名称。
        a = re.search(r"<a[^>]*>(.*?)</a>", name_cell, re.S)
        nm = _clean(a.group(1)) if a else _clean(name_cell)
        tags = [_clean(t) for t in re.findall(r"<span[^>]*>(.*?)</span>", name_cell, re.S)]
        tags = [t for t in tags if t]

        status = tags[0] if tags else ""
        credit = ""
        for t in tags[1:]:
            if "被列入" in t:
                credit = t.replace("被列入", "").strip()
            elif t in ("活动异常名录", "严重违法失信名单"):
                credit = t
        out.append({
            "org_id": m.group(1),
            "uscc": _clean(tds[1]),
            "name": nm,
            "status": status,
            "credit_status": credit,
            "establish_date": norm_date(_clean(tds[3])),
            "registrar": _clean(tds[4]),
        })
    return out


def _params(pageNo, **kw):
    p = {"pageNo": pageNo, "aaee0102_03": "", "mjzg": "", "hszh": "", "djnx": "",
         "zzlb": "", "field": "aaee0105", "sort": "desc", "flag": "0",
         "azzx0023": "", "zzzt": "", "xyzk": "", "benji": "0"}
    p.update({k: str(v) for k, v in kw.items() if v is not None})
    p["_"] = int(time.time() * 1000)
    return p


def get_count(ctx, **filters):
    p = _params(1, **filters)
    p.pop("field"); p.pop("sort"); p.pop("pageNo")
    try:
        return ctx.request.get(API_CNT, params=p, timeout=40000).json().get("count")
    except Exception:
        return None


def get_page(ctx, pageNo, **filters):
    """取一页。返回行列表；返回 None 表示响应异常（会话失效／被拦截）。

    不能把「异常」和「末页无数据」混为一谈：前者需重新建立会话后重试，
    后者才应终止遍历。会话在长时间抓取后可能失效，届时接口返回的不是
    数据表格。此处以响应中是否含详情链接作为有效性判据。
    """
    r = ctx.request.get(API_LIST, params=_params(pageNo, **filters), timeout=40000)
    text = r.text()
    if "csmhadetail" not in text:
        return None
    return parse_rows(text)


def open_session(headless=True, verbose=False):
    """建立会话并确保已通过滑块校验。返回 (ctx, page)。"""
    ctx = S.open_ctx(headless=headless)
    pg = ctx.new_page()
    S.goto_checked(pg, ctx, LIST_URL, wait=4, verbose=verbose)
    return ctx, pg


def fetch(conn, qual_type, pace=None, max_pages=None, verbose=True,
          stop_after_known=0, mark_expired=True, seen_out=None, change_type="失效",
          start_page=1, **filters):
    """抓取一个筛选条件下的全部机构并入库。

    qual_type        写入 qual 表的资质类型
    max_pages        限制页数（None = 按 count 全量）
    start_page       起始页，用于中断后断点续抓
    stop_after_known 连续多少条已存在即提前停止（用于增量），0 = 不停
    mark_expired     是否在本次抓取后做「未出现即失效」的比对
    seen_out         外部传入的集合，用于跨多次 fetch 合并命中集合
    change_type      失效时写入变更日志的动作名
    返回统计 dict
    """
    pace = PACE if pace is None else pace
    ctx, pg = open_session(verbose=verbose)
    t0 = time.time()
    seen = seen_out if seen_out is not None else set()
    n_reconnect = 0
    n_new = n_upd = n_rows = 0
    try:
        total = get_count(ctx, **filters)
        if verbose:
            print(f"[慈善中国] 命中 {total} 家 | 筛选 {filters or '全量'}", flush=True)
        pages = max_pages if max_pages else (
            (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1)
        consecutive_known = 0
        for i in range(start_page, pages + 1):
            rows = get_page(ctx, i, **filters)
            if rows is None:
                # 会话失效（滑块或超时）：重新过校验后重试本页，不终止遍历
                n_reconnect += 1
                if verbose:
                    print(f"  第 {i} 页响应异常，重建会话（第 {n_reconnect} 次）…", flush=True)
                try:
                    S.goto_checked(pg, ctx, LIST_URL, wait=3, verbose=verbose)
                except Exception as e:
                    if verbose:
                        print(f"  重建会话失败：{e}", flush=True)
                time.sleep(1.5)
                rows = get_page(ctx, i, **filters)
                if rows is None:
                    if verbose:
                        print(f"  第 {i} 页仍异常，跳过", flush=True)
                    continue
            if not rows:
                break
            for r in rows:
                oid = r["org_id"]
                seen.add(oid)
                n_rows += 1
                exists = conn.execute(
                    "SELECT 1 FROM qual WHERE org_id = ? AND qual_type = ?",
                    (oid, qual_type)).fetchone() is not None
                if exists:
                    n_upd += 1
                    consecutive_known += 1
                else:
                    n_new += 1
                    consecutive_known = 0

                r["org_type"] = type_from_uscc(r["uscc"], r.get("name"))
                db.upsert_org(conn, r)

                if qual_type == QUAL_CREDIT:
                    db.set_qual(conn, oid, QUAL_CREDIT, 1, name=r["name"],
                                source="慈善中国", source_url=LIST_URL,
                                evidence=r.get("credit_status") or r.get("status"))
                elif qual_type == QUAL_MJZG:
                    db.set_qual(conn, oid, QUAL_MJZG, 1, name=r["name"],
                                source="慈善中国", source_url=LIST_URL,
                                evidence="列表筛选：是否具有公开募捐资格=是")
                elif qual_type == QUAL_ORG:
                    db.set_qual(conn, oid, QUAL_ORG, 1, name=r["name"],
                                source="慈善中国", source_url=LIST_URL)
                db.snapshot(conn, oid, qual_type,
                            r.get("credit_status") or r.get("status") or 1)

            conn.commit()
            if verbose and (i % 10 == 0 or i == pages):
                el = time.time() - t0
                print(f"  第 {i}/{pages} 页 | 累计 {n_rows} 条 | 新增 {n_new} "
                      f"| 用时 {el:.0f}s", flush=True)
            if stop_after_known and consecutive_known >= stop_after_known:
                if verbose:
                    print(f"  连续 {consecutive_known} 条已存在，提前结束", flush=True)
                break
            if i < pages:
                time.sleep(pace)
    finally:
        S.close_ctx(ctx)

    expired = 0
    if mark_expired and qual_type in (QUAL_MJZG, QUAL_CREDIT) and not max_pages:
        expired = db.mark_missing(conn, qual_type, seen, LIST_URL, change_type=change_type)
        conn.commit()

    return {"qual_type": qual_type, "rows": n_rows, "new": n_new,
            "updated": n_upd, "expired": expired, "pages": pages,
            "from_page": start_page, "reconnects": n_reconnect,
            "total": total, "seconds": round(time.time() - t0, 1)}
