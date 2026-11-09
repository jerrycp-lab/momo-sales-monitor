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
