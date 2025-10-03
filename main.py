# main.py
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time
import math
import requests

# ================== FastAPI ==================
app = FastAPI(title="Daily Proxy API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 前端跨域
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================== 环境变量 ==================
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")  # 备用，不强制用
FMP_API_KEY = os.getenv("FMP_API_KEY", "")

BASE_URL = os.getenv("BASE_URL", "https://daily-proxy-api.onrender.com")

HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "15"))

# ================== 轻量缓存（TTL） ==================
_cache: Dict[str, Dict[str, Any]] = {}
def cache_get(key: str, ttl: int) -> Optional[Any]:
    item = _cache.get(key)
    if not item:
        return None
    if time.time() - item["ts"] > ttl:
        return None
    return item["data"]

def cache_set(key: str, data: Any):
    _cache[key] = {"ts": time.time(), "data": data}

# ================== 小工具 ==================
def now_ts() -> int:
    return int(datetime.utcnow().timestamp())

def today_str() -> str:
    return date.today().isoformat()

def n_days_ago_str(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()

def parse_bool(v: Optional[str], default=False) -> bool:
    if v is None:
        return default
    return str(v).lower() in ["1", "true", "t", "yes", "y"]

def http_get_json(url: str, timeout: int = HTTP_TIMEOUT, raise_for_status=False) -> Any:
    r = requests.get(url, timeout=timeout)
    if raise_for_status:
        r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return None

# ================== 第三方 API 封装 ==================
def finnhub_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Finnhub 实时报价：c/h/l/o/pc/d/dp"""
    if not FINNHUB_API_KEY:
        return None
    key = f"fh_quote:{symbol}"
    cached = cache_get(key, ttl=8)
    if cached:
        return cached
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
    js = http_get_json(url)
    if not isinstance(js, dict):
        return None
    # Finnhub 自带 d/dp（相对前收）；没有 t，这里补当前时间戳
    out = {
        "symbol": symbol.upper(),
        "c": js.get("c"), "h": js.get("h"), "l": js.get("l"),
        "o": js.get("o"), "pc": js.get("pc"),
        "d": js.get("d"), "dp": js.get("dp"), "t": now_ts(),
    }
    cache_set(key, out)
    return out

def finnhub_profile(symbol: str) -> Optional[Dict[str, Any]]:
    if not FINNHUB_API_KEY:
        return None
    key = f"fh_profile:{symbol}"
    cached = cache_get(key, ttl=3600)
    if cached:
        return cached
    url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={FINNHUB_API_KEY}"
    js = http_get_json(url)
    cache_set(key, js)
    return js

def finnhub_company_news(symbol: str, days: int = 30) -> List[Dict[str, Any]]:
    if not FINNHUB_API_KEY:
        return []
    key = f"fh_news:{symbol}:{days}"
    cached = cache_get(key, ttl=300)
    if cached:
        return cached
    _from = n_days_ago_str(days)
    _to = today_str()
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={_from}&to={_to}&token={FINNHUB_API_KEY}"
    js = http_get_json(url)
    out = js if isinstance(js, list) else []
    # 截取前 10 条
    out = out[:10]
    cache_set(key, out)
    return out

def fred_latest(series_id: str) -> Optional[Dict[str, Any]]:
    if not FRED_API_KEY:
        return None
    key = f"fred:{series_id}"
    cached = cache_get(key, ttl=600)  # 10 分钟
    if cached:
        return cached
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
    js = http_get_json(url)
    obs = None
    try:
        obs = (js or {}).get("observations", [])[0]
    except Exception:
        obs = None
    if not obs:
        return None
    out = {"series": series_id, "date": obs.get("date"), "value": obs.get("value")}
    cache_set(key, out)
    return out

def fmp_etf_holdings(etf: str) -> Any:
    """ETF 持仓（FMP）"""
    if not FMP_API_KEY:
        return None
    key = f"fmp_etf:{etf}"
    cached = cache_get(key, ttl=3600)
    if cached:
        return cached
    url = f"https://financialmodelingprep.com/api/v4/etf-holdings/{etf}?apikey={FMP_API_KEY}"
    js = http_get_json(url)
    cache_set(key, js)
    return js

def finnhub_candles(symbol: str, res: str, start_ts: int, end_ts: int) -> Optional[Dict[str, Any]]:
    if not FINNHUB_API_KEY:
        return None
    url = f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution={res}&from={start_ts}&to={end_ts}&token={FINNHUB_API_KEY}"
    js = http_get_json(url)
    if isinstance(js, dict) and js.get("s") == "ok":
        return js
    return None

def fmp_macro_calendar(frm: str, to: str) -> List[Dict[str, Any]]:
    if not FMP_API_KEY:
        return []
    url = f"https://financialmodelingprep.com/api/v4/economic_calendar?from={frm}&to={to}&apikey={FMP_API_KEY}"
    js = http_get_json(url)
    if not isinstance(js, list):
        return []
    KEYWORDS = ["CPI","PPI","Unemployment","Nonfarm","Payroll","FOMC","Federal Reserve","Fed","Core CPI","Core PPI"]
    def important(x):
        name = (x.get("event") or x.get("name") or "").lower()
        return any(k.lower() in name for k in KEYWORDS)
    return [x for x in js if important(x)]

# ================== 技术指标 ==================
def sma(values: List[float], n: int) -> Optional[float]:
    if not values or len(values) < n:
        return None
    try:
        return sum(values[-n:]) / n
    except Exception:
        return None

def atr14_from_daily(h: List[float], l: List[float], c: List[float]) -> Optional[float]:
    n = len(c)
    if n < 15:
        return None
    trs = []
    prev_close = c[0]
    for i in range(1, n):
        tr = max(h[i]-l[i], abs(h[i]-prev_close), abs(l[i]-prev_close))
        trs.append(tr)
        prev_close = c[i]
    if len(trs) < 14:
        return None
    return sum(trs[-14:]) / 14

def vwap_from_intraday(h: List[float], l: List[float], c: List[float], v: List[float]) -> Optional[float]:
    if not h or not v or len(h) != len(v):
        return None
    tv = 0.0
    tpv = 0.0
    for i in range(len(v)):
        try:
            tp = (h[i] + l[i] + c[i]) / 3.0
            vol = v[i]
            tv += vol
            tpv += tp * vol
        except Exception:
            continue
    return (tpv / tv) if tv > 0 else None

# ================== 根路径 & 健康检查 ==================
@app.get("/")
def root():
    return {"status": "ok", "message": "Daily Proxy API is running!", "time_utc": datetime.utcnow().isoformat() + "Z"}

@app.get("/healthcheck")
def healthcheck():
    return {"status": "running", "time_utc": datetime.utcnow().isoformat() + "Z"}

# ================== 行情：/price /prices ==================
@app.get("/price")
def price(symbol: str = Query(..., description="股票代码，如 TSLA")):
    q = finnhub_quote(symbol)
    if not q:
        return {"symbol": symbol.upper(), "error": "quote_unavailable"}
    return q

@app.get("/prices")
def prices(symbols: str = Query(..., description="逗号分隔，如 AAPL,TSLA,SPY")):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    out: Dict[str, Any] = {}
    if not syms:
        return out
    # 并发拉取
    with ThreadPoolExecutor(max_workers=min(8, len(syms))) as ex:
        futs = {ex.submit(finnhub_quote, s): s for s in syms}
        for fut in as_completed(futs):
            s = futs[fut]
            q = fut.result()
            out[s] = q if q else {"symbol": s, "error": "quote_unavailable"}
    return out

# ================== 聚合：/analyze /proxy ==================
@app.get("/analyze")
def analyze(ticker: str = "AAPL", etf: str = "SPY",
            include_account: Optional[str] = None,
            include_etf_holdings: Optional[str] = "false"):
    """
    返回：
    - price: Finnhub quote
    - company: Finnhub profile2
    - news: 近 30 天公司新闻
    - macro: 可选宏观（示例：CPI）
    - treasury: 2Y/5Y/10Y/30Y 最新观察值（FRED）
    - etf: ETF 持仓（FMP，开关）
    - account/positions/orders: Alpaca（开关）
    """
    result: Dict[str, Any] = {"ticker": ticker.upper()}

    # 行情
    try:
        result["price"] = finnhub_quote(ticker)
    except Exception as e:
        result["price_error"] = str(e)

    # 公司信息
    try:
        result["company"] = finnhub_profile(ticker)
    except Exception as e:
        result["company_error"] = str(e)

    # 公司新闻（近 30 天）
    try:
        result["news"] = finnhub_company_news(ticker, days=30)
    except Exception as e:
        result["news_error"] = str(e)

    # 宏观示例（CPI）
    try:
        if FRED_API_KEY:
            url = f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
            result["macro"] = http_get_json(url)
    except Exception as e:
        result["macro_error"] = str(e)

    # 国债收益率
    try:
        yields = {}
        for k, sid in {"US2Y": "DGS2", "US5Y": "DGS5", "US10Y": "DGS10", "US30Y": "DGS30"}.items():
            obs = fred_latest(sid)
            if obs:
                yields[k] = obs
        result["treasury"] = yields
    except Exception as e:
        result["treasury_error"] = str(e)

    # ETF 持仓（可选）
    try:
        if parse_bool(include_etf_holdings, default=False):
            result["etf"] = fmp_etf_holdings(etf)
    except Exception as e:
        result["etf_error"] = str(e)

    # Alpaca 模拟账户（可选）
    try:
        if parse_bool(include_account, default=False) and ALPACA_API_KEY and ALPACA_SECRET_KEY:
            headers = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}
            account = http_get_json(f"{ALPACA_BASE_URL}/v2/account")
            positions = http_get_json(f"{ALPACA_BASE_URL}/v2/positions")
            orders = http_get_json(f"{ALPACA_BASE_URL}/v2/orders")
            result["account"] = account
            result["positions"] = positions
            result["orders"] = orders
    except Exception as e:
        result["alpaca_error"] = str(e)

    result["server_time_utc"] = datetime.utcnow().isoformat() + "Z"
    return result

@app.get("/proxy")
def proxy(symbol: str = Query(..., description="股票代码"), etf: str = "SPY",
          include_account: Optional[str] = None,
          include_etf_holdings: Optional[str] = "false"):
    """
    兼容前端：内部调用 /analyze 返回 JSON
    """
    try:
        url = f"{BASE_URL}/analyze?ticker={symbol}&etf={etf}&include_account={include_account}&include_etf_holdings={include_etf_holdings}"
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        return resp.json()
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}

# ================== 市场聚合：/market ==================
@app.get("/market")
def market():
    """
    返回：
    - indices: 以 ETF 代理的指数价差（SPY/QQQ/DIA）
    - yields: FRED 真实国债收益率（US2Y/5Y/10Y/30Y）
    - etfs.snapshot: 核心 ETF 的快照（price 字段为 /price 形状）
    - news_top: 来自 SPY/QQQ 的头条若干
    """
    out: Dict[str, Any] = {"indices": {}, "yields": {}, "etfs": {"snapshot": {}}, "news_top": [], "extras": {}}
    core_indices = {"SPX_proxy_SPY": "SPY", "NDX_proxy_QQQ": "QQQ", "DJI_proxy_DIA": "DIA"}
    core_etfs = ["SPY","QQQ","VTI","IWM","DIA","TLT","IEF","HYG","LQD"]

    # 指数代理 + ETF 快照
    try:
        # 批量一次取完
        quotes = prices(",".join(list(set(list(core_indices.values()) + core_etfs))))
        # indices
        for k, sym in core_indices.items():
            q = quotes.get(sym) if isinstance(quotes, dict) else None
            out["indices"][k] = q
        # snapshot
        snap = {}
        for sym in core_etfs:
            q = quotes.get(sym) if isinstance(quotes, dict) else None
            if q:
                snap[sym] = {"price": q}
        out["etfs"]["snapshot"] = snap
    except Exception as e:
        out["indices_error"] = str(e)

    # 国债收益率
    try:
        for k, sid in {"US2Y": "DGS2", "US5Y": "DGS5", "US10Y": "DGS10", "US30Y": "DGS30"}.items():
            obs = fred_latest(sid)
            if obs:
                out["yields"][k] = obs
    except Exception as e:
        out["yields_error"] = str(e)

    # 头条（SPY/QQQ 取各 2 条）
    try:
        for sym in ["SPY","QQQ"]:
            arr = finnhub_company_news(sym, days=7)
            for n in arr[:2]:
                out["news_top"].append({
                    "headline": n.get("headline"),
                    "url": n.get("url"),
                    "source_symbol": sym,
                    "datetime": n.get("datetime"),
                })
    except Exception as e:
        out["news_error"] = str(e)

    out["extras"]["server_time_utc"] = datetime.utcnow().isoformat() + "Z"
    return out

# ================== 技术因子：/candles ==================
@app.get("/candles")
def candles(symbol: str, intraday_res: str = "5", days: int = 40):
    """
    返回技术因子：
    - 日线：MA5/20/50、ATR(14)、昨高/昨低、20日均量
    - 当日：5分钟(默认) VWAP / 当日高低 / 开盘 / 最新价
    - candles：最近 100 根当日K（o/h/l/c/v/t）
    """
    out = {"symbol": symbol.upper(), "daily": {}, "intraday": {}, "candles": {}}
    now = datetime.utcnow()
    end_ts = int(now.timestamp())
    start_daily = int((now - timedelta(days=max(days, 40) + 5)).timestamp())

    # 日线
    daily = finnhub_candles(symbol, "D", start_daily, end_ts)
    if daily:
        c = daily.get("c", []) or []
        h = daily.get("h", []) or []
        l = daily.get("l", []) or []
        v = daily.get("v", []) or []
        out["daily"] = {
            "ma5": sma(c, 5),
            "ma20": sma(c, 20),
            "ma50": sma(c, 50),
            "atr14": atr14_from_daily(h, l, c),
            "prev_high": h[-2] if len(h) >= 2 else None,
            "prev_low": l[-2] if len(l) >= 2 else None,
            "avg_vol20": sma(v, 20),
        }

    # 当日
    start_intraday = int(datetime(now.year, now.month, now.day).timestamp())
    intra = finnhub_candles(symbol, intraday_res, start_intraday, end_ts)
    if intra:
        h = intra.get("h", []) or []
        l = intra.get("l", []) or []
        c = intra.get("c", []) or []
        o = intra.get("o", []) or []
        v = intra.get("v", []) or []
        t = intra.get("t", []) or []
        out["intraday"] = {
            "res": intraday_res,
            "vwap": vwap_from_intraday(h, l, c, v),
            "day_high": max(h) if h else None,
            "day_low": min(l) if l else None,
            "open": o[0] if o else None,
            "last": c[-1] if c else None,
            "last_ts": t[-1] if t else None
        }
        k = max(0, len(t) - 100)
        out["candles"] = {"res": intraday_res, "t": t[k:], "o": o[k:], "h": h[k:], "l": l[k:], "c": c[k:], "v": v[k:]}

    out["server_time_utc"] = datetime.utcnow().isoformat() + "Z"
    return out

# ================== 事件日历：/events ==================
@app.get("/events")
def events(symbols: str = "", days: int = 14):
    """
    返回未来 days 天：
    - earnings: {symbol: [{date, hour, epsEstimate, revenueEstimate}]}
    - macro: 重点宏观（CPI/PPI/FOMC/NFP 等）
    """
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    today = datetime.utcnow().date()
    to = today + timedelta(days=days)
    out: Dict[str, Any] = {"earnings": {}, "macro": []}

    # earnings（Finnhub）
    try:
        if FINNHUB_API_KEY:
            from_str = today.isoformat(); to_str = to.isoformat()
            url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_str}&to={to_str}&token={FINNHUB_API_KEY}"
            js = http_get_json(url) or {}
            items = js.get("earningsCalendar", [])
            if syms:
                items = [x for x in items if (x.get("symbol") or "").upper() in syms]
            bysym: Dict[str, List[Dict[str, Any]]] = {}
            for it in items:
                s = (it.get("symbol") or "").upper()
                bysym.setdefault(s, []).append({
                    "date": it.get("date"),
                    "hour": it.get("hour"),
                    "epsEstimate": it.get("epsEstimate"),
                    "revenueEstimate": it.get("revenueEstimate")
                })
            out["earnings"] = bysym
    except Exception:
        out["earnings"] = {}

    # macro（FMP）
    try:
        out["macro"] = fmp_macro_calendar(today.isoformat(), to.isoformat())
    except Exception:
        out["macro"] = []

    out["server_time_utc"] = datetime.utcnow().isoformat() + "Z"
    return out

# ================== 本地开发入口（Render 会忽略） ==================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
