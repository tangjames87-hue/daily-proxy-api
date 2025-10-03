# main.py
from fastapi import FastAPI, Query
import os, requests, pandas as pd
from datetime import datetime, timedelta, timezone

# -------------------- 环境变量 --------------------
FINNHUB_API_KEY  = os.getenv("FINNHUB_API_KEY", "")
FMP_API_KEY      = os.getenv("FMP_API_KEY", "")
FRED_API_KEY     = os.getenv("FRED_API_KEY", "")
POLYGON_API_KEY  = os.getenv("POLYGON_API_KEY", "")
BASE_URL         = os.getenv("BASE_URL", "https://daily-proxy-api.onrender.com")

app = FastAPI(title="Daily Proxy API", version="2025-10-03")

# -------------------- 工具 --------------------
def now_utc_str():
    return datetime.utcnow().isoformat() + "Z"

def http_json(url: str, timeout: int = 20):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def safe_round(x, p=4):
    try: return round(float(x), p)
    except Exception: return x

# -------------------- 基础 / 健康 --------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Daily Proxy API is running!", "time_utc": now_utc_str()}

@app.get("/healthcheck")
def healthcheck():
    keys = {
        "FINNHUB": bool(FINNHUB_API_KEY),
        "FRED":    bool(FRED_API_KEY),
        "FMP":     bool(FMP_API_KEY),
        "POLYGON": bool(POLYGON_API_KEY),
    }
    return {"status": "running", "time_utc": now_utc_str(), "keys": keys}

# -------------------- 报价 --------------------
def finnhub_quote(symbol: str):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
    try: j = http_json(url, timeout=15)
    except Exception as e: return {"symbol": symbol.upper(), "error": str(e)}
    return {
        "symbol": symbol.upper(), "c": j.get("c"), "h": j.get("h"), "l": j.get("l"),
        "o": j.get("o"), "pc": j.get("pc"), "d": j.get("d"), "dp": j.get("dp"), "t": j.get("t")
    }

@app.get("/price")
def price(symbol: str = Query(...)):
    return finnhub_quote(symbol)

@app.get("/prices")
def prices(symbols: str = Query(...)):
    out = {}
    for s in [x.strip().upper() for x in symbols.split(",") if x.strip()]:
        out[s] = finnhub_quote(s)
    return out

# -------------------- 个股聚合 --------------------
@app.get("/analyze")
def analyze(ticker: str = "AAPL", etf: str = "SPY"):
    result = {"ticker": ticker.upper()}
    # 行情
    try: result["price"] = finnhub_quote(ticker)
    except Exception as e: result["price_error"] = str(e)
    # 公司信息
    try:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={FINNHUB_API_KEY}"
        result["company"] = http_json(url, timeout=15)
    except Exception as e:
        result["company_error"] = str(e)
    # 公司新闻（30天）
    try:
        to_dt = datetime.utcnow().date(); from_dt = to_dt - timedelta(days=30)
        url = (f"https://finnhub.io/api/v1/company-news?symbol={ticker}"
               f"&from={from_dt}&to={to_dt}&token={FINNHUB_API_KEY}")
        result["news"] = http_json(url, timeout=20)
    except Exception as e:
        result["news_error"] = str(e)
    # CPI
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL"
               f"&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1")
        result["macro"] = http_json(url, timeout=20)
    except Exception as e:
        result["macro_error"] = str(e)
    # 国债收益率
    try:
        series = {"US2Y":"DGS2","US5Y":"DGS5","US10Y":"DGS10","US30Y":"DGS30"}
        yields = {}
        for k,sid in series.items():
            url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}"
                   f"&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1")
            d = http_json(url, timeout=15); obs = (d.get("observations") or [])
            if obs: yields[k] = {"series": sid, "date": obs[0]["date"], "value": obs[0]["value"]}
        result["treasury"] = yields
    except Exception as e:
        result["treasury_error"] = str(e)
    # ETF 持仓（可选）
    try:
        if FMP_API_KEY and etf:
            url = f"https://financialmodelingprep.com/api/v4/etf-holdings/{etf}?apikey={FMP_API_KEY}"
            result["etf"] = http_json(url, timeout=20)
    except Exception as e:
        result["etf_error"] = str(e)

    result["server_time_utc"] = now_utc_str()
    return result

