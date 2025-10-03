# main.py
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time
import requests
import yfinance as yf

# ================== FastAPI ==================
app = FastAPI(title="Daily Proxy API", version="1.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 允许前端跨域
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================== ENV ==================
FINNHUB_API_KEY  = os.getenv("FINNHUB_API_KEY", "")
ALPACA_API_KEY   = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY= os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL  = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
FRED_API_KEY     = os.getenv("FRED_API_KEY", "")
FMP_API_KEY      = os.getenv("FMP_API_KEY", "")
BASE_URL         = os.getenv("BASE_URL", "https://daily-proxy-api.onrender.com")
HTTP_TIMEOUT     = int(os.getenv("HTTP_TIMEOUT", "15"))

# ================== 轻量 TTL 缓存 ==================
_cache: Dict[str, Dict[str, Any]] = {}
def cache_get(key: str, ttl: int) -> Optional[Any]:
    it = _cache.get(key)
    if not it: return None
    if time.time() - it["ts"] > ttl: return None
    return it["data"]

def cache_set(key: str, data: Any):
    _cache[key] = {"ts": time.time(), "data": data}

# ================== Utils ==================
def now_ts() -> int: return int(datetime.utcnow().timestamp())
def today_str() -> str: return date.today().isoformat()
def n_days_ago_str(n: int) -> str: return (date.today() - timedelta(days=n)).isoformat()

def http_get_json(url: str, timeout: int = HTTP_TIMEOUT, raise_for_status: bool = False) -> Any:
    r = requests.get(url, timeout=timeout)
    if raise_for_status: r.raise_for_status()
    try: return r.json()
    except Exception: return None

# ================== 第三方封装（Finnhub/FMP/yfinance） ==================
def finnhub_quote(symbol: str) -> Optional[Dict[str, Any]]:
    if not FINNHUB_API_KEY: return None
    key = f"fh_q:{symbol}"
    c = cache_get(key, ttl=8)
    if c: return c
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
    js = http_get_json(url)
    if not isinstance(js, dict): return None
    out = {
        "symbol": symbol.upper(),
        "c": js.get("c"), "h": js.get("h"), "l": js.get("l"),
        "o": js.get("o"), "pc": js.get("pc"),
        "d": js.get("d"), "dp": js.get("dp"), "t": now_ts(),
    }
    cache_set(key, out)
    return out

def finnhub_profile(symbol: str) -> Optional[Dict[str, Any]]:
    if not FINNHUB_API_KEY: return None
    key = f"fh_pf:{symbol}"
    c = cache_get(key, ttl=3600)
    if c: return c
    url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={FINNHUB_API_KEY}"
    js = http_get_json(url)
    cache_set(key, js)
    return js

def finnhub_company_news(symbol: str, days: int = 30) -> List[Dict[str, Any]]:
    if not FINNHUB_API_KEY: return []
    key = f"fh_news:{symbol}:{days}"
    c = cache_get(key, ttl=300)
    if c: return c
    _from, _to = n_days_ago_str(days), today_str()
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={_from}&to={_to}&token={FINNHUB_API_KEY}"
    js = http_get_json(url)
    out = js if isinstance(js, list) else []
    out = out[:10]
    cache_set(key, out)
    return out

def finnhub_candles(symbol: str, res: str, start_ts: int, end_ts: int) -> Optional[Dict[str, Any]]:
    if not FINNHUB_API_KEY: return None
    url = f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution={res}&from={start_ts}&to={end_ts}&token={FINNHUB_API_KEY}"
    js = http_get_json(url)
    if isinstance(js, dict) and js.get("s") == "ok": return js
    return None

def fred_latest(series_id: str) -> Optional[Dict[str, Any]]:
    if not FRED_API_KEY: return None
    key = f"fred:{series_id}"
    c = cache_get(key, ttl=600)
    if c: return c
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
    js = http_get_json(url)
    obs = None
    try: obs = (js or {}).get("observations", [])[0]
    except Exception: obs = None
    if not obs: return None
    out = {"series": series_id, "date": obs.get("date"), "value": obs.get("value")}
    cache_set(key, out)
    return out

def fmp_etf_holdings(etf: str) -> Any:
    if not FMP_API_KEY: return None
    key = f"fmp_etf:{etf}"
    c = cache_get(key, ttl=3600)
    if c: return c
    url = f"https://financialmodelingprep.com/api/v4/etf-holdings/{etf}?apikey={FMP_API_KEY}"
    js = http_get_json(url)
    cache_set(key, js)
    return js

# ---- FMP K 线回退 ----
def fmp_daily(symbol: str, limit: int = 120):
    if not FMP_API_KEY: return None
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?timeseries={limit}&apikey={FMP_API_KEY}"
    js = http_get_json(url)
    hist = (js or {}).get("historical") or []
    if not hist: return None
    hist = list(reversed(hist))   # 最早->最近
    o = [x.get("open") for x in hist]
    h = [x.get("high") for x in hist]
    l = [x.get("low") for x in hist]
    c = [x.get("close") for x in hist]
    v = [x.get("volume") for x in hist]
    t = []
    for x in hist:
        dt = x.get("date")
        try:
            t.append(int(datetime.fromisoformat(dt).timestamp()))
        except Exception:
            t.append(int(datetime.utcnow().timestamp()))
    if len(t) != len(c):
        base = datetime.utcnow() - timedelta(days=len(c))
        t = [int((base + timedelta(days=i)).timestamp()) for i in range(len(c))]
    return {"s":"ok","o":o,"h":h,"l":l,"c":c,"v":v,"t":t}

def fmp_intraday(symbol: str, interval: str = "5min", limit: int = 300):
    if not FMP_API_KEY: return None
    url = f"https://financialmodelingprep.com/api/v3/historical-chart/{interval}/{symbol}?apikey={FMP_API_KEY}"
    arr = http_get_json(url)
    if not isinstance(arr, list) or not arr: return None
    arr = list(reversed(arr))[-limit:]
    o = [x.get("open") for x in arr]
    h = [x.get("high") for x in arr]
    l = [x.get("low") for x in arr]
    c = [x.get("close") for x in arr]
    v = [x.get("volume") for x in arr]
    t = []
    for x in arr:
        dt = x.get("date")  # "YYYY-MM-DD HH:MM:SS"
        try: t.append(int(datetime.fromisoformat(dt).timestamp()))
        except Exception: t.append(int(datetime.utcnow().timestamp()))
    return {"s":"ok","o":o,"h":h,"l":l,"c":c,"v":v,"t":t}

# ---- yfinance 帮助函数 ----
def yf_history(symbol: str, period: str, interval: str):
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval=interval, auto_adjust=False, prepost=False)
        if df is None or df.empty:
            df = yf.download(symbol, period=period, interval=interval, progress=False, prepost=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        df = df.dropna()
        o = df["Open"].tolist(); h = df["High"].tolist(); l = df["Low"].tolist()
        c = df["Close"].tolist(); v = df["Volume"].tolist()
        tlist = [int(ts.timestamp()) for ts in df.index.to_pydatetime()]
        return {"s":"ok","o":o,"h":h,"l":l,"c":c,"v":v,"t":tlist}
    except Exception:
        return None

# ================== 指标 ==================
def sma(values: List[float], n: int) -> Optional[float]:
    if not values or len(values) < n: return None
    return sum(values[-n:]) / n

def atr14_from_daily(h: List[float], l: List[float], c: List[float]) -> Optional[float]:
    n = len(c)
    if n < 15: return None
    trs = []; prev_close = c[0]
    for i in range(1, n):
        tr = max(h[i]-l[i], abs(h[i]-prev_close), abs(l[i]-prev_close))
        trs.append(tr); prev_close = c[i]
    if len(trs) < 14: return None
    return sum(trs[-14:]) / 14

def vwap_from_intraday(h: List[float], l: List[float], c: List[float], v: List[float]) -> Optional[float]:
    if not h or not v or len(h) != len(v): return None
    tv = 0.0; tpv = 0.0
    for i in range(len(v)):
        tp = (h[i] + l[i] + c[i]) / 3.0
        vol = v[i]; tv += vol; tpv += tp * vol
    return (tpv / tv) if tv > 0 else None

# ================== 根 & 健康检查 ==================
@app.get("/")
def root():
    return {"status":"ok","message":"Daily Proxy API is running!","time_utc":datetime.utcnow().isoformat()+"Z"}

@app.get("/healthcheck")
def healthcheck():
    return {
        "status":"running",
        "time_utc":datetime.utcnow().isoformat()+"Z",
        "keys":{"FINNHUB":bool(FINNHUB_API_KEY),"FRED":bool(FRED_API_KEY),"FMP":bool(FMP_API_KEY)}
    }

# ================== /price /prices ==================
@app.get("/price")
def price(symbol: str = Query(..., description="股票代码，如 TSLA")):
    q = finnhub_quote(symbol)
    return q if q else {"symbol":symbol.upper(),"error":"quote_unavailable"}

@app.get("/prices")
def prices(symbols: str = Query(..., description="逗号分隔，如 AAPL,TSLA,SPY")):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    out: Dict[str, Any] = {}
    if not syms: return out
    with ThreadPoolExecutor(max_workers=min(8, len(syms))) as ex:
        futs = {ex.submit(finnhub_quote, s): s for s in syms}
        for fut in as_completed(futs):
            s = futs[fut]; q = fut.result()
            out[s] = q if q else {"symbol": s, "error":"quote_unavailable"}
    return out

# ================== /analyze /proxy ==================
@app.get("/analyze")
def analyze(ticker: str = "AAPL", etf: str = "SPY",
            include_account: Optional[str] = None,
            include_etf_holdings: Optional[str] = "false"):
    result: Dict[str, Any] = {"ticker": ticker.upper()}

    try: result["price"] = finnhub_quote(ticker)
    except Exception as e: result["price_error"] = str(e)

    try: result["company"] = finnhub_profile(ticker)
    except Exception as e: result["company_error"] = str(e)

    try: result["news"] = finnhub_company_news(ticker, days=30)
    except Exception as e: result["news_error"] = str(e)

    try:
        if FRED_API_KEY:
            url = f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
            result["macro"] = http_get_json(url)
    except Exception as e: result["macro_error"] = str(e)

    try:
        yields = {}
        for k, sid in {"US2Y":"DGS2","US5Y":"DGS5","US10Y":"DGS10","US30Y":"DGS30"}.items():
            obs = fred_latest(sid)
            if obs: yields[k] = obs
        result["treasury"] = yields
    except Exception as e: result["treasury_error"] = str(e)

    try:
        if include_etf_holdings and include_etf_holdings.lower() in ("1","true","yes","y"):
            result["etf"] = fmp_etf_holdings(etf)
    except Exception as e: result["etf_error"] = str(e)

    try:
        if include_account and include_account.lower() in ("1","true","yes","y") and ALPACA_API_KEY and ALPACA_SECRET_KEY:
            account   = http_get_json(f"{ALPACA_BASE_URL}/v2/account")
            positions = http_get_json(f"{ALPACA_BASE_URL}/v2/positions")
            orders    = http_get_json(f"{ALPACA_BASE_URL}/v2/orders")
            result["account"], result["positions"], result["orders"] = account, positions, orders
    except Exception as e: result["alpaca_error"] = str(e)

    result["server_time_utc"] = datetime.utcnow().isoformat()+"Z"
    return result

@app.get("/proxy")
def proxy(symbol: str = Query(..., description="股票代码"), etf: str = "SPY",
          include_account: Optional[str] = None,
          include_etf_holdings: Optional[str] = "false"):
    try:
        url = f"{BASE_URL}/analyze?ticker={symbol}&etf={etf}&include_account={include_account}&include_etf_holdings={include_etf_holdings}"
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        return resp.json()
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}

