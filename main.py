from fastapi import FastAPI
import requests
import os
import csv
import io

app = FastAPI()

# ============== 环境变量读取 ==============
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
FRED_API_KEY = os.getenv("FRED_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
ETF_SOURCE = os.getenv("ETF_SOURCE", "yahoo_finance")
TREASURY_API = os.getenv("TREASURY_API", "public")

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

# ============== Treasury ==============
@app.get("/treasury/yield")
def treasury_yield():
    """
    从 Treasury.gov 官方 CSV API 获取每日收益率曲线，转换为 JSON
    """
    if TREASURY_API == "public":
        url = "https://home.treasury.gov/sites/default/files/interest-rates/yield.csv"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True).text

        reader = csv.DictReader(io.StringIO(resp))
        data = list(reader)

        return {
            "source": "treasury.gov",
            "count": len(data),
            "latest": data[-1] if data else None,
            "data": data[-30:] if data else []
        }
    else:
        return {"error": f"Treasury API mode {TREASURY_API} not implemented"}

# ============== ETF (Yahoo Finance) ==============
@app.get("/etf")
def etf_data(ticker: str):
    """
    从 Yahoo Finance 获取 ETF 信息 (基金规模 + Top Holdings)
    """
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=topHoldings,fundProfile"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    data = resp.json()

    result = {"source": "yahoo_finance", "ticker": ticker}

    try:
        fund_profile = data["quoteSummary"]["result"][0]["fundProfile"]
        result["category"] = fund_profile.get("category", None)
        result["family"] = fund_profile.get("family", None)
        result["styleBox"] = fund_profile.get("styleBoxUrl", None)
    except:
        result["category"] = None
        result["family"] = None
        result["styleBox"] = None

    try:
        holdings = data["quoteSummary"]["result"][0]["topHoldings"]["holdings"]
        top10 = [
            {
                "name": h.get("holdingName"),
                "symbol": h.get("symbol"),
                "weight": h.get("holdingPercent")
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
