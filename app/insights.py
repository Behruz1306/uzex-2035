"""Exchange data → business insights (the "AI broker" knowledge layer).

Everything is computed from the UZEX deal registry (history.duckdb, 500k deals 2022–2026).
Privacy rule: counterparties of other companies are never revealed; any group with fewer than
K_MIN distinct companies is suppressed. Seller reliability is shown by name (sellers are the
offer side of a public exchange; their execution record is what the rating is for).
"""
import re
import threading
from functools import lru_cache

import duckdb

from core import HISTORY_DB

K_MIN = 3
LAST_FULL = 2025          # last complete year in the registry
YTD_MONTHS = 10           # registry ends 30.10.2026
_local = threading.local()

MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", ["a", "b", "v", "g", "d", "e", "yo", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
                                                    "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))
EN = {"Хлопок-сырец": "Raw cotton", "Пшеница": "Wheat", "Масло хлопковое": "Cottonseed oil", "Катод медный": "Copper cathode",
      "Полиэтилен": "Polyethylene", "Сахар": "Sugar", "Дизельное топливо": "Diesel fuel", "Бензин": "Gasoline", "Цемент": "Cement",
      "Масло подсолнечное": "Sunflower oil", "Арматура": "Rebar", "Карбамид": "Urea", "Пряжа хлопковая": "Cotton yarn",
      "Полипропилен": "Polypropylene", "Аммиачная селитра": "Ammonium nitrate", "Шрот хлопковый": "Cottonseed meal",
      "Мука пшеничная": "Wheat flour", "Газ сжиженный": "LPG", "Поливинилхлорид (ПВХ)": "PVC", "Рис": "Rice", "Битум": "Bitumen",
      "Мазут": "Fuel oil", "Пиломатериалы": "Sawn timber", "Комбикорм / кормосмесь": "Compound feed", "Лист стальной": "Steel sheet",
      "Кислота серная": "Sulfuric acid", "Профиль алюминиевый": "Aluminium profile", "Сода каустическая": "Caustic soda",
      "Соль пищевая": "Table salt", "Стекло": "Glass", "Проволока арматурная": "Rebar wire", "Кирпич": "Brick", "Гипс": "Gypsum",
      "Известь": "Lime", "Кабель силовой": "Power cable", "Эмаль": "Enamel paint", "Трубы полиэтиленовые": "PE pipes",
      "Вода питьевая": "Drinking water", "Азот": "Nitrogen", "Аргон": "Argon", "Подшипник": "Bearing"}
SYN = {"селитра": "Аммиачная селитра", "selitra": "Аммиачная селитра", "nitrate": "Аммиачная селитра", "мочевина": "Карбамид",
       "karbamid": "Карбамид", "urea": "Карбамид", "мука": "Мука пшеничная", "un": "Мука пшеничная", "flour": "Мука пшеничная",
       "sement": "Цемент", "cement": "Цемент", "shakar": "Сахар", "sugar": "Сахар", "bugdoy": "Пшеница", "bug'doy": "Пшеница",
       "wheat": "Пшеница", "пропан": "Газ сжиженный", "газ": "Газ сжиженный", "lpg": "Газ сжиженный", "propan": "Газ сжиженный",
       "солярка": "Дизельное топливо", "дизель": "Дизельное топливо", "diesel": "Дизельное топливо", "аи-92": "Бензин",
       "benzin": "Бензин", "gasoline": "Бензин", "пэ": "Полиэтилен", "polyethylene": "Полиэтилен", "пп": "Полипропилен",
       "polypropylene": "Полипропилен", "пвх": "Поливинилхлорид (ПВХ)", "pvc": "Поливинилхлорид (ПВХ)", "медь": "Катод медный",
       "copper": "Катод медный", "арматура": "Арматура", "rebar": "Арматура", "armatura": "Арматура", "хлопок": "Хлопок-сырец",
       "paxta": "Хлопок-сырец", "cotton": "Хлопок-сырец", "пряжа": "Пряжа хлопковая", "yarn": "Пряжа хлопковая",
       "масло": "Масло подсолнечное", "yog'": "Масло подсолнечное", "oil": "Масло подсолнечное", "рис": "Рис", "guruch": "Рис",
       "rice": "Рис", "кирпич": "Кирпич", "g'isht": "Кирпич", "brick": "Кирпич", "доска": "Пиломатериалы", "лес": "Пиломатериалы",
       "timber": "Пиломатериалы", "стекло": "Стекло", "glass": "Стекло", "битум": "Битум", "bitumen": "Битум", "комбикорм": "Комбикорм / кормосмесь",
       "feed": "Комбикорм / кормосмесь", "соль": "Соль пищевая", "salt": "Соль пищевая", "кабель": "Кабель силовой", "cable": "Кабель силовой",
       "трубы": "Трубы полиэтиленовые", "pipes": "Трубы полиэтиленовые", "шрот": "Шрот хлопковый", "известь": "Известь", "гипс": "Гипс"}


