"""proxy_config.py - 讓抓取程式可選擇性透過代理連線
設定檔 proxy.conf（放在程式同一個資料夾，內容三行；不要上傳到 GitHub）：
    server=http://主機:埠號
    username=帳號
    password=密碼
沒有 proxy.conf 時，行為與原本完全相同（直接連線）。
"""
import os

CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy.conf")


def load():
    """回傳 Playwright 的 proxy 設定 dict；沒設定就回傳 None"""
    cfg = {}
    if os.path.exists(CONF):
        with open(CONF, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip().lower()] = v.strip()
    for k in ("server", "username", "password"):
        env = os.environ.get("MOMO_PROXY_" + k.upper())
        if env:
            cfg[k] = env
    if not cfg.get("server"):
        return None
    out = {"server": cfg["server"]}
    if cfg.get("username"):
        out["username"] = cfg["username"]
    if cfg.get("password"):
        out["password"] = cfg["password"]
    return out


def launch_args():
    """給 chromium.launch(**launch_args()) 用"""
    p = load()
    return {"proxy": p} if p else {}


def apply_light_mode(page):
    """用代理時（流量計費）不載入圖片、影片、字型，省流量；不影響文字數量資料"""
    if not load():
        return
    page.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ("image", "media", "font")
        else route.continue_(),
    )


INIT_JS = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"


def open_page(p):
    """開啟瀏覽器與分頁（新版無頭 + 去除自動化特徵 + 台灣語系時區）。有 proxy.conf 就走代理。
    回傳 (browser, page)。2026-11 起 momo 會擋舊版無頭瀏覽器，實測這組設定可通過。"""
    kw = dict(headless=True, channel="chromium",
              args=["--disable-blink-features=AutomationControlled"], **launch_args())
    try:
        browser = p.chromium.launch(**kw)
    except Exception:
        kw.pop("channel")          # 舊版 Playwright 沒有 channel=chromium 時退回一般無頭
        browser = p.chromium.launch(**kw)
    ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
          f"Chrome/{browser.version} Safari/537.36")
    ctx = browser.new_context(user_agent=ua, locale="zh-TW", timezone_id="Asia/Taipei")
    page = ctx.new_page()
    page.add_init_script(INIT_JS)
    apply_light_mode(page)
    return browser, page
