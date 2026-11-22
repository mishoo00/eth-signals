import os
import requests

token = os.environ["TELEGRAM_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

sources = {
    "Binance": ("https://api.binance.com/api/v3/ticker/price", {"symbol": "ETHUSDT"}),
    "BinanceVision": ("https://data-api.binance.vision/api/v3/ticker/price", {"symbol": "ETHUSDT"}),
    "Bybit": ("https://api.bybit.com/v5/market/tickers", {"category": "spot", "symbol": "ETHUSDT"}),
    "OKX": ("https://www.okx.com/api/v5/market/ticker", {"instId": "ETH-USDT"}),
    "Coinbase": ("https://api.coinbase.com/v2/prices/ETH-USD/spot", {}),
    "Kraken": ("https://api.kraken.com/0/public/Ticker", {"pair": "ETHUSD"}),
}

lines = []
for name, (url, params) in sources.items():
    try:
        r = requests.get(url, params=params, timeout=15)
        lines.append(f"{name}: {r.status_code}")
    except Exception:
        lines.append(f"{name}: failed")

msg = "نتيجة فحص المصادر:\n" + "\n".join(lines)
requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data={"chat_id": chat_id, "text": msg},
    timeout=15,
)
