from fastapi import FastAPI, Query
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

BASE_URL = "https://daily-proxy-api.onrender.com"

# ============== 根路径 & 健康检查 ==============
@app.get("/")
def root():
    return {"status": "ok", "message": "Daily Proxy API is running!"}

@app.get("/healthcheck")
def healthcheck():
    return {"status": "running"}

# ============== 聚合接口 /analyze ==============
@app.get("/analyze")
def analyze(ticker: str = "AAPL", etf: str = "SPY"):
    result = {"ticker": ticker}

    # --- 股票行情 ---
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}"
        result["price"] = requests.get(url, timeout=15).json()
    except Exception as e:
        result["price_error"] = str(e)

    # --- 公司信息 ---
    try:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={FINNHUB_API_KEY}"
        result["company"] = requests.get(url, timeout=15).json()
    except Exception as e:
        result["company_error"] = str(e)

    # --- 公司新闻 ---
    try:
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from=2025-09-01&to=2025-10-02&token={FINNHUB_API_KEY}"
        result["news"] = requests.get(url, timeout=20).json()
    except Exception as e:
        result["news_error"] = str(e)

    # --- 宏观数据 (CPI) ---
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={FRED_API_KEY}&file_type=json"
        result["macro"] = requests.get(url, timeout=20).json()
    except Exception as e:
        result["macro_error"] = str(e)

    # --- 国债收益率 ---
    try:
        tickers = {"2Y": "DGS2", "10Y": "DGS10", "30Y": "DGS30"}
        yields = {}
        for k, v in tickers.items():
            url = f"https://api.stlouisfed.org/fred/series/observations?series_id={v}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
            data = requests.get(url, timeout=15).json()
            if "observations" in data and data["observations"]:
                yields[k] = data["observations"][0]
        result["treasury"] = yields
    except Exception as e:
        result["treasury_error"] = str(e)

    # --- ETF 持仓 ---
    try:
        url = f"https://financialmodelingprep.com/api/v4/etf-holdings/{etf}?apikey={FMP_API_KEY}"
        result["etf"] = requests.get(url, timeout=20).json()
    except Exception as e:
        result["etf_error"] = str(e)

    # --- Alpaca 模拟账户 ---
    try:
        headers = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}
        account = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=headers, timeout=15).json()
        positions = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=headers, timeout=15).json()
        orders = requests.get(f"{ALPACA_BASE_URL}/v2/orders", headers=headers, timeout=15).json()
        result["account"] = account
        result["positions"] = positions
        result["orders"] = orders
    except Exception as e:
        result["alpaca_error"] = str(e)

    return result


# ============== 中间层接口 /proxy ==============
@app.get("/proxy")
def proxy(symbol: str = Query(..., description="股票代码"), etf: str = "SPY"):
    """
    GPT 只需要调用 /proxy?symbol=XXX 即可，
    由本服务内部去调用 /analyze，返回 JSON。
    """
    try:
        url = f"{BASE_URL}/analyze?ticker={symbol}&etf={etf}"
        resp = requests.get(url, timeout=30)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}
