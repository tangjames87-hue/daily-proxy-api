# main.py  —— Daily Proxy API (改进版)
from fastapi import FastAPI, Query
import os, time, requests
from datetime import datetime, timedelta

app = FastAPI()

# ===== 读取环境变量 =====
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
FMP_API_KEY = os.getenv("FMP_API_KEY", "")

# ===== 简单缓存（内存，秒级） =====
_CACHE = {}  # key -> (ts, data)
def _cache_get(k, ttl=60):
    v = _CACHE.get(k)
    if not v: return None
    ts, data = v
    if time.time() - ts <= ttl:
        return data
    return None
def _cache_set(k, data): _CACHE[k] = (time.time(), data)

def _http_json(url, timeout=15):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

# ===== 公共：FRED 取最新有效值 =====
def fred_latest(series_id: str):
    if not FRED_API_KEY:
        return {"series": series_id, "value": None, "date": None, "note": "FRED_API_KEY missing"}
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=10")
    js = _http_json(url, timeout=12)
    for obs in js.get("observations", []):
        v = obs.get("value")
        if v not in (None, "", "."):
            try:
                return {"series": series_id, "value": float(v), "date": obs.get("date")}
            except:
                return {"series": series_id, "value": None, "date": obs.get("date")}
    return {"series": series_id, "value": None, "date": None}

# ===== 轻量行情：/price /prices 将在前端关注池使用 =====
@app.get("/price")
def price(symbol: str = Query(..., description="ticker, e.g. TSLA")):
    """
    统一返回 {c,h,l,d,dp,t} 风格（对齐 Finnhub quote）
    """
    cache_key = f"price:{symbol.upper()}"
    cached = _cache_get(cache_key, ttl=10)
    if cached: return cached

    out = {"symbol": symbol.upper()}
    try:
        # 你已有 FINNHUB_KEY，直接拉 quote（实时/延迟取决于账户）
        q = _http_json(f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}")
        out.update(q)
    except Exception as e:
        out["error"] = str(e)

    _cache_set(cache_key, out)
    return out

@app.get("/prices")
def prices(symbols: str = Query(..., description="comma separated, e.g. AAPL,TSLA,MSFT")):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return {s: price(s) for s in syms}

# ===== 聚合核心：analyze_core（避免 /proxy 再去网络自调用） =====
def analyze_core(ticker: str, etf: str = "SPY",
                 want_account: bool = False, want_etf_holdings: bool = True):
    result = {"ticker": ticker}

    # --- 股票行情 ---
    try:
        result["price"] = _http_json(
            f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}", timeout=12
        )
    except Exception as e:
        result["price_error"] = str(e)

    # --- 公司信息 ---
    try:
        result["company"] = _http_json(
            f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={FINNHUB_API_KEY}", timeout=12
        )
    except Exception as e:
        result["company_error"] = str(e)

    # --- 公司新闻：最近 14 天 ----
    try:
        to = datetime.utcnow().date()
        frm = to - timedelta(days=14)
        result["news"] = _http_json(
            f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={frm}&to={to}&token={FINNHUB_API_KEY}",
            timeout=15
        )
    except Exception as e:
        result["news_error"] = str(e)

    # --- 宏观（示例：CPI 全量，前端自行截取）---
    try:
        result["macro"] = _http_json(
            f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={FRED_API_KEY}&file_type=json",
            timeout=15
        )
    except Exception as e:
        result["macro_error"] = str(e)

    # --- 国债收益率：真数据（2Y/10Y/30Y） ---
    try:
        ticks = {"2Y": "DGS2", "10Y": "DGS10", "30Y": "DGS30"}
        yields = {}
        for k, sid in ticks.items():
            yields[k] = fred_latest(sid)
        result["treasury"] = yields
    except Exception as e:
        result["treasury_error"] = str(e)

    # --- ETF 持仓（可选，FMP 有 plan 限制；失败容错） ---
    if want_etf_holdings:
        try:
            result["etf"] = _http_json(
                f"https://financialmodelingprep.com/api/v4/etf-holdings/{etf}?apikey={FMP_API_KEY}", timeout=15
            )
        except Exception as e:
            result["etf_error"] = str(e)

    # --- Alpaca 模拟账户（可选，默认 False） ---
    if want_account:
        try:
            headers = {
                "APCA-API-KEY-ID": ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
            }
            account = _http_json(f"{ALPACA_BASE_URL}/v2/account", timeout=12)
            positions = _http_json(f"{ALPACA_BASE_URL}/v2/positions", timeout=12)
            orders = _http_json(f"{ALPACA_BASE_URL}/v2/orders", timeout=12)
            result["account"] = account
            result["positions"] = positions
            result["orders"] = orders
        except Exception as e:
            result["alpaca_error"] = str(e)

    return result