@app.get("/proxy")
def proxy(symbol: str = Query(...), etf: str = "SPY"):
    try:
        url = f"{BASE_URL}/analyze?ticker={symbol}&etf={etf}"
        return http_json(url, timeout=30)
    except Exception as e:
        return {"error": str(e), "server_time_utc": now_utc_str()}

# -------------------- 市场聚合 --------------------
@app.get("/market")
def market():
    out = {"indices": {}, "yields": {}, "etfs": {"snapshot": {}}, "news_top": [], "extras": {}}
    try:
        out["indices"]["SPX_proxy_SPY"] = finnhub_quote("SPY")
        out["indices"]["NDX_proxy_QQQ"] = finnhub_quote("QQQ")
        out["indices"]["DJI_proxy_DIA"] = finnhub_quote("DIA")
    except Exception: pass
    try:
        series = {"US2Y":"DGS2","US5Y":"DGS5","US10Y":"DGS10","US30Y":"DGS30"}
        for k,sid in series.items():
            url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}"
                   f"&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1")
            d = http_json(url, timeout=15); obs=(d.get("observations") or [])
            if obs: out["yields"][k]={"series":sid,"date":obs[0]["date"],"value":obs[0]["value"]}
    except Exception: pass
    try:
        for e in ["SPY","QQQ","VTI","IWM","DIA","TLT","IEF","HYG","LQD"]:
            out["etfs"]["snapshot"][e] = {"price": finnhub_quote(e)}
    except Exception: pass
    try:
        to_dt = datetime.utcnow().date(); from_dt = to_dt - timedelta(days=7)
        for sym in ("SPY","QQQ"):
            url = (f"https://finnhub.io/api/v1/company-news?symbol={sym}"
                   f"&from={from_dt}&to={to_dt}&token={FINNHUB_API_KEY}")
            arr = http_json(url, timeout=15)[:2]
            for it in arr:
                out["news_top"].append({
                    "headline": it.get("headline"),
                    "url": it.get("url"),
                    "source_symbol": sym,
                    "datetime": it.get("datetime")
                })
    except Exception: pass
    out["extras"]["server_time_utc"] = now_utc_str()
    return out

# -------------------- Candles（yfinance → Polygon → Finnhub → FMP） --------------------
def _df_from_polygon_aggs(j):
    # polygon aggs: results: [{t(ms), o,h,l,c,v,...}]
    if not j or "results" not in j or not j["results"]:
        return None
    df = pd.DataFrame(j["results"])
    # t is epoch ms
    if "t" in df.columns:
        df["Datetime"] = pd.to_datetime(df["t"], unit="ms")
        df.set_index("Datetime", inplace=True)
    # 统一列名
    rename = {"o":"Open","h":"High","l":"Low","c":"Close","v":"Volume"}
    df.rename(columns=rename, inplace=True)
    df.sort_index(inplace=True)
    return df[["Open","High","Low","Close","Volume"]] if set(rename.values()).issubset(df.columns) else None

def _to_df_from_fmp_daily(j):
    if not j or "historical" not in j or not j["historical"]:
        return None
    df = pd.DataFrame(j["historical"])
    df.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"}, inplace=True)
    df = df.iloc[::-1].reset_index(drop=True)
    if "date" in df.columns:
        df["Date"] = pd.to_datetime(df["date"])
        df.set_index("Date", inplace=True)
    return df[["Open","High","Low","Close","Volume"]]

def _to_df_from_fmp_intraday(j):
    if not isinstance(j, list) or len(j)==0:
        return None
    df = pd.DataFrame(j)
    df.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"}, inplace=True)
    df = df.iloc[::-1].reset_index(drop=True)
    if "date" in df.columns:
        df["Datetime"] = pd.to_datetime(df["date"])
        df.set_index("Datetime", inplace=True)
    return df[["Open","High","Low","Close","Volume"]]

def _to_df_from_finnhub_candles(j):
    if not j or j.get("s")!="ok": return None
    df = pd.DataFrame({
        "Datetime": pd.to_datetime(j["t"], unit="s"),
        "Open": j["o"], "High": j["h"], "Low": j["l"], "Close": j["c"], "Volume": j["v"]
    })
    df.set_index("Datetime", inplace=True); df.sort_index(inplace=True)
    return df