# ================== /market ==================
@app.get("/market")
def market():
    out: Dict[str, Any] = {"indices":{}, "yields":{}, "etfs":{"snapshot":{}}, "news_top":[], "extras":{}}
    core_indices = {"SPX_proxy_SPY":"SPY", "NDX_proxy_QQQ":"QQQ", "DJI_proxy_DIA":"DIA"}
    core_etfs = ["SPY","QQQ","VTI","IWM","DIA","TLT","IEF","HYG","LQD"]

    try:
        sym_list = ",".join(sorted(set(list(core_indices.values()) + core_etfs)))
        quotes = http_get_json(f"{BASE_URL}/prices?symbols={sym_list}") or {}
        for k, sym in core_indices.items():
            q = quotes.get(sym)
            if q: out["indices"][k] = q
        snap = {}
        for sym in core_etfs:
            q = quotes.get(sym)
            if q: snap[sym] = {"price": q}
        out["etfs"]["snapshot"] = snap
    except Exception as e:
        out["indices_error"] = str(e)

    try:
        for k, sid in {"US2Y":"DGS2","US5Y":"DGS5","US10Y":"DGS10","US30Y":"DGS30"}.items():
            obs = fred_latest(sid)
            if obs: out["yields"][k] = obs
    except Exception as e:
        out["yields_error"] = str(e)

    try:
        for sym in ["SPY","QQQ"]:
            arr = finnhub_company_news(sym, days=7)
            for n in arr[:2]:
                out["news_top"].append({
                    "headline": n.get("headline"),
                    "url": n.get("url"),
                    "source_symbol": sym,
                    "datetime": n.get("datetime")
                })
    except Exception as e:
        out["news_error"] = str(e)

    out["extras"]["server_time_utc"] = datetime.utcnow().isoformat()+"Z"
    return out