def con():
    c = getattr(_local, "c", None)
    if c is None:
        c = _local.c = duckdb.connect(str(HISTORY_DB), read_only=True)
    return c


def rows(sql, *args):
    cur = con().execute(sql, list(args))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def slug(name: str) -> str:
    s = "".join(_TR.get(ch, ch) for ch in name.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def growth(a, b):
    return round((a / b - 1) * 100, 1) if a and b else None


# ------------------------------------------------------------------ markets
@lru_cache(maxsize=1)
def families() -> list:
    """Every product family with size, growth, competition and reliability. Dominant unit only (no mixing kg/t)."""
    base = rows(f"""
      with u as (select product_family f, unit, count(*) n, row_number() over (partition by product_family order by count(*) desc) r
                 from v_deals group by 1, 2),
      d as (select v.* from v_deals v join u on u.f = v.product_family and u.unit = v.unit and u.r = 1)
      select product_family f, any_value(unit) unit, any_value(category) category, any_value(industry) industry,
        sum(case when year = {LAST_FULL} then amount_uzs end) vol,
        sum(case when year = {LAST_FULL - 1} then amount_uzs end) vol_prev,
        sum(case when year = {LAST_FULL} then amount_usd end) vol_usd,
        sum(case when year = {LAST_FULL + 1} then amount_uzs end) ytd,
        sum(case when year = {LAST_FULL} and month <= {YTD_MONTHS} then amount_uzs end) ytd_prev,
        sum(case when year = {LAST_FULL} then volume end) qty,
        count(case when year = {LAST_FULL} then 1 end) deals,
        count(distinct case when year = {LAST_FULL} then buyer_inn end) buyers,
        count(distinct case when year = {LAST_FULL} then seller_inn end) sellers,
        count(distinct case when year = {LAST_FULL - 1} then seller_inn end) sellers_prev,
        avg(case when year >= {LAST_FULL} then case when is_executed then 1.0 else 0 end end) exec_rate,
        median(case when deal_date >= date '2026-08-01' and volume > 0 then amount_uzs / volume end) price,
        median(case when deal_date >= date '2025-08-01' and deal_date < date '2025-11-01' and volume > 0 then amount_uzs / volume end) price_ly
      from d group by 1""")
    top = {r["f"]: r["s"] for r in rows(f"""
      with t as (select product_family f, seller_inn, sum(amount_uzs) s from v_deals where year = {LAST_FULL} group by 1, 2),
      r as (select f, s, row_number() over (partition by f order by s desc) rk, sum(s) over (partition by f) tot from t)
      select f, sum(s) / any_value(tot) s from r where rk <= 3 group by 1""")}
    spark = {}
    for r in rows("""select product_family f, strftime(date_trunc('month', deal_date), '%Y-%m') m, sum(amount_uzs) v from v_deals
                     where deal_date >= date '2025-07-01' group by 1, 2 order by 1, 2"""):
        spark.setdefault(r["f"], []).append(round(r["v"]))
    out = []
    for r in base:
        if not r["vol"]:
            continue
        out.append({"name": r["f"], "en": EN.get(r["f"], r["f"]), "slug": slug(EN.get(r["f"], r["f"])), "unit": r["unit"],
                    "category": r["category"], "industry": r["industry"], "volume_uzs": round(r["vol"]),
                    "volume_usd": round(r["vol_usd"] or 0), "qty": round(r["qty"] or 0), "deals": r["deals"],
                    "buyers": r["buyers"], "sellers": r["sellers"], "sellers_prev": r["sellers_prev"],
                    "growth": growth(r["vol"], r["vol_prev"]), "growth_ytd": growth(r["ytd"], r["ytd_prev"]),
                    "top3_share": round(top.get(r["f"], 0) * 100, 1), "exec_rate": round((r["exec_rate"] or 0) * 100, 1),
                    "price": round(r["price"]) if r["price"] else None,
                    "price_change": growth(r["price"], r["price_ly"]), "spark": spark.get(r["f"], [])[-16:]})
    out.sort(key=lambda x: -x["volume_uzs"])
    return out


def by_slug(s):
    return next((f for f in families() if f["slug"] == s or f["name"] == s), None)


@lru_cache(maxsize=64)
def family(name: str) -> dict:
    f = by_slug(name)
    if not f:
        return {}
    n = f["name"]
    unit = f["unit"]
    monthly = rows("""select strftime(date_trunc('month', deal_date), '%Y-%m') m, sum(amount_uzs) vol, sum(volume) qty,
        median(case when volume > 0 then amount_uzs / volume end) price, count(distinct buyer_inn) buyers
        from v_deals where product_family = ? and unit = ? group by 1 order by 1""", n, unit)
    season = rows(f"""with m as (select year, month, sum(amount_uzs) v from v_deals where product_family = ? and year between 2022 and {LAST_FULL} group by 1, 2),
        y as (select year, avg(v) a from m group by 1)
        select month, avg(v / a) idx from m join y using(year) group by 1 order by 1""", n)
    pseason = rows(f"""with m as (select year, month, median(amount_uzs / volume) p from v_deals where product_family = ? and unit = ? and volume > 0
        and year between 2022 and {LAST_FULL} group by 1, 2), y as (select year, avg(p) a from m group by 1)
        select month, avg(p / a) idx from m join y using(year) group by 1 order by 1""", n, unit)
    regions = rows(f"""select region, sum(case when year = {LAST_FULL} then amount_uzs end) vol,
        sum(case when year = {LAST_FULL - 1} then amount_uzs end) prev, count(distinct case when year = {LAST_FULL} then buyer_inn end) buyers
        from v_deals where product_family = ? group by 1 order by 2 desc nulls last""", n)
    tot = sum(r["vol"] or 0 for r in regions) or 1
    regions = [{"region": r["region"], "share": round((r["vol"] or 0) / tot * 100, 1), "growth": growth(r["vol"], r["prev"]),
                "buyers": r["buyers"]} for r in regions if (r["buyers"] or 0) >= K_MIN]
    sellers = rows(f"""select seller_inn inn, any_value(seller_name) name, count(*) deals, sum(amount_uzs) vol,
        avg(case when is_executed then 1.0 else 0 end) exec_rate,
        avg(case when delivered_on is not null and delivery_term_days is not null
                 then case when date_diff('day', deal_date, delivered_on) <= delivery_term_days then 1.0 else 0 end end) on_time,
        count(distinct buyer_inn) buyers, min(year) since
        from v_deals where product_family = ? and year >= {LAST_FULL - 1} group by 1 having count(*) >= 5 order by vol desc limit 40""", n)
    stot = sum(s["vol"] for s in sellers) or 1
    for s in sellers:
        s["share"] = round(s["vol"] / stot * 100, 1)
        s["exec_rate"] = round((s["exec_rate"] or 0) * 100, 1)
        s["on_time"] = round((s["on_time"] or 0) * 100, 1)
        s["score"] = score(s["exec_rate"], s["on_time"], s["since"], s["deals"])
        del s["vol"]
    sellers.sort(key=lambda s: (-s["score"], -s["deals"]))
    newb = rows(f"""with fst as (select buyer_inn, min(year) y from v_deals where product_family = ? group by 1)
        select y, count(*) n from fst group by 1 order by 1""", n)
    size = rows(f"""with b as (select buyer_inn, sum(amount_uzs) s from v_deals where product_family = ? and year = {LAST_FULL} group by 1)
        select count(*) n, median(s) med, sum(case when s < 650000000 then 1 else 0 end) small from b""", n)[0]
    return {**f, "monthly": [{"m": r["m"], "vol": round(r["vol"] or 0), "qty": round(r["qty"] or 0),
                               "price": round(r["price"]) if r["price"] else None, "buyers": r["buyers"]} for r in monthly],
            "season_volume": [round(r["idx"] * 100) for r in season], "season_price": [round(r["idx"] * 100, 1) for r in pseason],
            "regions": regions, "top_sellers": sellers[:12], "new_buyers": {r["y"]: r["n"] for r in newb},
            "buyer_size": {"buyers": size["n"], "median_uzs": round(size["med"] or 0), "small": size["small"]}}


def score(exec_rate, on_time, since, deals):
    """0–100: execution (40), on-time delivery (30), years on exchange (15), track record (15)."""
    tenure = min(max(2026 - (since or 2026), 0), 4) / 4
    vol = min(deals / 300, 1)
    return round(min(max((exec_rate - 80) * 3, 0), 40) + min(max((on_time - 50) * 1.2, 0), 30) + 15 * tenure + 15 * vol)


def cheapest_months(name):
    d = family(name)
    p = d.get("season_price") or []
    if len(p) < 12:
        return []
    order = sorted(range(12), key=lambda i: p[i])
    return [{"month": MONTHS[i], "vs_avg": round(p[i] - 100, 1)} for i in order[:3]]


# ------------------------------------------------------------------ one company
def company(inn: str) -> dict:
    """Personal cabinet: market share, regional gaps, where to grow, reliability, buying efficiency."""
    inn = re.sub(r"\D", "", str(inn or ""))
    who = rows("""select any_value(seller_name) sn, count(case when seller_inn = ? then 1 end) sd,
                         count(case when buyer_inn = ? then 1 end) bd from v_deals where seller_inn = ? or buyer_inn = ?""", inn, inn, inn, inn)[0]
    bn = rows("select any_value(buyer_name) n from v_deals where buyer_inn = ?", inn)[0]["n"]
    if not who["sd"] and not who["bd"]:
        return {"found": False, "inn": inn}
    out = {"found": True, "inn": inn, "name": (rows("select any_value(seller_name) n from v_deals where seller_inn = ?", inn)[0]["n"] if who["sd"] else bn),
           "as_seller": who["sd"], "as_buyer": who["bd"]}
    if who["sd"]:
        out["seller"] = _seller(inn)
    if who["bd"]:
        out["buyer"] = _buyer(inn)
    side = "seller" if who["sd"] else "buyer"
    r = rows(f"""select avg(case when is_executed then 1.0 else 0 end) e, min(year) since, count(*) d,
        avg(case when delivered_on is not null and delivery_term_days is not null
                 then case when date_diff('day', deal_date, delivered_on) <= delivery_term_days then 1.0 else 0 end end) ot
        from v_deals where {side}_inn = ?""", inn)[0]
    mk = rows("select avg(case when is_executed then 1.0 else 0 end) e from v_deals where year >= 2025")[0]["e"]
    out["rating"] = {"score": score((r["e"] or 0) * 100, (r["ot"] or 0) * 100, r["since"], r["d"]),
                     "exec_rate": round((r["e"] or 0) * 100, 1), "on_time": round((r["ot"] or 0) * 100, 1),
                     "since": r["since"], "deals": r["d"], "market_exec_rate": round(mk * 100, 1)}
    return out


def _seller(inn):
    mine = rows(f"""select product_family f, sum(case when year = {LAST_FULL} then amount_uzs end) v, sum(case when year = {LAST_FULL - 1} then amount_uzs end) vp,
        count(distinct case when year = {LAST_FULL} then buyer_inn end) b, sum(case when year = {LAST_FULL} then volume end) q
        from v_deals where seller_inn = ? group by 1 order by 2 desc nulls last""", inn)
    fam = {f["name"]: f for f in families()}
    prev = {r["f"]: r["v"] for r in rows(f"select product_family f, sum(amount_uzs) v from v_deals where year = {LAST_FULL - 1} group by 1")}
    markets = []
    for m in mine:
        f = fam.get(m["f"])
        if not f or not m["v"]:
            continue
        share = m["v"] / f["volume_uzs"] * 100
        share_prev = (m["vp"] / prev[m["f"]] * 100) if m["vp"] and prev.get(m["f"]) else None
        markets.append({"name": m["f"], "slug": f["slug"], "my_volume": round(m["v"]), "market_volume": f["volume_uzs"],
                        "share": round(share, 2), "share_prev": round(share_prev, 2) if share_prev else None,
                        "my_growth": growth(m["v"], m["vp"]), "market_growth": f["growth"], "my_buyers": m["b"],
                        "market_buyers": f["buyers"], "rank": None, "unit": f["unit"]})
        rk = rows(f"""with t as (select seller_inn, sum(amount_uzs) s from v_deals where year = {LAST_FULL} and product_family = ? group by 1)
                      select count(*) + 1 r, (select count(*) from t) n from t where s > ?""", m["f"], m["v"])[0]
        markets[-1]["rank"], markets[-1]["competitors"] = rk["r"], rk["n"]
    main = markets[0]["name"] if markets else None
    gaps, ideas = [], []
    if main:
        reg = rows(f"""select region, sum(amount_uzs) v, sum(case when seller_inn = ? then amount_uzs end) mine,
            count(distinct buyer_inn) buyers from v_deals where product_family = ? and year = {LAST_FULL} group by 1""", inn, main)
        tot = sum(r["v"] for r in reg) or 1
        mtot = sum(r["mine"] or 0 for r in reg) or 1
        for r in sorted(reg, key=lambda r: -r["v"]):
            ms, my = r["v"] / tot * 100, (r["mine"] or 0) / mtot * 100
            if r["buyers"] >= K_MIN and ms - my > 3:
                gaps.append({"region": r["region"], "market_share": round(ms, 1), "my_share": round(my, 1), "buyers": r["buyers"]})
        gaps = gaps[:4]
        # where to grow: what my own buyers also buy (cross-sell), ranked by overlap × market growth
        co = rows(f"""with my_b as (select distinct buyer_inn from v_deals where seller_inn = ? and year >= {LAST_FULL - 1})
            select v.product_family f, count(distinct v.buyer_inn) b from v_deals v join my_b using(buyer_inn)
            where v.year >= {LAST_FULL - 1} group by 1""", inn)
        nb = rows(f"select count(distinct buyer_inn) n from v_deals where seller_inn = ? and year >= {LAST_FULL - 1}", inn)[0]["n"] or 1
        mine_set = {m["name"] for m in markets}
        my_ind = fam[main]["industry"] if main in fam else None
        for r in co:
            f = fam.get(r["f"])
            if not f or r["f"] in mine_set or r["b"] < K_MIN:
                continue
            overlap = r["b"] / nb * 100
            g = f["growth"] or 0
            ideas.append({"name": r["f"], "slug": f["slug"], "overlap": round(overlap, 1), "growth": f["growth"],
                          "growth_ytd": f["growth_ytd"], "market_volume": f["volume_uzs"], "sellers": f["sellers"],
                          "top3_share": f["top3_share"], "same_industry": f["industry"] == my_ind,
                          "why": f"{round(overlap)}% ваших покупателей уже покупают это на бирже; рынок {'+' if g >= 0 else ''}{g}% за год, "
                                 f"продавцов всего {f['sellers']}", "_rank": overlap * (1 + max(g, -50) / 100) + (15 if f["industry"] == my_ind else 0)})
        ideas.sort(key=lambda x: -x.pop("_rank"))
        if len(ideas) < 3:
            for f in families():
                if f["industry"] == my_ind and f["name"] not in mine_set and f["name"] not in {i["name"] for i in ideas} and (f["growth"] or 0) > 0:
                    ideas.append({"name": f["name"], "slug": f["slug"], "overlap": 0, "growth": f["growth"], "growth_ytd": f["growth_ytd"],
                                  "market_volume": f["volume_uzs"], "sellers": f["sellers"], "top3_share": f["top3_share"], "same_industry": True,
                                  "why": f"та же отрасль, рынок +{f['growth']}% за год, продавцов {f['sellers']}"})
    return {"markets": markets, "gaps": gaps, "ideas": ideas[:4]}


def _buyer(inn):
    buys = rows(f"""select product_family f, unit, count(*) d, sum(amount_uzs) v, sum(volume) q,
        median(case when volume > 0 then amount_uzs / volume end) my_price, min(deal_date) first
        from v_deals where buyer_inn = ? and year >= {LAST_FULL} group by 1, 2 order by v desc limit 6""", inn)
    out = []
    for b in buys:
        mk = rows(f"""with mine as (select distinct month, year from v_deals where buyer_inn = ? and product_family = ? and year >= {LAST_FULL})
            select median(amount_uzs / volume) p from v_deals join mine using(year, month) where product_family = ? and unit = ? and volume > 0""",
                  inn, b["f"], b["f"], b["unit"])[0]["p"]
        f = by_slug(b["f"]) or {}
        over = round((b["my_price"] / mk - 1) * 100, 1) if mk and b["my_price"] else None
        out.append({"name": b["f"], "slug": f.get("slug"), "deals": b["d"], "volume_uzs": round(b["v"]), "qty": round(b["q"] or 0),
                    "unit": b["unit"], "my_price": round(b["my_price"] or 0), "market_price": round(mk or 0), "overpay_pct": over,
                    "overpay_uzs": round(b["v"] * over / (100 + over)) if over and over > 0 else 0,
                    "sellers": f.get("sellers"), "cheapest_months": cheapest_months(b["f"])})
    return {"purchases": out}


@lru_cache(maxsize=1)
def demos():
    out = []
    s = rows(f"""with t as (select seller_inn, any_value(seller_name) n, sum(amount_uzs) s, count(*) d from v_deals
                 where year = {LAST_FULL} and product_family = 'Мука пшеничная' group by 1), m as (select sum(s) tot from t)
            select seller_inn inn, n name from t, m where s / tot between 0.01 and 0.06 order by d desc limit 1""")
    if s:
        out.append({**s[0], "role": "Мельница: продаёт муку"})
    b = rows(f"""select buyer_inn inn, any_value(buyer_name) name from v_deals where year >= {LAST_FULL} and product_family = 'Цемент'
                 group by 1 having count(*) between 25 and 80 order by count(*) desc limit 1""")
    if b:
        out.append({**b[0], "role": "Стройкомпания: покупает цемент"})
    return out


def overview():
    fam = families()
    tot = rows(f"""select count(*) d, count(distinct buyer_inn) b, count(distinct seller_inn) s, sum(amount_usd) usd,
        avg(case when is_executed then 1.0 else 0 end) e from v_deals where year = {LAST_FULL}""")[0]
    sellers = {r["year"]: r["n"] for r in rows("select year, count(distinct seller_inn) n from v_deals group by 1")}
    small = rows(f"""with b as (select buyer_inn, sum(amount_usd) s from v_deals where year = {LAST_FULL} group by 1)
        select count(*) n, sum(case when s < 50000 then 1 else 0 end) small, sum(case when s < 50000 then s end) / sum(s) small_vol from b""")[0]
    rising = sorted([f for f in fam if f["growth"] is not None and f["volume_usd"] > 3e6], key=lambda f: -f["growth"])[:6]
    concentrated = sorted([f for f in fam if f["volume_usd"] > 3e6], key=lambda f: -f["top3_share"])[:5]
    return {"deals": tot["d"], "buyers": tot["b"], "sellers": tot["s"], "volume_usd": round(tot["usd"]), "exec_rate": round(tot["e"] * 100, 1),
            "sellers_by_year": sellers, "small_buyers": small["small"], "small_buyers_vol_pct": round(small["small_vol"] * 100, 1),
            "families": len(fam), "rising": rising, "concentrated": concentrated, "year": LAST_FULL,
            "source": "Реестр сделок UZEX, 500 000 сделок 03.01.2022–30.10.2026"}


def search(text: str, limit=3):
    t = text.lower()
    hits = []
    for f in families():
        sc = 0
        for w in re.findall(r"[\w'ʻ‘’-]+", t):
            if len(w) < 3 and w not in SYN:
                continue
            if SYN.get(w) == f["name"]:
                sc += 3
            if w in f["name"].lower() or w in f["en"].lower():
                sc += 2
            elif len(w) >= 4 and (f["name"].lower().startswith(w[:4]) or f["en"].lower().startswith(w[:4])):
                sc += 1
        if sc:
            hits.append((sc, f))
    hits.sort(key=lambda x: (-x[0], -x[1]["volume_uzs"]))
    return [f for _, f in hits[:limit]]
