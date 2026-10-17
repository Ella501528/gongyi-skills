# -*- coding: utf-8 -*-
"""浏览器会话与慈善中国滑块验证处理（自包含，不依赖外部工具目录）。

慈善中国（cszg.mca.gov.cn）对列表页与详情页都会做一次滑块校验：
首次访问会被重定向到 `/biz/ma/csmh/filter/slideCaptchaindex.html`，
通过后同一会话内不再拦截。

求解思路：
    1. 请求 getSlideCaptcha 拿到背景图与缺口图；
    2. 对背景图做反混合网格搜索（α ∈ 若干候选）定位缺口左边界 x，
       并以亮度差法兜底；
    3. 在**验证页上下文**调用站内 `encode64` 编码答案，
       提交 slideCaptchaCheck，等待 status == "success"。

该流程完全走网络请求与页面内脚本，不模拟鼠标轨迹，因此无头模式即可运行。
"""
import base64
import io
import os
import time

B = "https://cszg.mca.gov.cn"
CAPTCHA_PAGE = B + "/biz/ma/csmh/filter/slideCaptchaindex.html"

PROFILE = os.environ.get("CQR_PROFILE") or os.path.join(
    os.path.expanduser("~"), ".workbuddy", "charity-qualification-registry", "profile")

_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-blink-features=AutomationControlled",
]


def _headless(flag=None):
    if flag is not None:
        return bool(flag)
    return os.environ.get("CQR_HEADLESS", "1").strip().lower() in ("1", "true", "yes")


def open_ctx(profile=None, headless=None, args=None, timeout=90000):
    """打开持久化浏览器上下文。返回 context，调用方负责 close()。"""
    from playwright.sync_api import sync_playwright

    prof = profile or PROFILE
    os.makedirs(prof, exist_ok=True)
    hl = _headless(headless)

    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=prof,
        headless=hl,
        args=list(_ARGS) + list(args or []) + ([] if hl else ["--start-maximized"]),
        viewport=None if not hl else {"width": 1440, "height": 900},
        no_viewport=not hl,
        ignore_https_errors=True,
        timeout=timeout,
    )
    ctx._cqr_pw = pw          # 便于统一关闭
    return ctx


def close_ctx(ctx):
    try:
        pw = getattr(ctx, "_cqr_pw", None)
        ctx.close()
    finally:
        try:
            if pw:
                pw.stop()
        except Exception:
            pass


# ---------------------------------------------------------------- 滑块求解
def _b64img(s):
    from PIL import Image
    s = (s or "").replace("\r", "").replace("\n", "")
    return Image.open(io.BytesIO(base64.b64decode(s))).convert("RGB")


def locate_x(ori_img, cut_img, ypos):
    """定位缺口左边界。

    背景图中的缺口是「原图 × α + 白 × (1-α)」的半透明覆盖，
    因此对 α 做网格搜索，取反混合后与缺口块残差最小的 x。
    """
    import numpy as np

    ori = np.array(ori_img).astype(np.float32)
    cn = np.array(cut_img)
    if cn.ndim == 2:
        cn = np.dstack([cn] * 3 + [np.full(cn.shape, 255, np.uint8)])
    if cn.shape[2] == 4:
        m = cn[:, :, 3] > 40
    else:
        m = np.ones(cn.shape[:2], bool)
    ys, xs = np.where(m)
    if len(ys) == 0:
        return None, "缺口块无有效像素"

    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    mm = m[y0:y1, x0:x1]
    ph, pw = mm.shape
    cut = cn[y0:y1, x0:x1, :3].astype(np.float32)
    H, W = ori.shape[:2]
    ypos = max(0, min(ypos, H - ph))
    band = ori[ypos:ypos + ph]

    results = {}
    best_fit = None
    for alpha in (0.5, 0.6, 0.7, 0.4, 0.3, 0.8):
        est = np.clip((band - 255.0 * (1.0 - alpha)) / alpha, 0, 255)
        best = None
        for x in range(0, W - pw + 1):
            seg = est[:, x:x + pw]
            d = np.abs(seg - cut).sum(axis=2)
            sc = d[mm].mean()
            if best is None or sc < best[1]:
                best = (x, sc)
        if best:
            results[f"a{alpha}"] = best
            if best_fit is None or best[1] < best_fit[1]:
                best_fit = (best[0], best[1], alpha)

    b = ori.min(axis=2)
    bb = None
    for x in range(0, W - pw + 1):
        seg = b[ypos:ypos + ph, x:x + pw]
        sc = seg[mm].mean() - (seg[~mm].mean() if (~mm).any() else 0)
        if bb is None or sc > bb[1]:
            bb = (x, sc)
    if bb:
        results["bright"] = bb

    diag = f"缺口块 {pw}x{ph} ypos={ypos}"
    if best_fit:
        results["best"] = (best_fit[0], best_fit[1])
        diag += f" 最优α={best_fit[2]}"
    return results, diag


def _guess_order(res):
    order = []
    if "best" in res:
        order.append(res["best"][0])
    for k in sorted((k for k in res if k.startswith("a")), key=lambda k: res[k][1]):
        order.append(res[k][0])
    if "bright" in res:
        order.append(res["bright"][0])
    seen, out = set(), []
    for x in order:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _submit(pg, x):
    try:
        enc = pg.evaluate("(v) => encode64(String(v))", str(x))
    except Exception:
        enc = str(x)
    try:
        out = pg.evaluate(
            """async (val) => {
                const r = await fetch('/biz/ma/csmh/filter/slideCaptchaCheck.html?slidevalue=' +
                    encodeURIComponent(val), {credentials:'include'});
                return await r.text();
            }""", enc)
    except Exception as e:
        return f"<err {e}>"
    import json
    try:
        return json.loads(out).get("status", "")
    except Exception:
        return str(out)[:80]


def solve(pg, ctx, tries=8, per_try=3, verbose=False):
    """处理滑块校验。返回 True/False。"""
    if "slideCaptcha" not in (pg.url or ""):
        try:
            pg.goto(CAPTCHA_PAGE, timeout=60000, wait_until="domcontentloaded")
            time.sleep(2)
        except Exception:
            pass
    for t in range(1, tries + 1):
        r = ctx.request.get(
            f"{B}/biz/ma/csmh/filter/getSlideCaptcha.html?t={int(time.time()*1000)}",
            timeout=40000)
        try:
            j = r.json()["c"]
        except Exception:
            return "slideCaptcha" not in (pg.url or "")
        ori = _b64img(j["oriImage"])
        cut = _b64img(j["cutImage"])
        ypos = int(j.get("ypos", 0))
        res, diag = locate_x(ori, cut, ypos)
        if not isinstance(res, dict):
            if verbose:
                print(f"  [{t}] {diag}")
            continue
        cands = _guess_order(res)[:per_try]
        if verbose:
            print(f"  [{t}] {diag} | 候选 x: {cands}")
        for x in cands:
            st = _submit(pg, x)
            if verbose:
                print(f"       x={x} → {st}")
            if st == "success":
                return True
            if "invalid" in str(st):
                break
        time.sleep(2)
    return False


def goto_checked(pg, ctx, url, wait=4.0, verbose=False):
    """导航到目标页；若被拦到滑块页，过关后重新进入。"""
    pg.goto(url, timeout=60000, wait_until="domcontentloaded")
    time.sleep(wait)
    if "slideCaptcha" in (pg.url or ""):
        if not solve(pg, ctx, verbose=verbose):
            raise RuntimeError("滑块校验未通过，无法访问：" + url)
        pg.goto(url, timeout=60000, wait_until="domcontentloaded")
        time.sleep(wait)
    return pg
