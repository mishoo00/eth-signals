import os, json, time, hmac, base64, hashlib
from datetime import datetime, timezone
import requests


def num(name, default):
    v = os.environ.get(name, "")
    return float(v) if v.strip() else float(default)


def clean(v):
    return "".join(ch for ch in v if 33 <= ord(ch) <= 126)


TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
MODE = (os.environ.get("MODE", "") or "auto").strip()
TRADING = (os.environ.get("TRADING_MODE", "") or "off").strip().lower()
if TRADING not in ("off", "demo", "live"):
    TRADING = "off"
RISK_USD = num("RISK_USD", 2)
CAPITAL = num("CAPITAL", 100)
MAX_LEV = int(num("MAX_LEV", 5))
MAX_DAILY_LOSS = num("MAX_DAILY_LOSS", 6)
MAX_LOSS_STREAK = int(num("MAX_LOSS_STREAK", 3))

KEY = clean(os.environ.get("OKX_API_KEY", ""))
SEC = clean(os.environ.get("OKX_API_SECRET", ""))
PASS = clean(os.environ.get("OKX_PASSPHRASE", ""))

FILE = "signals.json"
FEE = 0.0008
MAX_CANDLES = 144
INST = "ETH-USDT-SWAP"
OKX = "https://www.okx.com"
CT_VAL = 0.1   # كل عقد = 0.1 ETH
LOT = 0.01     # أصغر خطوة للعقود
TAG = "[تجريبي] " if TRADING == "demo" else ("[حقيقي] " if TRADING == "live" else "")


# ---------- تيليجرام ----------
def tg(text):
    print(text)
    if not TOKEN or not CHAT:
        return
    try:
        requests.post("https://api.telegram.org/bot" + TOKEN + "/sendMessage",
                      data={"chat_id": CHAT, "text": text}, timeout=15)
    except Exception as e:
        print("telegram error:", type(e).__name__)


# ---------- البيانات والمؤشرات ----------
def klines():
    r = requests.get("https://data-api.binance.vision/api/v3/klines",
                     params={"symbol": "ETHUSDT", "interval": "5m", "limit": 300}, timeout=20)
    r.raise_for_status()
    rows = r.json()[:-1]  # نحذف الشمعة الحالية (لسه ما قفلت)
    return [(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in rows]


def ema_series(vals, n):
    k = 2.0 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes, n=14):
    g = l = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        g += max(d, 0)
        l += max(-d, 0)
    ag, al = g / n, l / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def atr(c, n=14):
    trs = []
    for i in range(1, len(c)):
        h, l, pc = c[i][1], c[i][2], c[i - 1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def detect(candles):
    closes = [c[3] for c in candles]
    e20 = ema_series(closes, 20)
    e50 = ema_series(closes, 50)
    r = rsi(closes)
    a = atr(candles)
    price = closes[-1]
    side = None
    if e20[-1] > e50[-1] and e50[-1] > e50[-10] and closes[-2] < e20[-2] and price > e20[-1] and 50 <= r <= 70:
        side = "buy"
    elif e20[-1] < e50[-1] and e50[-1] < e50[-10] and closes[-2] > e20[-2] and price < e20[-1] and 30 <= r <= 50:
        side = "sell"
    return side, price, a, r, e20[-1], e50[-1]


# ---------- سجل الإشارات ----------
def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except Exception:
        return []


def save(s):
    with open(FILE, "w") as f:
        json.dump(s, f, indent=1, ensure_ascii=False)


def fee_r(s):
    risk = abs(s["entry"] - s["sl"])
    return FEE * s["entry"] / risk if risk else 0.0


def resolve(sigs, candles):
    done = []
    for s in sigs:
        if s.get("status") != "open":
            continue
        buy = s["side"] == "buy"
        later = [c for c in candles if c[0] > s["id"]]
        risk = abs(s["entry"] - s["sl"])
        if risk == 0:
            continue
        res = None
        for c in later:
            hit_sl = c[2] <= s["sl"] if buy else c[1] >= s["sl"]
            hit_tp = c[1] >= s["tp"] if buy else c[2] <= s["tp"]
            if hit_sl:  # نفحص الوقف أول (تحفظًا)
                res = ("sl", -1.0)
                break
            if hit_tp:
                res = ("tp", abs(s["tp"] - s["entry"]) / risk)
                break
        if not res and len(later) >= MAX_CANDLES:
            last = later[-1][3]
            g = ((last - s["entry"]) if buy else (s["entry"] - last)) / risk
            res = ("expired", g)
        if res:
            s["status"] = res[0]
            s["r"] = round(res[1] - fee_r(s), 3)
            done.append(s)
    return done


def stats(sigs):
    d = [s for s in sigs if s.get("status") in ("tp", "sl", "expired")]
    o = [s for s in sigs if s.get("status") == "open"]
    if not d:
        return "📊 السجل: ما في صفقات مقفلة لسه (مفتوحة: %d)" % len(o)
    w = [s for s in d if s.get("r", 0) > 0]
    tot = sum(s.get("r", 0) for s in d)
    return "📊 السجل: %d مقفلة | رابحة %d (%.0f%%) | صافي %+.2fR | مفتوحة %d" % (
        len(d), len(w), 100 * len(w) / len(d), tot, len(o))


# ---------- OKX ----------
def okx(method, path, body=None):
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)
    b = json.dumps(body) if body is not None else ""
    sig = base64.b64encode(hmac.new(SEC.encode(), (ts + method + path + b).encode(),
                                    hashlib.sha256).digest()).decode()
    h = {"OK-ACCESS-KEY": KEY, "OK-ACCESS-SIGN": sig, "OK-ACCESS-TIMESTAMP": ts,
         "OK-ACCESS-PASSPHRASE": PASS, "Content-Type": "application/json"}
    if TRADING == "demo":
        h["x-simulated-trading"] = "1"
    r = requests.request(method, OKX + path, headers=h, data=b if b else None, timeout=20)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError("okx http %s" % r.status_code)
    if j.get("code") != "0":
        raise RuntimeError("okx %s code %s %s %s" % (path.split("?")[0], j.get("code"),
                                                      j.get("msg"), str(j.get("data"))[:200]))
    return j.get("data", [])


