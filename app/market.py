"""Market data: weekly candles from the registry history, price anchoring to real quotes, forecast + recommendation."""
import json
import math
import threading
from datetime import date, datetime, timedelta

import duckdb
from pathlib import Path

from core import DATA, HISTORY_DB, INSTRUMENTS, q

_hist = {}
_lock = threading.Lock()
REAL_FILE = Path(__file__).with_name("data") / "real_market.json"


def _db():
    return duckdb.connect(str(HISTORY_DB), read_only=True)


def _real() -> dict:
    """Real weekly quotes scraped from uzex.uz QuotesDynamics (UZS per tonne)."""
    try:
        data = json.loads(REAL_FILE.read_text())
    except Exception:  # noqa: BLE001
        return {}
    return {c["key"]: c for c in data.get("commodities", [])}


def _monday(d: str) -> str:
    x = date.fromisoformat(d[:10])
    return (x - timedelta(days=x.weekday())).isoformat()


def _real_candles(series) -> list:
    pts = sorted([p for p in series["points"] if p.get("price")], key=lambda p: p["date"])
    weeks = {}
    for p in pts:
        weeks.setdefault(_monday(p["date"]), []).append(float(p["price"]))
    out, prev = [], None
    for w in sorted(weeks):
        vals = weeks[w]
        o = prev if prev is not None else vals[0]
        cl = vals[-1]
        out.append({"time": w, "open": round(o), "high": round(max([o] + vals)), "low": round(min([o] + vals)),
                    "close": round(cl), "vwap": round(sum(vals) / len(vals)), "volume": 0, "deals": len(vals),
                    "real": True})
        prev = cl
    return out


