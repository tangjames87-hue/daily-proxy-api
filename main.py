from fastapi import FastAPI
import requests
import os

app = FastAPI()

# ============== 环境变量读取 ==============
BASE_URL = "https://daily-proxy-api.onrender.com"

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
FRED_API_KEY = os.getenv("FRED_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")

# ============== 健康检查 ==============
@app.get("/")
def root():
    return {"status": "ok", "message": "Daily Proxy API is running!"}

@app.get("/healthcheck")
def healthcheck():
    return {"status": "running"}

# ============== 聚合接口 ==============
@app.get("/analyze")
def analyze(ticker: str = "AAPL"):
    result = {"ticker": ticker}

    try:
        price = requests.get(f"{BASE_URL}/price?ticker={ticker}", timeout=15).json()
        result["price"] = price
    except Exception as e:
        result["price_error"] = str(e)

    try:
        company = requests.get(f"{BASE_URL}/company?ticker={ticker}", timeout=15).json()
        result["company"] = company
    except Exception as e:
        result["company_error"] = str(e)

    try:
        news = requests.get(f"{BASE_URL}/finnhub-news?ticker={ticker}", timeout=20).json()
        result["news"] = news[:5] if isinstance(news, list) else news
    except Exception as e:
        result["news_error"] = str(e)

    try:
        macro = requests.get(f"{BASE_URL}/fred/series?id=CPIAUCSL", timeout=20).json()
        result["macro"] = macro
    except Exception as e:
        result["macro_error"] = str(e)

    try:
        treasury = requests.get(f"{BASE_URL}/treasury/yield", timeout=20).json()
        result["treasury"] = treasury
    except Exception as e:
        result["treasury_error"] = str(e)

    return result