def position_open():
    for p in okx("GET", "/api/v5/account/positions?instType=SWAP&instId=" + INST):
        if abs(float(p.get("pos") or 0)) > 0:
            return p
    return None


def balance():
    d = okx("GET", "/api/v5/account/balance?ccy=USDT")
    for x in d[0].get("details", []):
        if x.get("ccy") == "USDT":
            return float(x.get("availBal") or 0)
    return 0.0


def last_price():
    return float(okx("GET", "/api/v5/market/ticker?instId=" + INST)[0]["last"])


def pending_algos():
    res = []
    for t in ("oco", "conditional"):
        try:
            res += okx("GET", "/api/v5/trade/orders-algo-pending?ordType=%s&instId=%s" % (t, INST))
        except Exception as e:
            print("algo query", t, str(e)[:120])
    return res


def cancel_algos():
    a = pending_algos()
    if a:
        try:
            okx("POST", "/api/v5/trade/cancel-algos",
                [{"algoId": x["algoId"], "instId": INST} for x in a[:10]])
        except Exception as e:
            print("cancel algos", str(e)[:120])


def force_close():
    okx("POST", "/api/v5/trade/close-position", {"instId": INST, "mgnMode": "isolated"})
    time.sleep(1)
    cancel_algos()


def size(entry, sl, avail):
    dist = abs(entry - sl)
    if dist <= 0:
        return 0.0
    sz = RISK_USD / (dist * CT_VAL)                       # الحجم اللي يخلي الخسارة = RISK_USD
    cap = min(CAPITAL, avail) * MAX_LEV                   # سقف القيمة الكلية
    sz = min(sz, cap / (entry * CT_VAL))
    return int(sz * 100) / 100.0


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def gates(sigs):
    ex = [s["exec"] for s in sigs if s.get("exec") and s["exec"].get("status") == "closed"]
    day = sum(e.get("pnl_usd", 0) for e in ex if e.get("closed_day") == today())
    if day <= -MAX_DAILY_LOSS:
        return "وصلنا حد الخسارة اليومي (%.2f$)" % day
    last = ex[-MAX_LOSS_STREAK:]
    if len(last) == MAX_LOSS_STREAK and all(e.get("pnl_usd", 0) < 0 for e in last):
        if time.time() - last[-1].get("closed_ts", 0) < 6 * 3600:
            return "%d خسائر متتالية، وقفة 6 ساعات" % MAX_LOSS_STREAK
    return None


