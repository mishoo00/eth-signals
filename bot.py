import os
import requests

token = os.environ["TELEGRAM_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]
manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

r = requests.get(
    "https://data-api.binance.vision/api/v3/klines",
    params={"symbol": "ETHUSDT", "interval": "5m", "limit": 200},
    timeout=15,
)
candles = r.json()[:-1]  # نتجاهل الشمعة غير المغلقة
highs = [float(c[2]) for c in candles]
lows = [float(c[3]) for c in candles]
closes = [float(c[4]) for c in candles]


def ema_series(values, n):
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


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


def atr(n=14):
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


e20 = ema_series(closes, 20)
e50 = ema_series(closes, 50)
r14 = rsi(closes)
a14 = atr()
price = closes[-1]

side = None
reasons = []
if (e20[-1] > e50[-1] and e50[-1] > e50[-10]
        and closes[-2] < e20[-2] and price > e20[-1] and 50 <= r14 <= 70):
    side = "شراء 🟢"
    reasons = ["اتجاه صاعد (EMA20 فوق EMA50)", "ارتداد وإغلاق فوق EMA20", f"RSI={r14:.1f}"]
    sl = price - 1.5 * a14
    tp = price + 3.75 * a14
elif (e20[-1] < e50[-1] and e50[-1] < e50[-10]
        and closes[-2] > e20[-2] and price < e20[-1] and 30 <= r14 <= 50):
    side = "بيع 🔴"
    reasons = ["اتجاه هابط (EMA20 تحت EMA50)", "ارتداد وإغلاق تحت EMA20", f"RSI={r14:.1f}"]
    sl = price + 1.5 * a14
    tp = price - 3.75 * a14

if side:
    gap = abs(e20[-1] - e50[-1]) / a14
    strength = "قوية" if gap > 0.7 else "متوسطة" if gap > 0.3 else "ضعيفة"
    msg = (
        f"إشارة {side} ETHUSDT (5m)\n"
        f"الدخول: {price:.2f}\n"
        f"وقف الخسارة: {sl:.2f}\n"
        f"جني الأرباح: {tp:.2f}\n"
        f"العائد/المخاطرة: 2.5\n"
        f"القوة: {strength}\n"
        "الأسباب: " + " | ".join(reasons) + "\n"
        "⚠️ إشارة تجريبية وليست ضمان ربح."
    )
elif manual:
    trend = "صاعد" if e20[-1] > e50[-1] else "هابط"
    msg = (
        "لا توجد إشارة الآن.\n"
        f"السعر: {price:.2f} | الاتجاه: {trend}\n"
        f"EMA20: {e20[-1]:.2f} | EMA50: {e50[-1]:.2f}\n"
        f"RSI14: {r14:.1f} | ATR14: {a14:.2f}"
    )
else:
    msg = None

if msg:
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": msg},
        timeout=15,
    )
