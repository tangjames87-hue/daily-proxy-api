import requests

BASE_URL = "https://daily-proxy-api.onrender.com"  # 替换成你的 Render 域名

# 定义要测试的接口
endpoints = [
    ("/", None, "健康检查"),
    ("/price", {"ticker": "AAPL"}, "Finnhub 股价"),
    ("/company", {"ticker": "MSFT"}, "Finnhub 公司信息"),
    ("/finnhub-news", {"ticker": "TSLA", "_from": "2025-09-01", "to": "2025-10-01"}, "Finnhub 新闻"),
    ("/account", None, "Alpaca 账户"),
    ("/positions", None, "Alpaca 持仓"),
    ("/orders", None, "Alpaca 订单"),
    ("/poly/price", {"ticker": "NVDA"}, "Polygon 前日价格"),
    ("/poly/options", {"ticker": "QQQ"}, "Polygon 期权合约"),
    ("/fred/series", {"id": "CPIAUCSL"}, "FRED 宏观数据"),
    ("/treasury/yield", None, "Treasury 国债收益率 (FRED)"),
    ("/etf", {"ticker": "SPY"}, "ETF 基金信息 (FMP)"),
    ("/newsapi", {"query": "Apple"}, "NewsAPI 新闻"),
]

success_count = 0
fail_count = 0

def test_endpoint(path, params=None, desc=""):
    global success_count, fail_count
    url = f"{BASE_URL}{path}"
    print(f"\n🔹 {desc} → {url}")
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            try:
                data = resp.json()

                # 特殊检查 Treasury
                if path == "/treasury/yield":
                    if "yields" in data and all(k in data["yields"] for k in ["2Y", "10Y", "30Y"]):
                        print("✅ 成功 | Treasury 返回了 2Y/10Y/30Y 收益率")
                        success_count += 1
                        return
                    else:
                        print("❌ Treasury 返回格式异常")
                        fail_count += 1
                        return

                # 特殊检查 ETF (FMP)
                if path == "/etf":
                    top_holdings = data.get("top_holdings", [])
                    if len(top_holdings) > 0:
                        preview = top_holdings[:3]
                        print(f"✅ 成功 | ETF 返回 {len(top_holdings)} 个持仓, 前3个: {preview}")
                        success_count += 1
                        return
                    else:
                        print("❌ ETF 未返回持仓数据")
                        fail_count += 1
                        return

                # 通用检查
                if isinstance(data, dict):
                    preview = {k: data[k] for k in list(data.keys())[:5]}
                elif isinstance(data, list) and len(data) > 0:
                    preview = data[0]
                else:
                    preview = data
                print(f"✅ 成功 | 预览: {str(preview)[:300]}")
                success_count += 1
            except Exception:
                print(f"❌ 错误 | 返回非 JSON: {resp.text[:200]}")
                fail_count += 1
        else:
            print(f"❌ 错误 | 状态码 {resp.status_code} | 内容: {resp.text[:200]}")
            fail_count += 1
    except Exception as e:
        print(f"⚠️ 异常: {e}")
        fail_count += 1

if __name__ == "__main__":
    print("🚀 开始测试 Daily Proxy API 全部接口...\n")
    for ep in endpoints:
        test_endpoint(ep[0], ep[1], ep[2])
    print("\n📊 测试完成！")
    total = success_count + fail_count
    percent = round(success_count / total * 100, 2) if total > 0 else 0
    print(f"✅ 成功: {success_count} 个 | ❌ 失败: {fail_count} 个 | 总计: {total} 个接口 | 通过率: {percent}%")