def load_history():
    """Weekly candles per instrument (UZS per tonne). Real UzEx quotes where available; otherwise the hackathon
    registry shape scaled to the latest real quote."""
    with _lock:
        if _hist:
            return _hist
        real = _real()
        con = _db()
        for key, ins in INSTRUMENTS.items():
            series = real.get(ins.get("real") or "")
            if series and len(series.get("points", [])) > 60:
                cs = _real_candles(series)
                last = cs[-1]
                _hist[key] = {"candles": cs, "scale": 1.0, "source": "uzex.uz · QuotesDynamics (реальные котировки)",
                              "product": (series.get("uzex_products") or [ins["name_ru"]])[0],
                              "anchor": {"price": last["close"], "date": last["time"], "source": "https://uzex.uz/Quote/QuotesDynamics"}}
                continue
            where = f"product_family='{ins['family']}' and is_valid and currency='UZS' and unit='тонна'"
            where += f" and brand='{ins['brand']}'" if ins["brand"] else ""
            rows = con.execute(f"""
                select date_trunc('week', deal_date) w,
                       arg_min(unit_price, deal_date + deal_time) o, max(unit_price) h, min(unit_price) l,
                       arg_max(unit_price, deal_date + deal_time) c,
                       sum(amount)/sum(volume) vwap, sum(volume) vol, count(*) n
                from v_deals where {where} group by 1 order by 1""").fetchall()
            cs = [{"time": str(r[0])[:10], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "vwap": r[5],
                   "volume": r[6], "deals": r[7]} for r in rows]
            anchor_series = real.get(ins.get("anchor_real") or "")
            scale, anchor = 1.0, None
            if anchor_series:
                pts = sorted([p for p in anchor_series["points"] if p.get("price")], key=lambda p: p["date"])[-3:]
                ref_real = sorted(float(p["price"]) for p in pts)[len(pts) // 2]
                scale = ref_real / (sum(c["vwap"] for c in cs[-4:]) / 4)
                anchor = {"price": ref_real, "date": pts[-1]["date"], "source": "https://uzex.uz/Quote/QuotesDynamics"}
            for c in cs:
                for f in ("open", "high", "low", "close", "vwap"):
                    c[f] = round(c[f] * scale)
            _hist[key] = {"candles": cs, "scale": scale, "anchor": anchor, "product": ins["name_ru"],
                          "source": "форма — реестр хакатона 2022–2026, уровень — реальная котировка uzex.uz"}
        con.close()
        return _hist


def last_price(key: str) -> int:
    live = q("select clearing_price from sessions where instrument=? and status='cleared' and clearing_price>0 "
             "order by closes_at desc limit 1", key)
    if live:
        return live[0]["clearing_price"]
    return load_history()[key]["candles"][-1]["vwap"]


def candles(key: str) -> list:
    """History candles + live session results folded into weekly candles."""
    out = [dict(c) for c in load_history()[key]["candles"]]
    live = q("select closes_at, clearing_price, matched from sessions where instrument=? and status='cleared' "
             "and clearing_price>0 order by closes_at", key)
    for s in live:
        d = datetime.fromtimestamp(s["closes_at"]).date()
        wk = (d - timedelta(days=d.weekday())).isoformat()
        p = s["clearing_price"]
        if out and out[-1]["time"] == wk:
            c = out[-1]
            c["high"], c["low"], c["close"] = max(c["high"], p), min(c["low"], p), p
            c["volume"] += s["matched"]
            c["live"] = True
        else:
            out.append({"time": wk, "open": out[-1]["close"] if out else p, "high": p, "low": p, "close": p,
                        "vwap": p, "volume": s["matched"], "deals": 1, "live": True})
    return out


# ------------------------------------------------------------------ forecast
def _season(series):
    """Month-of-year multiplicative factors from history (normalized to mean 1)."""
    by_m = {}
    # deseasonalize against a centred 13-week moving average
    vals = [c["vwap"] for c in series]
    for i, c in enumerate(series):
        lo, hi = max(0, i - 6), min(len(vals), i + 7)
        ma = sum(vals[lo:hi]) / (hi - lo)
        m = int(c["time"][5:7])
        by_m.setdefault(m, []).append(vals[i] / ma)
    f = {m: sum(v) / len(v) for m, v in by_m.items()}
    avg = sum(f.values()) / len(f) if f else 1
    return {m: f.get(m, avg) / avg for m in range(1, 13)}


def _fit(series):
    season = _season(series)
    des = [c["vwap"] / season[int(c["time"][5:7])] for c in series]
    alpha = 0.35
    level = des[0]
    for v in des[1:]:
        level = alpha * v + (1 - alpha) * level
    tail = des[-12:]
    n = len(tail)
    xm, ym = (n - 1) / 2, sum(tail) / n
    slope = sum((i - xm) * (y - ym) for i, y in enumerate(tail)) / max(1e-9, sum((i - xm) ** 2 for i in range(n)))
    trend = slope / max(ym, 1)
    return season, level, trend


def _predict(series, h):
    season, level, trend = _fit(series)
    last = date.fromisoformat(series[-1]["time"])
    out, damp = [], 0.85
    cum = 0.0
    for k in range(1, h + 1):
        cum += trend * damp ** k
        d = last + timedelta(weeks=k)
        out.append({"time": d.isoformat(), "price": level * (1 + cum) * season[d.month]})
    return out


def backtest(key: str, h: int = 4) -> float:
    """MAPE of h-week-ahead forecasts over the last ~52 weeks of history."""
    s = load_history()[key]["candles"]
    errs = []
    for end in range(max(60, len(s) - 52), len(s) - h):
        pred = _predict(s[:end], h)[-1]["price"]
        actual = s[end + h - 1]["vwap"]
        errs.append(abs(pred - actual) / actual)
    return round(100 * sum(errs) / max(1, len(errs)), 1)


def forecast(key: str, weeks: int = 8) -> dict:
    s = candles(key)
    this_week = date.today() - timedelta(days=date.today().weekday())
    gap = max(0, (this_week - date.fromisoformat(s[-1]["time"])).days // 7)
    pts = [p for p in _predict(s, weeks + gap) if p["time"] > this_week.isoformat()][:weeks]
    mape = backtest(key)
    band = mape / 100 * 1.25
    cur = last_price(key)
    for i, p in enumerate(pts):
        w = band * math.sqrt((i + 1) / 4)
        p.update(price=round(p["price"]), low=round(p["price"] * (1 - w)), high=round(p["price"] * (1 + w)))
    return {"instrument": key, "current": cur, "points": pts, "mape": mape,
            "method": "сезонность по месяцам (2022–2026) + сглаженный уровень + затухающий тренд",
            "accuracy_note": f"средняя ошибка прогноза на 4 недели по истории: {mape}%"}


def recommend(key: str, side: str = "buy", horizon_weeks: int = 6) -> dict:
    """'Buy now' vs 'wait' — a recommendation, never an instruction."""
    f = forecast(key, max(1, horizon_weeks))
    cur = f["current"]
    pts = f["points"][:horizon_weeks]
    best = min(pts, key=lambda p: p["price"]) if side == "buy" else max(pts, key=lambda p: p["price"])
    delta = (best["price"] - cur) / cur
    threshold = max(0.015, f["mape"] / 100 * 0.6)
    s = candles(key)
    month = date.today().month
    same_month = [c["vwap"] for c in s if int(c["time"][5:7]) == month]
    yr = [c["vwap"] for c in s[-52:]]
    pos = (cur - min(yr)) / max(1, (max(yr) - min(yr)))
    if side == "buy":
        action = "wait" if delta < -threshold else "buy_now"
        saving = -delta if action == "wait" else 0
    else:
        action = "wait" if delta > threshold else "sell_now"
        saving = delta if action == "wait" else 0
    conf = "высокая" if abs(delta) > 2 * threshold else "средняя" if abs(delta) > threshold else "низкая"
    return {
        "instrument": key, "side": side, "action": action, "current": cur,
        "target_week": best["time"], "target_price": best["price"], "expected_change_pct": round(100 * delta, 1),
        "expected_saving_pct": round(100 * saving, 1), "confidence": conf, "mape": f["mape"],
        "year_position_pct": round(100 * pos), "same_month_avg": round(sum(same_month) / len(same_month)) if same_month else None,
        "reasons": [
            f"Текущая цена {cur:,.0f} сум/т — {round(100 * pos)}% от годового диапазона (0% = годовой минимум)".replace(",", " "),
            f"Модель ждёт {'снижения' if delta < 0 else 'роста'} до ~{best['price']:,.0f} сум/т к неделе {best['time']}"
            .replace(",", " "),
            f"Средняя ошибка модели на истории — {f['mape']}%, поэтому порог для совета «ждать» — {round(100 * threshold, 1)}%",
        ],
        "disclaimer": "Это рекомендация, а не указание: решение принимает человек.",
    }


# ------------------------------------------------------------------ seasonality («когда лучше покупать»)
MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def seasonality(key: str) -> dict:
    """Average deviation of each calendar month from its own year's mean, over the real weekly series."""
    cs = load_history()[key]["candles"]
    by_year = {}
    for c in cs:
        by_year.setdefault(c["time"][:4], []).append(c)
    dev = {m: [] for m in range(1, 13)}
    for y, rows in by_year.items():
        if len(rows) < 26:
            continue
        mean = sum(r["vwap"] for r in rows) / len(rows)
        for r in rows:
            dev[int(r["time"][5:7])].append(r["vwap"] / mean - 1)
    months = [{"month": m, "name": MONTHS[m - 1], "dev_pct": round(100 * sum(v) / len(v), 1) if v else None,
               "years": len(v)} for m, v in dev.items()]
    valid = [x for x in months if x["dev_pct"] is not None]
    cheapest = sorted(valid, key=lambda x: x["dev_pct"])[:3]
    priciest = sorted(valid, key=lambda x: -x["dev_pct"])[:3]
    cur_m = date.today().month
    cur = next((x for x in months if x["month"] == cur_m), None)
    return {"instrument": key, "months": months, "cheapest": [x["name"] for x in cheapest],
            "priciest": [x["name"] for x in priciest], "current_month": cur,
            "years_used": sorted(by_year), "source": load_history()[key].get("source"),
            "note": "Отклонение средней цены месяца от средней цены своего года по реальным недельным котировкам."}


def index() -> dict:
    """UZEX commodity index: equal-weighted, each instrument normalized to 100 at its first 2024 week."""
    series = {}
    for k in INSTRUMENTS:
        cs = [c for c in candles(k) if c["time"] >= "2024-01-01"]
        if cs:
            base = cs[0]["vwap"]
            series[k] = {c["time"]: c["close"] / base * 100 for c in cs}
    weeks = sorted(set().union(*[set(v) for v in series.values()]))
    pts, last = [], {}
    for w in weeks:
        for k, v in series.items():
            if w in v:
                last[k] = v[w]
        if len(last) == len(series):
            pts.append({"time": w, "value": round(sum(last.values()) / len(last), 2)})
    cur, prev = pts[-1]["value"], pts[-2]["value"] if len(pts) > 1 else pts[-1]["value"]
    return {"name": "UZEX Commodity Index", "points": pts[-130:], "value": cur, "change_pct": round(100 * (cur - prev) / prev, 2),
            "method": "равновзвешенный, 8 товаров, база = 100 на первую неделю 2024 года"}