def try_open(sig, sigs):
    g = gates(sigs)
    if g:
        return "⏸️ %sما فتحت الصفقة: %s" % (TAG, g)
    if position_open():
        return "⏸️ %sما فتحت الصفقة: في صفقة مفتوحة على المنصة" % TAG
    sz = size(sig["entry"], sig["sl"], balance())
    if sz < LOT:
        return "⏸️ %sما فتحت الصفقة: الحجم أصغر من الحد الأدنى" % TAG
    px = last_price()
    buy = sig["side"] == "buy"
    ok = (sig["sl"] < px < sig["tp"]) if buy else (sig["tp"] < px < sig["sl"])
    if not ok:
        return "⏸️ %sما فتحت الصفقة: السعر تحرك وتجاوز الوقف أو الهدف" % TAG
    okx("POST", "/api/v5/account/set-leverage",
        {"instId": INST, "lever": str(MAX_LEV), "mgnMode": "isolated"})
    body = {"instId": INST, "tdMode": "isolated", "side": sig["side"], "ordType": "market",
            "sz": "%.2f" % sz,
            "attachAlgoOrds": [{"tpTriggerPx": "%.2f" % sig["tp"], "tpOrdPx": "-1",
                                "tpTriggerPxType": "last",
                                "slTriggerPx": "%.2f" % sig["sl"], "slOrdPx": "-1",
                                "slTriggerPxType": "last"}]}
    t0 = int(time.time() * 1000)
    d = okx("POST", "/api/v5/trade/order", body)[0]
    if d.get("sCode") != "0":
        return "❌ %sرفضت المنصة الأمر: %s" % (TAG, d.get("sMsg"))
    fill = None
    time.sleep(1.5)
    try:
        o = okx("GET", "/api/v5/trade/order?instId=%s&ordId=%s" % (INST, d["ordId"]))[0]
        fill = float(o.get("avgPx") or 0) or None
    except Exception as e:
        print("fill query", str(e)[:120])
    dist = abs(sig["entry"] - sig["sl"])
    sig["exec"] = {"status": "open", "mode": TRADING, "ordId": d["ordId"], "sz": sz,
                   "fill": fill, "open_ts": t0}
    return ("%s %sفتحت صفقة %s ETH\nالدخول: %s%s\nالكمية: %.2f عقد (%.3f ETH)\n"
            "وقف الخسارة: %.2f\nالهدف: %.2f\nالخسارة المتوقعة: -%.2f$ | الربح المتوقع: +%.2f$") % (
        "🟢" if buy else "🔴", TAG, "شراء" if buy else "بيع", sig["entry"],
        (" (فعلي %s)" % fill) if fill else "", sz, sz * CT_VAL, sig["sl"], sig["tp"],
        sz * CT_VAL * dist, sz * CT_VAL * abs(sig["tp"] - sig["entry"]))


def sync_exec(sigs):
    msgs = []
    pos = position_open()
    for s in sigs:
        ex = s.get("exec")
        if not ex or ex.get("status") != "open":
            continue
        if pos is not None and s.get("status") == "expired":
            force_close()
            time.sleep(2)
            pos = position_open()
            msgs.append("⏰ %sأغلقت الصفقة لانتهاء مدتها" % TAG)
        if pos is None:
            h = okx("GET", "/api/v5/account/positions-history?instType=SWAP&instId=%s&limit=1" % INST)
            fresh = h and int(h[0].get("uTime") or 0) >= ex.get("open_ts", 0)
            stale = time.time() * 1000 - ex.get("open_ts", 0) > 2 * 3600 * 1000
            if not fresh and not stale:
                continue
            pnl = float(h[0].get("realizedPnl") or h[0].get("pnl") or 0) if fresh else 0.0
            ex.update({"status": "closed", "pnl_usd": round(pnl, 2), "closed_day": today(),
                       "closed_ts": int(time.time())})
            msgs.append("%s %sانقفلت الصفقة: %+.2f$ (بعد الرسوم)" % (
                "✅" if pnl > 0 else "❌", TAG, pnl))
    return msgs


