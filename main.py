from fastapi import FastAPI
import requests
import os
import yfinance as yf
from bs4 import BeautifulSoup

app = FastAPI()

# ============== 环境变量读取 ==============
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
FRED_API_KEY = os.getenv("FRED_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")
TREASURY_API = os.getenv("TREASURY_API", "FRED")  # 默认用 FRED

DEFAULT_HEADERS = {
    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

# ============== 根路径健康检查 ==============
@app.get("/")
def root():
    return {"status": "ok", "message": "Daily Proxy API is running!"}

# ============== Finnhub ==============
@app.get("/price")
def get_price(ticker: str = "MSFT"):
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}"
    return requests.get(url, timeout=15).json()

@app.get("/company")
def get_company(ticker: str = "MSFT"):
    url = f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={FINNHUB_API_KEY}"
    return requests.get(url, timeout=15).json()

@app.get("/finnhub-news")
def get_company_news(ticker: str = "TSLA", _from: str = "2025-09-01", to: str = "2025-10-02"):
    url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={_from}&to={to}&token={FINNHUB_API_KEY}"
    return requests.get(url, timeout=20).json()

# ============== Alpaca ==============
@app.get("/account")
def get_account():
    url = f"{ALPACA_BASE_URL}/v2/account"
    headers = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}
    return requests.get(url, headers=headers, timeout=15).json()

@app.get("/positions")
def get_positions():
    url = f"{ALPACA_BASE_URL}/v2/positions"
    headers = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}
    return requests.get(url, headers=headers, timeout=15).json()

@app.get("/orders")
def get_orders():
    url = f"{ALPACA_BASE_URL}/v2/orders"
    headers = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}
    return requests.get(url, headers=headers, timeout=15).json()

# ============== Polygon ==============
@app.get("/poly/price")
def poly_price(ticker: str = "NVDA"):
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev?apiKey={POLYGON_API_KEY}"
    return requests.get(url, timeout=15).json()

@app.get("/poly/options")
def poly_options(ticker: str = "QQQ"):
    url = f"https://api.polygon.io/v3/reference/options/contracts?underlying_ticker={ticker}&apiKey={POLYGON_API_KEY}"
    return requests.get(url, timeout=20).json()

# ============== FRED ==============
@app.get("/fred/series")
def fred_series(id: str = "CPIAUCSL"):
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={id}&api_key={FRED_API_KEY}&file_type=json"
    return requests.get(url, timeout=20).json()

# ============== Treasury (FRED 国债收益率) ==============
@app.get("/treasury/yield")
def treasury_yield():
    # 使用 FRED 的 DGS2/DGS10/DGS30 系列
    tickers = {"2Y": "DGS2", "10Y": "DGS10", "30Y": "DGS30"}
    result = {}
    for k, v in tickers.items():
        url = (f"https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={v}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1")
        data = requests.get(url, timeout=15).json()
        if "observations" in data and data["observations"]:
            result[k] = data["observations"][0]
    return {"source": "FRED", "yields": result}

# ============== ETF (Yahoo 基本信息 + FMP v4/ETFdb/yfinance(持仓)) ==============
def _get_etf_holdings_from_fmp(ticker: str):
    """优先尝试 FMP v4 两种形式，并支持分页参数。"""
    holdings = []

    # 形式1：query 参数形式（建议）
    try:
        url = (f"https://financialmodelingprep.com/api/v4/etf-holdings"
               f"?symbol={ticker}&page=1&size=100&apikey={FMP_API_KEY}")
        resp = requests.get(url, timeout=20).json()
        if isinstance(resp, list) and resp:
            for h in resp:
                holdings.append({
                    "symbol": h.get("asset"),
                    "name": h.get("name"),
                    "weight": h.get("weightPercentage")
                })
            if holdings:
                return holdings
    except Exception:
        pass

    # 形式2：路径参数形式（兼容某些账户）
    try:
        url2 = f"https://financialmodelingprep.com/api/v4/etf-holdings/{ticker}?apikey={FMP_API_KEY}"
        resp2 = requests.get(url2, timeout=20).json()
        if isinstance(resp2, list) and resp2:
            for h in resp2:
                holdings.append({
                    "symbol": h.get("asset"),
                    "name": h.get("name"),
                    "weight": h.get("weightPercentage")
                })
    except Exception:
        pass

    return holdings

def _get_etf_holdings_from_etfdb(ticker: str):
    """ETFdb 网页解析 Top10（尽量容错）。"""
    holdings = []
    try:
        url = f"https://etfdb.com/etf/{ticker}/#holdings"
        html = requests.get(url, headers=DEFAULT_HEADERS, timeout=20).text
        soup = BeautifulSoup(html, "lxml")

        # 常见：id="etf-holdings" 的表
        table = soup.find("table", {"id": "etf-holdings"})
        if not table:
            # 备选：寻找包含“Holdings”的表格（容错）
            for t in soup.find_all("table"):
                cap = (t.find("caption").get_text(strip=True).lower() if t.find("caption") else "")
                if "holding" in cap:
                    table = t
                    break

        if table:
            rows = table.find_all("tr")
            for row in rows[1:]:  # 跳过表头
                cols = [c.get_text(strip=True) for c in row.find_all("td")]
                # 常见列：Symbol | Name | % Assets 或 Weight
                if len(cols) >= 3:
                    sym = cols[0]
                    name = cols[1]
                    weight = cols[2]
                    # 只要像 6.71% 这样的就通过
                    holdings.append({"symbol": sym, "name": name, "weight": weight})
                if len(holdings) >= 10:
                    break
    except Exception:
        pass
    return holdings

def _get_etf_holdings_from_yfinance(ticker: str):
    """yfinance 的少量 ETF 可能返回 holdings（不稳定）。"""
    try:
        etf = yf.Ticker(ticker)
        if hasattr(etf, "holdings") and etf.holdings is not None:
            df = etf.holdings
            if df is not None and not df.empty:
                out = []
                for _, r in df.head(10).iterrows():
                    out.append({
                        "symbol": r.get("symbol") or r.get("Symbol"),
                        "name": r.get("holdingName") or r.get("name"),
                        "weight": r.get("holdingPercent") or r.get("weight")
                    })
                return out
    except Exception:
        pass
    return []

@app.get("/etf")
def etf_info(ticker: str = "SPY"):
    result = {"ticker": ticker, "source": "Yahoo+Multi"}

    # --- 基本信息（Yahoo Finance） ---
    try:
        etf = yf.Ticker(ticker)
        info = etf.info or {}
        result.update({
            "category": info.get("category"),
            "family": info.get("fundFamily") or info.get("family"),
            "styleBox": info.get("styleBox")
        })
    except Exception as e:
        result["yahoo_error"] = str(e)

    # --- 持仓：FMP v4 → ETFdb → yfinance ---
    holdings = _get_etf_holdings_from_fmp(ticker)
    if not holdings:
        holdings = _get_etf_holdings_from_etfdb(ticker)
    if not holdings:
        holdings = _get_etf_holdings_from_yfinance(ticker)

    result["top_holdings"] = holdings[:10] if holdings else []
    if not result["top_holdings"]:
        result["holdings_note"] = "No holdings found via FMP/ETFdb/yfinance"
    return result

# ============== NewsAPI ==============
@app.get("/newsapi")
def get_news(query: str = "Apple"):
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}"
    return requests.get(url, timeout=20).json()