# ===== 根 & 健康检查 =====
@app.get("/")
def root(): return {"status": "ok", "message": "Daily Proxy API is running!"}

@app.get("/healthcheck")
def healthcheck(): return {"status": "running"}

# ===== /analyze：对外暴露，支持可选参数以控制成本 =====
@app.get("/analyze")
def analyze(
    ticker: str = "AAPL",
    etf: str = "SPY",
    include_account: bool = False,
    include_etf_holdings: bool = True
):
    cache_key = f"analyze:{ticker}:{etf}:{include_account}:{include_etf_holdings}"
    cached = _cache_get(cache_key, ttl=60)
    if cached: return cached

    data = analyze_core(
        ticker=ticker, etf=etf,
        want_account=include_account,
        want_etf_holdings=include_etf_holdings
    )
    _cache_set(cache_key, data)
    return data

# ===== /proxy：简化版，直返 analyze_core（不再网络自调用） =====
@app.get("/proxy")
def proxy(symbol: str = Query(..., description="股票代码"), etf: str = "SPY"):
    return analyze_core(symbol, etf, want_account=False, want_etf_holdings=True)

# ===== /market：统一市场聚合（真收益率 + 指数代理 + ETF 快照 + 头条） =====
@app.get("/market")
def market():
    cached = _cache_get("market", ttl=60)
    if cached: return cached

    # 1) 收益率（FRED 真数据）
    yields = {}
    for sid, name in [("DGS2","US2Y"), ("DGS5","US5Y"), ("DGS10","US10Y"), ("DGS30","US30Y")]:
        try:
            yields[name] = fred_latest(sid)
        except Exception as e:
            yields[name] = {"series": sid, "value": None, "date": None, "err": str(e)}

    # 2) ETF 快照（也充当指数代理）
    etfs = ["SPY","QQQ","VTI","IWM","DIA","TLT","IEF","HYG","LQD"]
    snapshot, news_top = {}, []
    for s in etfs:
        try:
            q = _http_json(f"https://finnhub.io/api/v1/quote?symbol={s}&token={FINNHUB_API_KEY}", timeout=8)
            snapshot[s] = {"symbol": s, "price": q}
        except Exception as e:
            snapshot[s] = {"symbol": s, "price": {}, "err": str(e)}
    # 新闻（从 SPY/QQQ 各取一条）
    for s in ["SPY","QQQ"]:
        try:
            to = datetime.utcnow().date()
            frm = to - timedelta(days=7)
            ns = _http_json(
                f"https://finnhub.io/api/v1/company-news?symbol={s}&from={frm}&to={to}&token={FINNHUB_API_KEY}",
                timeout=10
            )
            if isinstance(ns, list) and ns:
                top = ns[0]
                news_top.append({"headline": top.get("headline"), "url": top.get("url"), "source_symbol": s})
        except Exception:
            pass

    # 3) 指数（默认 ETF 代理；你有正规指数源再替换）
    indices = {
        "SPX_proxy_SPY": snapshot.get("SPY"),
        "NDX_proxy_QQQ": snapshot.get("QQQ"),
        "DJI_proxy_DIA": snapshot.get("DIA"),
    }

    result = {
        "indices": indices,
        "yields": yields,
        "etfs": {"snapshot": snapshot},
        "news_top": news_top,
        "extras": {}
    }
    _cache_set("market", result)
    return result
