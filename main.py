from fastapi import FastAPI
import requests
import os

app = FastAPI()

# ============== 环境变量读取 ==============
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

    # Finnhub - 股票价格
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}"
        result["price"] = requests.get(url, timeout=15).json()
    except Exception as e:
        result["price_error"] = str(e)

    # Finnhub - 公司信息
    try:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={FINNHUB_API_KEY}"
        result["company"] = requests.get(url, timeout=15).json()
    except Exception as e:
        result["company_error"] = str(e)

    # Finnhub - 公司新闻
    try:
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from=2025-09-01&to=2025-10-02&token={FINNHUB_API_KEY}"
        result["news"] = requests.get(url, timeout=20).json()
    except Exception as e:
        result["news_error"] = str(e)

    # FRED - 宏观数据 (CPI)
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={FRED_API_KEY}&file_type=json"
        result["macro"] = requests.get(url, timeout=20).json()
    except Exception as e:
        result["macro_error"] = str(e)

    # FRED - 国债收益率
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={FRED_API_KEY}&file_type=json"
        result["treasury"] = requests.get(url, timeout=20).json()
    except Exception as e:
        result["treasury_error"] = str(e)

    return result
