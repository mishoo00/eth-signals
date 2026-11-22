import os
import requests

token = os.environ["TELEGRAM_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

r = requests.get(
    "https://data-api.binance.vision/api/v3/klines",
    params={"symbol": "ETHUSDT", "interval": "5m", "limit": 200},
    timeout=15,
)
candles = r.json()
closes = [float(c[4]) for c in candles]


def ema(values, n):
    k = 2 / (n + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values, n=14):
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


msg = (
    "اختبار المؤشرات ✅\n"
    f"عدد الشموع: {len(closes)}\n"
    f"آخر إغلاق: {closes[-1]:.2f}\n"
    f"EMA20: {ema(closes, 20):.2f}\n"
    f"EMA50: {ema(closes, 50):.2f}\n"
    f"RSI14: {rsi(closes):.1f}"
)

requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data={"chat_id": chat_id, "text": msg},
    timeout=15,
)
