from fastapi import FastAPI
import requests
import os

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

# ============== 根路径健康检查 ==============
@app.get("/")
def root():
    return {"status": "ok", "message": "Daily Proxy API is running!"}

# ============== Finnhub ==============
@app.get("/price")
def get_price(ticker: str):
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}"
    return requests.get(url).json()

@app.get("/company")
def get_company(ticker: str):
    url = f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={FINNHUB_API_KEY}"
    return requests.get(url).json()

@app.get("/finnhub-news")
def get_company_news(ticker: str, _from: str = "2025-09-01", to: str = "2025-10-02"):
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
def poly_price(ticker: str):
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev?apiKey={POLYGON_API_KEY}"
    return requests.get(url).json()

@app.get("/poly/options")
def poly_options(ticker: str):
    url = f"https://api.polygon.io/v3/reference/options/contracts?underlying_ticker={ticker}&apiKey={POLYGON_API_KEY}"
    return requests.get(url).json()

# ============== FRED ==============
@app.get("/fred/series")
def fred_series(id: str):
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={id}&api_key={FRED_API_KEY}&file_type=json"
    return requests.get(url).json()

# ============== Treasury (用 FRED 数据) ==============
@app.get("/treasury/yield")
def treasury_yield():
    """
    从 FRED API 获取国债收益率 (2Y, 10Y, 30Y)，返回最近30天
    """
    series = {"2Y": "DGS2", "10Y": "DGS10", "30Y": "DGS30"}
    results = {}

    for label, sid in series.items():
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}&api_key={FRED_API_KEY}&file_type=json"
        resp = requests.get(url).json()
        obs = resp.get("observations", [])
        latest30 = obs[-30:] if len(obs) > 30 else obs
        results[label] = latest30

    return {"source": "FRED", "yields": results}

# ============== ETF (FMP API) ==============
@app.get("/etf")
def etf_data(ticker: str):
    """
    从 FMP 获取 ETF 持仓 (Top10)
    """
    url = f"https://financialmodelingprep.com/api/v3/etf-holdings/{ticker}?apikey={FMP_API_KEY}"
    resp = requests.get(url)
    data = resp.json()

    result = {"source": "FMP", "ticker": ticker}

    try:
        holdings = data.get("holdings", [])
        top10 = [
            {
                "name": h.get("asset", None),
                "symbol": h.get("symbol", None),
                "weight": h.get("weightPercentage", None)
            }
            for h in holdings[:10]
        ]
        result["top_holdings"] = top10
    except:
        result["top_holdings"] = []

    return result

# ============== NewsAPI ==============
@app.get("/newsapi")
def get_news(query: str):
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}"
    return requests.get(url).json()