# ================== /candles ==================
@app.get("/candles")
def candles(symbol: str, intraday_res: str = "5", days: int = 40, debug: int = 0):
    """
    返回：
      daily:  ma5/20/50, atr14, prev_high/prev_low, avg_vol20
      intraday: vwap, day_high/day_low, open, last
      candles: 最近100根 o/h/l/c/v/t
      sources: 数据源(finnhub|yfinance|fmp)
      errors:  错误提示
    """
    out = {"symbol":symbol.upper(), "daily":{}, "intraday":{}, "candles":{}, "sources":{}, "errors":[]}
    now = datetime.utcnow()
    end_ts = int(now.timestamp())
    start_daily = int((now - timedelta(days=max(days,40)+5)).timestamp())

    # ---- 日线 Finnhub -> yfinance -> FMP ----
    daily_src = None
    daily = finnhub_candles(symbol, "D", start_daily, end_ts)
    if daily: daily_src = "finnhub"
    else:
        daily = yf_history(symbol, period=f"{max(days,40)+5}d", interval="1d")
        if daily: daily_src = "yfinance"
        else:
            daily = fmp_daily(symbol, limit=max(days,120))
            if daily: daily_src = "fmp"
            else: out["errors"].append("daily_no_data")

    if daily:
        c = daily.get("c", []) or []
        h = daily.get("h", []) or []
        l = daily.get("l", []) or []
        v = daily.get("v", []) or []
        out["daily"] = {
            "ma5": sma(c,5), "ma20": sma(c,20), "ma50": sma(c,50),
            "atr14": atr14_from_daily(h,l,c),
            "prev_high": h[-2] if len(h)>=2 else None,
            "prev_low":  l[-2] if len(l)>=2 else None,
            "avg_vol20": sma(v,20),
        }
    out["sources"]["daily"] = daily_src

    # ---- 分钟 Finnhub -> yfinance -> FMP ----
    intra_src = None
    start_intraday = int(datetime(now.year, now.month, now.day).timestamp())
    intra = finnhub_candles(symbol, intraday_res, start_intraday, end_ts)
    if intra: intra_src = "finnhub"
    else:
        candidates = [f"{intraday_res}m"] if intraday_res.isdigit() else []
        for iv in ["1m","2m","5m"]:
            if iv not in candidates: candidates.append(iv)
        yfintra = None
        for iv in candidates:
            yfintra = yf_history(symbol, period="7d", interval=iv)
            if yfintra: break
        intra = yfintra
        if intra: intra_src = "yfinance"
        else:
            iv_map = {"1":"1min","2":"1min","5":"5min","15":"15min","30":"30min","60":"1hour"}
            fiv = iv_map.get(intraday_res, "5min")
            intra = fmp_intraday(symbol, interval=fiv, limit=300)
            if intra: intra_src = "fmp"
            else: out["errors"].append("intraday_no_data")

    if intra:
        h = intra.get("h", []) or []
        l = intra.get("l", []) or []
        c = intra.get("c", []) or []
        o = intra.get("o", []) or []
        v = intra.get("v", []) or []
        t = intra.get("t", []) or []
        out["intraday"] = {
            "res": intraday_res,
            "vwap": vwap_from_intraday(h,l,c,v),
            "day_high": max(h) if h else None,
            "day_low":  min(l) if l else None,
            "open": o[0] if o else None,
            "last": c[-1] if c else None,
            "last_ts": t[-1] if t else None
        }
        k = max(0, len(t)-100)
        out["candles"] = {"res":intraday_res, "t":t[k:], "o":o[k:], "h":h[k:], "l":l[k:], "c":c[k:], "v":v[k:]}

    out["sources"]["intraday"] = intra_src
    out["server_time_utc"] = datetime.utcnow().isoformat()+"Z"
    if debug:
        out["debug"] = {
            "daily_len": len(daily.get("c",[])) if daily else 0,
            "intra_len": len(intra.get("c",[])) if intra else 0
        }
    return out

# ================== /events ==================
@app.get("/events")
def events(symbols: str = "", days: int = 14):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    today = datetime.utcnow().date()
    to = today + timedelta(days=days)
    out: Dict[str, Any] = {"earnings": {}, "macro": []}

    try:
        if FINNHUB_API_KEY:
            from_str = today.isoformat(); to_str = to.isoformat()
            url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_str}&to={to_str}&token={FINNHUB_API_KEY}"
            js = http_get_json(url) or {}
            items = js.get("earningsCalendar", [])
            if syms: items = [x for x in items if (x.get("symbol") or "").upper() in syms]
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

    try:
        out["macro"] = (lambda frm,to: (
            fmp_macro_calendar(frm,to) if FMP_API_KEY else []
        ))(today.isoformat(), to.isoformat())
    except Exception:
        out["macro"] = []

    out["server_time_utc"] = datetime.utcnow().isoformat()+"Z"
    return out

# ================== 本地启动 ==================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT","8000")), reload=True)