def _calc_daily_indicators(df: pd.DataFrame):
    if df is None or df.empty or len(df)<50: return None
    w = df.copy()
    w["MA5"]  = w["Close"].rolling(5).mean()
    w["MA20"] = w["Close"].rolling(20).mean()
    w["MA50"] = w["Close"].rolling(50).mean()
    hl   = w["High"] - w["Low"]
    hc   = (w["High"] - w["Close"].shift(1)).abs()
    lc   = (w["Low"]  - w["Close"].shift(1)).abs()
    tr   = pd.concat([hl,hc,lc], axis=1).max(axis=1)
    w["ATR14"] = tr.rolling(14).mean()
    tail = w.iloc[-1]
    return {
        "ma5": safe_round(tail["MA5"]), "ma20": safe_round(tail["MA20"]),
        "ma50": safe_round(tail["MA50"]), "atr14": safe_round(tail["ATR14"]),
        "asof": w.index[-1].strftime("%Y-%m-%d")
    }

def _calc_intraday_snapshot(df_intra: pd.DataFrame):
    if df_intra is None or df_intra.empty: return None
    df = df_intra.copy()
    if df.index.tz is not None: df.index = df.index.tz_convert(None)
    last_day = df.index[-1].date()
    day_df = df[df.index.date == last_day]
    if day_df.empty: return None
    typical = (day_df["High"] + day_df["Low"] + day_df["Close"]) / 3.0
    vol = day_df["Volume"].replace(0, pd.NA).fillna(0)
    vwap = float((typical * vol).sum() / (vol.sum() or 1))
    return {
        "vwap": safe_round(vwap),
        "day_high": safe_round(day_df["High"].max()),
        "day_low":  safe_round(day_df["Low"].min()),
        "open":     safe_round(day_df["Open"].iloc[0]),
        "last":     safe_round(day_df["Close"].iloc[-1]),
        "date":     str(last_day)
    }

