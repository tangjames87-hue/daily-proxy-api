from fastapi import FastAPI
import requests
import os
import yfinance as yf
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

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

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

# ============== 根路径健康检查 ==============
@app.get("/")
def root():
    return {"status": "ok", "message": "Daily Proxy API is running!"}

# ============== 数据源健康检查接口 ==============
@app.get("/healthcheck")
def healthcheck():
    results = {}

    # Finnhub
    try:
        r = requests.get(f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={FINNHUB_API_KEY}", timeout=10)
        results["finnhub"] = "ok" if r.status_code == 200 and "c" in r.json() else "error"
    except Exception as e:
        results["finnhub"] = f"error: {str(e)}"

    # Alpaca
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/account",
                         headers={"APCA-API-KEY-ID": ALPACA_API_KEY,
                                  "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}, timeout=10)
        results["alpaca"] = "ok" if r.status_code == 200 and "account_number" in r.text else "error"
    except Exception as e:
        results["alpaca"] = f"error: {str(e)}"

    # Polygon
    try:
        r = requests.get(f"https://api.polygon.io/v2/aggs/ticker/AAPL/prev?apiKey={POLYGON_API_KEY}", timeout=10)
        results["polygon"] = "ok" if r.status_code == 200 else "error"
    except Exception as e:
        results["polygon"] = f"error: {str(e)}"

    # FRED
    try:
        r = requests.get(f"https://api.stlouisfed.org/fred/series/observations"
                         f"?series_id=DGS10&api_key={FRED_API_KEY}&file_type=json", timeout=10)
        results["fred"] = "ok" if r.status_code == 200 and "observations" in r.text else "error"
    except Exception as e:
        results["fred"] = f"error: {str(e)}"

    # NewsAPI
    try:
        r = requests.get(f"https://newsapi.org/v2/everything?q=Apple&apiKey={NEWS_API_KEY}", timeout=10)
        results["newsapi"] = "ok" if r.status_code == 200 and "articles" in r.text else "error"
    except Exception as e:
        results["newsapi"] = f"error: {str(e)}"

    return {"status": "running", "sources": results}

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
    tickers = {"2Y": "DGS2", "10Y": "DGS10", "30Y": "DGS30"}
    result = {}
    for k, v in tickers.items():
        url = (f"https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={v}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1")
        data = requests.get(url, timeout=15).json()
        if "observations" in data and data["observations"]:
            result[k] = data["observations"][0]
    return {"source": "FRED", "yields": result}

# ============== ETF (Yahoo + FMP + ETFdb) ==============
def _get_etf_holdings_from_fmp(ticker: str):
    holdings = []
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
    return holdings

@app.get("/etf")
def etf_info(ticker: str = "SPY"):
    result = {"ticker": ticker, "source": "Yahoo+Multi"}
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
    holdings = _get_etf_holdings_from_fmp(ticker)
    result["top_holdings"] = holdings[:10] if holdings else []
    return result

# ============== NewsAPI ==============
@app.get("/newsapi")
def get_news(query: str = "Apple"):
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}"
    return requests.get(url, timeout=20).json()