def self_test():
    if TRADING != "demo":
        tg("🧪 الاختبار يشتغل بالتجريبي فقط (TRADING_MODE لازم يكون demo)")
        return
    out = []
    try:
        if position_open():
            tg("🧪 في صفقة مفتوحة أصلًا، ما سويت الاختبار")
            return
        px = last_price()
        out.append("السعر: %.2f" % px)
        okx("POST", "/api/v5/account/set-leverage", {"instId": INST, "lever": "2", "mgnMode": "isolated"})
        out.append("الرافعة ✅")
        body = {"instId": INST, "tdMode": "isolated", "side": "buy", "ordType": "market", "sz": "0.01",
                "attachAlgoOrds": [{"tpTriggerPx": "%.2f" % (px * 1.02), "tpOrdPx": "-1",
                                    "tpTriggerPxType": "last",
                                    "slTriggerPx": "%.2f" % (px * 0.98), "slOrdPx": "-1",
                                    "slTriggerPxType": "last"}]}
        d = okx("POST", "/api/v5/trade/order", body)[0]
        out.append("الأمر ✅" if d.get("sCode") == "0" else "الأمر ❌ " + str(d.get("sMsg")))
        time.sleep(2)
        out.append("الصفقة ظاهرة ✅" if position_open() else "الصفقة ما ظهرت ❌")
        out.append("أوامر وقف/هدف معلّقة: %d" % len(pending_algos()))
        force_close()
        time.sleep(2)
        out.append("الإغلاق ✅" if not position_open() else "الإغلاق ❌")
        out.append("معلّق بعد الإغلاق: %d" % len(pending_algos()))
    except Exception as e:
        out.append("❌ " + str(e)[:250])
    tg("🧪 نتيجة الاختبار:\n" + "\n".join(out))


# ---------- التشغيل ----------
def main():
    if MODE == "test":
        self_test()
        return
    candles = klines()
    sigs = load()
    msgs = []
    resolved = resolve(sigs, candles)
    for s in resolved:
        msgs.append("%s إشارة %s انتهت: %s (%+.2fR)" % (
            "✅" if s["r"] > 0 else "❌", "شراء" if s["side"] == "buy" else "بيع",
            {"tp": "الهدف", "sl": "الوقف", "expired": "انتهت مدتها"}[s["status"]], s["r"]))

    side, price, a, r, e20, e50 = detect(candles)
    new = None
    if side and not any(s.get("status") == "open" for s in sigs) \
            and not any(s.get("id") == candles[-1][0] for s in sigs):
        k = 1 if side == "buy" else -1
        new = {"id": candles[-1][0], "side": side, "entry": round(price, 2),
               "sl": round(price - k * 1.5 * a, 2), "tp": round(price + k * 3.75 * a, 2),
               "status": "open"}
        sigs.append(new)
        msgs.append("%s إشارة %s ETH\nالدخول: %.2f\nوقف الخسارة: %.2f\nالهدف: %.2f\nRSI: %.0f" % (
            "🟢" if side == "buy" else "🔴", "شراء" if side == "buy" else "بيع",
            new["entry"], new["sl"], new["tp"], r))

    if TRADING != "off" and KEY and SEC and PASS:
        try:
            msgs += sync_exec(sigs)
        except Exception as e:
            msgs.append("⚠️ %sمشكلة في مزامنة الصفقات: %s" % (TAG, str(e)[:200]))
        if new:
            try:
                msgs.append(try_open(new, sigs))
            except Exception as e:
                msgs.append("⚠️ %sمشكلة في فتح الصفقة: %s" % (TAG, str(e)[:200]))
    save(sigs)

    if MODE == "manual":
        msgs.append("✅ شغّال | السعر %.2f | EMA20 %.2f | EMA50 %.2f | RSI %.0f\n"
                    "التداول التلقائي: %s\n%s" % (price, e20, e50, r, TRADING, stats(sigs)))
    if msgs:
        tg("\n\n".join(msgs))
    else:
        print("لا جديد")


if __name__ == "__main__":
    main()