@app.get("/candles")
def candles(symbol: str = "TSLA", intraday_res: int = 5, debug: int = 0):
    out = {
        "symbol": symbol.upper(),
        "daily": {}, "intraday": {}, "candles": {},
        "sources": {"daily": None, "intraday": None},
        "errors": [], "server_time_utc": now_utc_str()
    }

    yf_daily_len = 0; yf_intra_len = 0

    # 1) yfinance
    try:
        import yfinance as yf
        ddf = yf.download(symbol, period="6mo", interval="1d", auto_adjust=False,
                          progress=False, threads=False, prepost=False)
        yf_daily_len = 0 if ddf is None else len(ddf)
        if ddf is not None and not ddf.empty:
            ddf = ddf.rename(columns=str.title)
            calc = _calc_daily_indicators(ddf)
            if calc: out["daily"]=calc; out["sources"]["daily"]="yfinance"
        interval = f"{max(1, min(int(intraday_res),60))}m"
        idf = yf.download(symbol, period="5d", interval=interval, auto_adjust=False,
                          progress=False, threads=False, prepost=False)
        yf_intra_len = 0 if idf is None else len(idf)
        if idf is not None and not idf.empty:
            idf = idf.rename(columns=str.title)
            snap = _calc_intraday_snapshot(idf)
            if snap: out["intraday"]=snap; out["sources"]["intraday"]="yfinance"
        if (out["sources"]["daily"] is None) or (out["sources"]["intraday"] is None):
            out["errors"].append("yf_empty")
    except Exception as e:
        out["errors"].append(f"yf_error:{e}")

    # 2) Polygon fallback
    try:
        if POLYGON_API_KEY:
            if out["sources"]["daily"] is None:
                fro = (datetime.utcnow().date() - timedelta(days=220)).isoformat()
                to  = datetime.utcnow().date().isoformat()
                url = (f"https://api.polygon.io/v2/aggs/ticker/{symbol.upper()}/range/1/day/{fro}/{to}"
                       f"?adjusted=true&sort=asc&limit=50000&apiKey={POLYGON_API_KEY}")
                j = http_json(url, timeout=20)
                df = _df_from_polygon_aggs(j)
                calc = _calc_daily_indicators(df)
                if calc: out["daily"]=calc; out["sources"]["daily"]="polygon"
            if out["sources"]["intraday"] is None:
                res = max(1, min(int(intraday_res),60))
                fro = (datetime.utcnow() - timedelta(days=7))
                to  = datetime.utcnow()
                url = (f"https://api.polygon.io/v2/aggs/ticker/{symbol.upper()}/range/{res}/minute/"
                       f"{fro.strftime('%Y-%m-%d')}/{to.strftime('%Y-%m-%d')}"
                       f"?adjusted=true&sort=asc&limit=50000&apiKey={POLYGON_API_KEY}")
                j = http_json(url, timeout=20)
                df = _df_from_polygon_aggs(j)
                snap = _calc_intraday_snapshot(df)
                if snap: out["intraday"]=snap; out["sources"]["intraday"]="polygon"
    except Exception as e:
        out["errors"].append(f"polygon_error:{e}")

    # 3) Finnhub 兜底
    try:
        if out["sources"]["daily"] is None and FINNHUB_API_KEY:
            fro = int((datetime.utcnow() - timedelta(days=400)).timestamp())
            to  = int(datetime.utcnow().timestamp())
            url = (f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution=D"
                   f"&from={fro}&to={to}&token={FINNHUB_API_KEY}")
            j = http_json(url, timeout=20)
            df = _to_df_from_finnhub_candles(j)
            calc = _calc_daily_indicators(df)
            if calc: out["daily"]=calc; out["sources"]["daily"]="finnhub"
        if out["sources"]["intraday"] is None and FINNHUB_API_KEY:
            fro = int((datetime.utcnow() - timedelta(days=7)).timestamp())
            to  = int(datetime.utcnow().timestamp())
            res = max(1, min(int(intraday_res),60))
            url = (f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution={res}"
                   f"&from={fro}&to={to}&token={FINNHUB_API_KEY}")
            j = http_json(url, timeout=20)
            df = _to_df_from_finnhub_candles(j)
            snap = _calc_intraday_snapshot(df)
            if snap: out["intraday"]=snap; out["sources"]["intraday"]="finnhub"
    except Exception as e:
        out["errors"].append(f"fh_error:{e}")

    # 4) FMP 最后
    try:
        if out["sources"]["daily"] is None and FMP_API_KEY:
            url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?timeseries=260&apikey={FMP_API_KEY}"
            j = http_json(url, timeout=20)
            df = _to_df_from_fmp_daily(j)
            calc = _calc_daily_indicators(df)
            if calc: out["daily"]=calc; out["sources"]["daily"]="fmp"
        if out["sources"]["intraday"] is None and FMP_API_KEY:
            res = max(1, min(int(intraday_res),60))
            url = f"https://financialmodelingprep.com/api/v3/historical-chart/{res}min/{symbol}?apikey={FMP_API_KEY}"
            j = http_json(url, timeout=20)
            df = _to_df_from_fmp_intraday(j)
            snap = _calc_intraday_snapshot(df)
            if snap: out["intraday"]=snap; out["sources"]["intraday"]="fmp"
    except Exception as e:
        out["errors"].append(f"fmp_error:{e}")

    if not out["daily"]: out["errors"].append("daily_no_data")
    if not out["intraday"]: out["errors"].append("intraday_no_data")

    if debug:
        out["debug"] = {"daily_len": int(yf_daily_len), "intra_len": int(yf_intra_len)}

    return out

# -------------------- 事件日历 --------------------
@app.get("/events")
def events(symbols: str = "AAPL,TSLA", days: int = 14):
    res = {"earnings": {}, "macro": [], "server_time_utc": now_utc_str()}
    try:
        to_dt = datetime.utcnow().date() + timedelta(days=max(1,int(days)))
        from_dt = datetime.utcnow().date()
        for sym in [x.strip().upper() for x in symbols.split(",") if x.strip()]:
            url = (f"https://finnhub.io/api/v1/calendar/earnings?from={from_dt}&to={to_dt}"
                   f"&symbol={sym}&token={FINNHUB_API_KEY}")
            j = http_json(url, timeout=20)
            arr = (j.get("earningsCalendar") or [])
            if arr:
                res["earnings"][sym] = [{
                    "date": it.get("date"), "hour": it.get("hour"),
                    "epsEstimate": it.get("epsEstimate"),
                    "revenueEstimate": it.get("revenueEstimate"),
                } for it in arr]
    except Exception:
        pass
    return res
