from fastapi import FastAPI
import requests
import os
import csv
import io
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
GOOGLE_NEWS_API_KEY = os.getenv("GOOGLE_NEWS_API_KEY")
ETF_SOURCE = os.getenv("ETF_SOURCE", "etfdb_free")
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
    从 Treasury.gov 抓取每日收益率曲线，并解析为 JSON
    """
    if TREASURY_API == "public":
        url = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-yield-curve-rates.csv"
        resp = requests.get(url).text

        # 解析 CSV
        reader = csv.DictReader(io.StringIO(resp))
        data = list(reader)

        return {
            "source": "treasury.gov",
            "count": len(data),
            "latest": data[-1] if data else None,  # 最近一行
            "data": data[:30]  # 返回最近30行
        }
    else:
        return {"error": f"Treasury API mode {TREASURY_API} not implemented"}

# ============== ETF Source ==============
@app.get("/etfdb")
def etf_data(ticker: str):
    """
    从 etfdb.com 抓取 ETF 页面，解析基金规模、持仓 Top10
    """
    if ETF_SOURCE == "etfdb_free":
        url = f"https://etfdb.com/etf/{ticker}/"
        html = requests.get(url).text
        soup = BeautifulSoup(html, "html.parser")

        result = {"source": "etfdb", "ticker": ticker}

        # 基金规模
        try:
            asset_tag = soup.find("div", text="Assets Under Management").find_next("div")
            result["assets"] = asset_tag.text.strip()
        except:
            result["assets"] = None

        # Top 10 持仓
        try:
            holdings_table = soup.find("table", {"class": "table-etf-holdings"})
            holdings = []
            if holdings_table:
                rows = holdings_table.find_all("tr")[1:11]
                for r in rows:
                    cols = [c.get_text(strip=True) for c in r.find_all("td")]
                    if cols:
                        holdings.append({"name": cols[0], "weight": cols[-1]})
            result["top_holdings"] = holdings
        except:
            result["top_holdings"] = []

        return result
    else:
        return {"error": f"ETF source mode {ETF_SOURCE} not implemented"}

# ============== NewsAPI ==============
@app.get("/newsapi")
def get_news(query: str):
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}"
    return requests.get(url).json()

# ============== Google News ==============
@app.get("/google-news")
def google_news(query: str):
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={GOOGLE_NEWS_API_KEY}"
    return requests.get(url).json()
