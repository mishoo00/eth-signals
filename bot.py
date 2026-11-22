import os
import json
import requests

token = os.environ["TELEGRAM_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]
manual = os.environ.get("MODE") == "manual"

FILE = "signals.json"
FEE = 0.0008  # رسوم الدخول والخروج تقريبًا
MAX_CANDLES = 144  # 12 ساعة، ثم تُقفل الصفقة بسعر الإغلاق


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=15,
    )


try:
    with open(FILE) as f:
        signals = json.load(f)
except FileNotFoundError:
    signals = []

r = requests.get(
    "https://data-api.binance.vision/api/v3/klines",
    params={"symbol": "ETHUSDT", "interval": "5m", "limit": 200},
    timeout=15,
)
raw = r.json()[:-1]  # نتجاهل الشمعة غير المغلقة
candles = [(int(c[0]), float(c[2]), float(c[3]), float(c[4])) for c in raw]
highs = [c[1] for c in candles]
lows = [c[2] for c in candles]
closes = [c[3] for c in candles]


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


def stats():
    done = [s for s in signals if s["status"] != "open"]
    wins = [s for s in done if s["r"] > 0]
    total = sum(s["r"] for s in done)
    open_n = len(signals) - len(done)
    rate = 100 * len(wins) / len(done) if done else 0
    return (
        "📊 السجل\n"
        f"مغلقة: {len(done)} | رابحة: {len(wins)} | نسبة النجاح: {rate:.0f}%\n"
        f"صافي النتيجة: {total:+.2f}R (بعد الرسوم)\n"
        f"مفتوحة الآن: {open_n}"
    )


out = []
resolved = False

# 1) فحص الإشارات المفتوحة
for s in signals:
    if s["status"] != "open":
        continue
    risk = abs(s["entry"] - s["sl"])
    n = 0
    res = None
    for t, h, l, c in candles:
        if t <= s["id"]:
            continue
        n += 1
        if s["side"] == "buy":
            hit_sl = l <= s["sl"]
            hit_tp = h >= s["tp"]
        else:
            hit_sl = h >= s["sl"]
            hit_tp = l <= s["tp"]
        if hit_sl:  # لو الاثنان في نفس الشمعة نعتبرها خسارة (تحفظًا)
            res, exit_p = "sl", s["sl"]
        elif hit_tp:
            res, exit_p = "tp", s["tp"]
        elif n >= MAX_CANDLES:
            res, exit_p = "expired", c
        if res:
            break
    if not res:
        continue
    move = exit_p - s["entry"] if s["side"] == "buy" else s["entry"] - exit_p
    net = move / risk - FEE * s["entry"] / risk
    s["status"] = res
    s["exit"] = round(exit_p, 2)
    s["r"] = round(net, 2)
    resolved = True
    label = {"tp": "وصلت الهدف ✅", "sl": "ضربت الوقف ❌", "expired": "انتهت مدتها ⏱"}[res]
    out.append(f"إشارة {s['side']} بسعر {s['entry']} {label}\nالنتيجة: {net:+.2f}R")

# 2) فحص إشارة جديدة
e20 = ema_series(closes, 20)
e50 = ema_series(closes, 50)
r14 = rsi(closes)
a14 = atr()
price = closes[-1]
candle_id = candles[-1][0]
has_open = any(s["status"] == "open" for s in signals)
already = any(s["id"] == candle_id for s in signals)

side = None
if (e20[-1] > e50[-1] and e50[-1] > e50[-10]
        and closes[-2] < e20[-2] and price > e20[-1] and 50 <= r14 <= 70):
    side = "buy"
    sl = price - 1.5 * a14
    tp = price + 3.75 * a14
    reasons = ["اتجاه صاعد (EMA20 فوق EMA50)", "ارتداد وإغلاق فوق EMA20", f"RSI={r14:.1f}"]
elif (e20[-1] < e50[-1] and e50[-1] < e50[-10]
        and closes[-2] > e20[-2] and price < e20[-1] and 30 <= r14 <= 50):
    side = "sell"
    sl = price + 1.5 * a14
    tp = price - 3.75 * a14
    reasons = ["اتجاه هابط (EMA20 تحت EMA50)", "ارتداد وإغلاق تحت EMA20", f"RSI={r14:.1f}"]

new_signal = False
if side and not has_open and not already:
    gap = abs(e20[-1] - e50[-1]) / a14
    strength = "قوية" if gap > 0.7 else "متوسطة" if gap > 0.3 else "ضعيفة"
    signals.append({
        "id": candle_id,
        "side": side,
        "entry": round(price, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "status": "open",
    })
    new_signal = True
    title = "شراء 🟢" if side == "buy" else "بيع 🔴"
    out.append(
        f"إشارة {title} ETHUSDT (5m)\n"
        f"الدخول: {price:.2f}\n"
        f"وقف الخسارة: {sl:.2f}\n"
        f"جني الأرباح: {tp:.2f}\n"
        f"العائد/المخاطرة: 2.5\n"
        f"القوة: {strength}\n"
        "الأسباب: " + " | ".join(reasons) + "\n"
        "⚠️ إشارة تجريبية وليست ضمان ربح."
    )

# 3) الحالة عند التشغيل اليدوي
if manual and not new_signal:
    trend = "صاعد" if e20[-1] > e50[-1] else "هابط"
    note = " (توجد إشارة مفتوحة)" if has_open else ""
    out.append(
        f"لا توجد إشارة جديدة{note}\n"
        f"السعر: {price:.2f} | الاتجاه: {trend}\n"
        f"EMA20: {e20[-1]:.2f} | EMA50: {e50[-1]:.2f}\n"
        f"RSI14: {r14:.1f} | ATR14: {a14:.2f}"
    )

if out and (resolved or manual):
    out.append(stats())

with open(FILE, "w") as f:
    json.dump(signals, f, ensure_ascii=False, indent=1)

if out:
    send("\n\n".join(out))
