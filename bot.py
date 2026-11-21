import os
import requests

token = os.environ["TELEGRAM_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

r = requests.get(
    "https://api.binance.com/api/v3/ticker/price",
    params={"symbol": "ETHUSDT"},
    timeout=15,
)
price = r.json()["price"]

msg = f"تجربة ناجحة ✅\nسعر ETHUSDT الحالي: {price}"
requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data={"chat_id": chat_id, "text": msg},
    timeout=15,
)
