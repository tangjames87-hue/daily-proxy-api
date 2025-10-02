from fastapi import FastAPI
import requests
import os
import yfinance as yf

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

# ============== 根路径健康检查 ==============
@app.get("/")
def root():
    return {"status": "ok", "message": "Daily Proxy API is running!"}

# ============== Finnhub ==============
@app.get("/price")
def get_price(ticker: str = "MSFT"):
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}"
    return requests.get(url).json()

@app.get("/company")
def get_company(ticker: str = "MSFT"):
    url = f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={FINNHUB_API_KEY}"
    return requests.get(url).json()

@app.get("/finnhub-news")
def get_company_news(ticker: str = "TSLA", _from: str = "2025-09-01", to: str = "2025-10-02"):
    url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={_from}&to={to}&token={FINNHUB_API_KEY}"
    return requests.get(url).json()

# ============== Alpaca ==============
@app.get("/account")
def get_account():
    url = f"{ALPACA_BASE_URL}/v2/account"
    headers = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}
    return requests.get(url, headers=headers).json()

@app.get("/positions")
def get_positions():
    url = f"{ALPACA_BASE_URL}/v2/positions"
    headers = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}
    return requests.get(url, headers=headers).json()

@app.get("/orders")
def get_orders():
    url = f"{ALPACA_BASE_URL}/v2/orders"
    headers = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}
    return requests.get(url, headers=headers).json()

# ============== Polygon ==============
@app.get("/poly/price")
def poly_price(ticker: str = "NVDA"):
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev?apiKey={POLYGON_API_KEY}"
    return requests.get(url).json()

@app.get("/poly/options")
def poly_options(ticker: str = "QQQ"):
    url = f"https://api.polygon.io/v3/reference/options/contracts?underlying_ticker={ticker}&apiKey={POLYGON_API_KEY}"
    return requests.get(url).json()

# ============== FRED ==============
@app.get("/fred/series")
def fred_series(id: str = "CPIAUCSL"):
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={id}&api_key={FRED_API_KEY}&file_type=json"
    return requests.get(url).json()

# ============== Treasury (FRED 国债收益率) ==============
@app.get("/treasury/yield")
def treasury_yield():
    tickers = {"2Y": "DGS2", "10Y": "DGS10", "30Y": "DGS30"}
    result = {}
    for k, v in tickers.items():
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id={v}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        data = requests.get(url).json()
        if "observations" in data and data["observations"]:
            result[k] = data["observations"][0]
    return {"source": "FRED", "yields": result}

# ============== ETF (Yahoo 基本信息 + FMP v4 持仓) ==============
@app.get("/etf")
def etf_info(ticker: str = "SPY"):
    result = {"ticker": ticker, "source": "Yahoo+FMP"}

    # --- 基本信息（Yahoo Finance） ---
    try:
        etf = yf.Ticker(ticker)
        info = etf.info
        result.update({
            "category": info.get("category"),
            "family": info.get("fundFamily"),
            "styleBox": info.get("styleBox")
        })
    except Exception as e:
        result["yahoo_error"] = str(e)

    # --- 持仓数据（FMP v4） ---
    try:
        url = f"https://financialmodelingprep.com/api/v4/etf-holdings/{ticker}?apikey={FMP_API_KEY}"
        resp = requests.get(url).json()
        holdings = []
        if isinstance(resp, list) and resp:
            for h in resp[:10]:  # Top 10
                holdings.append({
                    "symbol": h.get("asset"),
                    "name": h.get("name"),
                    "weight": h.get("weightPercentage")
                })
        result["top_holdings"] = holdings
    except Exception as e:
        result["fmp_error"] = str(e)

    return result

# ============== NewsAPI ==============
@app.get("/newsapi")
def get_news(query: str = "Apple"):
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}"
    return requests.get(url).json()
