"""Exchange engine: scheduled call auctions (uniform clearing price, price band), two-sided agent mandates,
pooling of small buyers, forward price locks, alerts, and the full physical deal lifecycle."""
import json
import os
import random
import threading
import time
import traceback

import docs
import market
from core import (FEE_BUYER, FEE_CLEARING, FEE_SELLER, INSTRUMENTS, REGIONS, SYS, acct, add_event, balances,
                  broadcast, ensure_accounts, new_keypair, notify, now, post, q, q1, tx, uid)

# Demo clock (seconds). The real exchange runs daily sessions; the demo compresses the cycle so a deal fits in minutes.
EVERY = int(os.environ.get("SESSION_EVERY", 150))
OPEN = int(os.environ.get("SESSION_OPEN", 40))
PAY = int(os.environ.get("PAY_WINDOW", 60))
SHIP = int(os.environ.get("SHIP_DELAY", 25))
SHIP_WINDOW = int(os.environ.get("SHIP_WINDOW", 240))      # time a human seller has to load the truck
TRANSIT = int(os.environ.get("TRANSIT", 90))
ACCEPT = int(os.environ.get("ACCEPT_WINDOW", 240))
WEEK = int(os.environ.get("FORWARD_WEEK_SECS", 120))       # one "forward week" in demo seconds
TOLERANCE = 0.005
# Price band: growth from the start price is capped at 10% for liquefied gas (Competition Committee, since 12.01.2026)
BAND = {"propane": 0.10}

SELLERS = {  # names from the hackathon registry, which is fictional by design (no real companies are implied)
    "cement": [("FICHOʻR STROY OK", "Toshkent shahri"), ("\"Shiqoʻm Qurilish\" MChJ", "Toshkent viloyati")],
    "propane": [("PODIBOʻL PETROL AJ", "Jizzax viloyati"), ("\"ДЕРЎРИЛ ЕНЕРГО\" МЧЖ", "Namangan viloyati")],
    "ai92": [("\"Linom Energo\" MChJ", "Samarqand viloyati"), ("\"Vejut Neft\" OK", "Namangan viloyati")],
    "pp": [("\"Dusan Plast\" MChJ", "Toshkent shahri"), ("\"ҲАРАЙЎМ КИМЁ\" МЧЖ", "Qashqadaryo viloyati")],
    "urea": [("MOʻNIZ KIMYO XK", "Qashqadaryo viloyati"), ("\"Shetoʻzo Industriya\" MChJ", "Toshkent viloyati")],
    "wheat": [("\"Moʻjotat Klaster\" MChJ", "Xorazm viloyati"), ("\"Boqoʻbo Klaster\" MChJ", "Xorazm viloyati")],
    "sugar": [("\"РЎХОК ОЗИҚ-ОВҚАТ\" МЧЖ", "Toshkent shahri"), ("\"ЙЕТИК ФООД\" МЧЖ", "Namangan viloyati")],
    "rebar": [("POʻPILOʻK STEEL MCHJ", "Buxoro viloyati"), ("\"Zasahi Steel\" MChJ", "Namangan viloyati")],
}
BUYERS = [("Toshkent Qurilish Invest", "Toshkent shahri"), ("Andijon Savdo Markazi", "Andijon viloyati"),
          ("Samarqand Agro Trade", "Samarqand viloyati"), ("Fargʻona Plast", "Fargʻona viloyati"),
          ("Namangan Non Kombinati", "Namangan viloyati"), ("Buxoro Yoqilgʻi", "Buxoro viloyati"),
          ("Qarshi Qurilish", "Qashqadaryo viloyati"), ("Navoiy Industrial", "Navoiy viloyati"),
          ("Termiz Logistics", "Surxondaryo viloyati"), ("Urganch Savdo", "Xorazm viloyati")]
SMALL = [("Nonvoyxona «Barakat»", "Namangan viloyati"), ("Nonvoyxona «Oltin Non»", "Namangan viloyati"),
         ("Qurilish usta Akmal", "Toshkent viloyati"), ("Fermer «Bogʻbon»", "Samarqand viloyati"),
         ("Kichik sex «Plast-M»", "Fargʻona viloyati"), ("Shirinlik sexi «Asal»", "Andijon viloyati")]
CARRIERS = ["Yuk Tashuvchi-1 (демо)", "Avto Karvon (демо)", "Ipak Yoʻli Cargo (демо)"]
_demo = {"next_scenario": "normal"}


def set_next_scenario(s: str):
    _demo["next_scenario"] = s


def fmt(n):
    return f"{n:,.0f}".replace(",", " ")


# ------------------------------------------------------------------ seeding
def seed():
    if q1("select 1 from users where role='seller_bot' limit 1"):
        return
    with tx() as c:
        def mk(prefix, name, region, role):
            u = f"bot_{prefix}_{uid('')[1:]}"
            pub, priv = new_keypair()
            c.execute("insert into users(id, name, company, region, status, role, sign_pub, sign_priv, verified_at, "
                      "created_at, inn) values(?,?,?,?,?,?,?,?,?,?,?)",
                      (u, name, name, region, "company", role, pub, priv, now(), now(), str(random.randint(2 * 10**8, 3 * 10**8))))
            ensure_accounts(c, u)
            post(c, SYS["bank"], acct(u, "wallet"), 500_000_000_000, "topup", u, "Стартовый баланс демо-участника")
        for sellers in SELLERS.values():
            for name, region in sellers:
                if not c.execute("select 1 from users where name=? and role='seller_bot'", (name,)).fetchone():
                    mk("s", name, region, "seller_bot")
        for name, region in BUYERS:
            mk("b", name, region, "buyer_bot")
        for name, region in SMALL:
            mk("m", name, region, "small_bot")


def _seller_for(key, n):
    name = SELLERS[key][n % len(SELLERS[key])][0]
    return q1("select id from users where name=? and role='seller_bot'", name)["id"]


# ------------------------------------------------------------------ scheduling, announcements, alerts
def ensure_schedule():
    t = now()
    for i, key in enumerate(INSTRUMENTS):
        last = q1("select opens_at from sessions where instrument=? order by opens_at desc limit 1", key)
        nxt = (last["opens_at"] + EVERY) if last else (t + 20 + i * EVERY / len(INSTRUMENTS))
        while nxt < t + 2.2 * EVERY:
            n = q1("select count(*) n from sessions where instrument=?", key)["n"]
            seller = _seller_for(key, n)
            ins = INSTRUMENTS[key]
            price = market.last_price(key)
            start = int(round(price * random.uniform(0.965, 0.995), -3))
            offered = ins["lot"] * random.randint(6, 14)
            sid = f"S{key[:3].upper()}{int(nxt)}"
            with tx() as c:
                c.execute("insert or ignore into sessions(id, instrument, announce_at, opens_at, closes_at, status, "
                          "seller, offered, start_price) values(?,?,?,?,?,?,?,?,?)",
                          (sid, key, t, nxt, nxt + OPEN, "scheduled", seller, offered, start))
                seller_name = q1("select name from users where id=?", seller)["name"]
                watchers = {m["user_id"] for m in q("select distinct user_id from mandates where instrument=? and "
                                                     "status='active'", key)}
                watchers |= {a["user_id"] for a in q("select user_id from alerts where instrument=? and kind='session' "
                                                     "and active=1", key)}
                for u in watchers:
                    notify(c, u, "schedule", f"Анонс торгов: {ins['name_ru']}",
                           f"{seller_name} выставит {offered} т, старт {fmt(start)} сум/т. Начало в "
                           f"{time.strftime('%H:%M', time.localtime(nxt))}.", f"/market/{key}")
            nxt += EVERY


def remind_upcoming():
    """'Be ready' reminder ~45 s before a session opens (mentor: «пропилен в четверг в 11:00 — будьте готовы»)."""
    t = now()
    for s in q("select * from sessions where status='scheduled' and opens_at between ? and ? and reminded is null",
               t, t + 45):
        ins = INSTRUMENTS[s["instrument"]]
        with tx() as c:
            c.execute("update sessions set reminded=1 where id=?", (s["id"],))
            users = {a["user_id"] for a in q("select user_id from alerts where instrument=? and kind='session' and "
                                             "active=1", s["instrument"])}
            for u in users:
                bal = balances(u)["wallet"]
                need = int(ins["lot"] * s["start_price"] * (ins["deposit"] + FEE_BUYER + FEE_CLEARING))
                ready = "Задатка на минимальный лот хватает." if bal >= need else \
                    f"Пополните кошелёк: на минимальный лот нужно ~{fmt(need)} сум."
                notify(c, u, "alert", f"Через минуту продажа: {ins['name_ru']}",
                       f"Старт {fmt(s['start_price'])} сум/т, {s['offered']} т. {ready}", f"/market/{s['instrument']}")


def check_price_alerts(key, price):
    with tx() as c:
        for a in q("select * from alerts where instrument=? and active=1 and kind in ('below','above')", key):
            hit = (a["kind"] == "below" and price <= a["value"]) or (a["kind"] == "above" and price >= a["value"])
            if hit:
                c.execute("update alerts set active=0, fired_at=? where id=?", (now(), a["id"]))
                notify(c, a["user_id"], "alert", f"Цена {'опустилась' if a['kind'] == 'below' else 'поднялась'}: "
                       f"{INSTRUMENTS[key]['name_ru']}", f"Клиринг {fmt(price)} сум/т (ваш порог {fmt(a['value'])}).",
                       f"/market/{key}")


# ------------------------------------------------------------------ helpers
def _block(c, user, amount, ref, memo):
    post(c, acct(user, "wallet"), acct(user, "blocked"), amount, "block", ref, memo)
    return amount


def _bid_need(qty, price, dep):
    return int(qty * price * dep + qty * price * (FEE_BUYER + FEE_CLEARING))


def _fair(key, cache):
    if key not in cache:
        cache[key] = market.forecast(key, 2)["points"][0]["price"]
    return cache[key]


def _urgency(m):
    total = max(1, m["deadline"] - m["created_at"])
    return min(1.0, max(0.0, 1 - (m["deadline"] - now()) / total))


def _agent_bid(m, s, cache):
    """Buyer agent negotiates: starts near fair value, moves toward the limit as the deadline approaches."""
    if m["strategy"] == "now":
        return m["limit_price"]
    fair = _fair(s["instrument"], cache)
    price = fair * 0.995 + (m["limit_price"] - fair * 0.995) * _urgency(m) ** 1.5
    return int(round(min(m["limit_price"], max(price, s["start_price"])), -3))


def _agent_ask(m, s, cache):
    """Seller agent: asks a bit above fair value, concedes toward the floor as the deadline approaches."""
    if m["strategy"] == "now":
        return m["limit_price"]
    fair = _fair(s["instrument"], cache)
    hi = max(m["limit_price"], fair * 1.01)
    return int(round(max(m["limit_price"], hi - (hi - m["limit_price"]) * _urgency(m) ** 1.5), -3))


# ------------------------------------------------------------------ session open: collect orders
def open_session(s):
    key, ins = s["instrument"], INSTRUMENTS[s["instrument"]]
    cache, pool = {}, []
    with tx() as c:
        c.execute("update sessions set status='open' where id=?", (s["id"],))
        _block(c, s["seller"], int(s["offered"] * s["start_price"] * ins["deposit"]), s["id"], "Гарантийный задаток продавца")
        c.execute("insert into orders(id, session_id, user_id, side, qty, price, status, ts) values(?,?,?,?,?,?,?,?)",
                  (uid("O"), s["id"], s["seller"], "sell", s["offered"], s["start_price"], "open", now()))
        for m in q("select * from mandates where instrument=? and status='active' and side in ('buy','sell')", key):
            left = m["qty"] - m["filled"]
            if left <= 0:
                continue
            if m["deadline"] < now():
                c.execute("update mandates set status='expired' where id=?", (m["id"],))
                notify(c, m["user_id"], "mandate", "Срок поручения истёк",
                       f"{ins['name_ru']}: исполнено {m['filled']} из {m['qty']} т.", "/agent")
                continue
            if m["side"] == "sell":
                if left < ins["lot"]:
                    continue
                ask = _agent_ask(m, s, cache)
                try:
                    _block(c, m["user_id"], int(left * ask * ins["deposit"]), s["id"], "Гарантийный задаток продавца")
                except ValueError:
                    notify(c, m["user_id"], "wallet", "Не хватает средств на гарантийный задаток",
                           f"Для продажи {left} т нужно заблокировать {fmt(left * ask * ins['deposit'])} сум.", "/wallet")
                    continue
                c.execute("insert into orders(id, session_id, user_id, side, qty, price, mandate_id, status, ts) "
                          "values(?,?,?,?,?,?,?,?,?)", (uid("O"), s["id"], m["user_id"], "sell", left, ask, m["id"],
                                                        "open", now()))
                notify(c, m["user_id"], "agent", f"Агент выставил ваш товар: {ins['name_ru']}",
                       f"{left} т по цене от {fmt(ask)} сум/т (ваш минимум {fmt(m['limit_price'])}).", f"/market/{key}")
                continue
            price = _agent_bid(m, s, cache)
            if price < s["start_price"]:
                notify(c, m["user_id"], "agent", f"Агент пропускает сессию: {ins['name_ru']}",
                       f"Старт {fmt(s['start_price'])} выше вашего лимита {fmt(m['limit_price'])} сум/т.", f"/market/{key}")
                continue
            if left < ins["lot"]:
                pool.append((m, left, price))
                continue
            try:
                blk = _block(c, m["user_id"], _bid_need(left, price, ins["deposit"]), s["id"],
                             "Блокировка задатка и сборов под заявку")
            except ValueError:
                notify(c, m["user_id"], "wallet", "Не хватает средств для заявки",
                       f"Агент хотел купить {left} т {ins['name_ru']}, но на кошельке не хватает на задаток.", "/wallet")
                continue
            c.execute("insert into orders(id, session_id, user_id, side, qty, price, mandate_id, status, ts) "
                      "values(?,?,?,?,?,?,?,?,?)", (uid("O"), s["id"], m["user_id"], "buy", left, price, m["id"],
                                                    "open", now()))
            notify(c, m["user_id"], "agent", f"Агент подал заявку: {ins['name_ru']}",
                   f"{left} т по цене до {fmt(price)} сум/т (лимит {fmt(m['limit_price'])}). Заблокировано {fmt(blk)} сум.",
                   f"/market/{key}")
        if random.random() < 0.85:
            for b in random.sample(q("select id from users where role='small_bot'"), k=random.randint(1, 3)):
                pool.append(({"id": None, "user_id": b["id"], "limit_price": 0}, random.randint(2, max(2, ins["lot"] - 2)),
                             int(round(s["start_price"] * random.uniform(1.0, 1.03), -3))))
        if pool:
            qty = sum(x[1] for x in pool)
            if qty >= ins["lot"]:
                pool_id, pool_price = uid("POOL"), min(x[2] for x in pool)
                for m, left, _ in pool:
                    try:
                        _block(c, m["user_id"], _bid_need(left, pool_price, ins["deposit"]), s["id"],
                               "Блокировка задатка под общий лот")
                    except ValueError:
                        continue
                    c.execute("insert into orders(id, session_id, user_id, side, qty, price, mandate_id, pool_id, "
                              "status, ts) values(?,?,?,?,?,?,?,?,?,?)",
                              (uid("O"), s["id"], m["user_id"], "buy", left, pool_price, m["id"], pool_id, "open", now()))
                    if m["id"]:
                        notify(c, m["user_id"], "agent", "Вы в общем лоте",
                               f"{len(pool)} мелких покупателей объединены в лот {qty} т по цене до {fmt(pool_price)} сум/т.",
                               f"/market/{key}")
            else:
                for m, left, _ in pool:
                    if m["id"]:
                        notify(c, m["user_id"], "agent", "Собираем общий лот",
                               f"Набрано {qty} т из минимальных {ins['lot']} т. Агент попробует в следующей сессии.",
                               f"/market/{key}")
    broadcast({"type": "session", "id": s["id"], "status": "open", "instrument": key})


def bot_bids(s):
    key, ins = s["instrument"], INSTRUMENTS[s["instrument"]]
    fair = market.last_price(key)
    with tx() as c:
        for b in random.sample(q("select id from users where role='buyer_bot'"), k=random.randint(1, 4)):
            qty = ins["lot"] * random.randint(1, 4)
            price = int(round(max(s["start_price"], fair * random.uniform(0.975, 1.035)), -3))
            _block(c, b["id"], _bid_need(qty, price, ins["deposit"]), s["id"], "Блокировка под заявку")
            c.execute("insert into orders(id, session_id, user_id, side, qty, price, status, ts) values(?,?,?,?,?,?,?,?)",
                      (uid("O"), s["id"], b["id"], "buy", qty, price, "open", now()))
    broadcast({"type": "book", "session": s["id"], "instrument": key})


# ------------------------------------------------------------------ clearing
def clearing_price(bids, asks, cap=None):
    """Uniform price maximizing matched volume. Excess demand → higher price; excess supply → sellers' ask.
    With a price band the price can't exceed `cap`; bids above it are treated as bids at the cap."""
    if cap:
        bids = [{**b, "price": min(b["price"], cap)} for b in bids]
    prices = sorted({o["price"] for o in bids + asks if not cap or o["price"] <= cap})
    best = None
    for p in prices:
        d = sum(o["qty"] for o in bids if o["price"] >= p)
        s_ = sum(o["qty"] for o in asks if o["price"] <= p)
        v = min(d, s_)
        k = (v, -abs(d - s_), p if d > s_ else -p)
        if v > 0 and (best is None or k > best[0]):
            best = (k, p, d, s_)
    return (best[1], best[0][0], best[2], best[3]) if best else (0, 0, sum(o["qty"] for o in bids), 0)


def clear_session(s):
    key, ins = s["instrument"], INSTRUMENTS[s["instrument"]]
    orders = q("select * from orders where session_id=? and status='open'", s["id"])
    bids = sorted([o for o in orders if o["side"] == "buy"], key=lambda o: (-o["price"], o["ts"]))
    asks = sorted([o for o in orders if o["side"] == "sell"], key=lambda o: (o["price"], o["ts"]))
    band = BAND.get(key)
    cap = int(round(s["start_price"] * (1 + band), -3)) if band else None
    price, volume, demand, supply = clearing_price(bids, asks, cap)
    capped = bool(cap and price == cap and demand > supply)
    with tx() as c:
        # 1) release all bid blocks; deals re-block exactly what they need
        for b in bids:
            post(c, acct(b["user_id"], "blocked"), acct(b["user_id"], "wallet"),
                 min(_bid_need(b["qty"], b["price"], ins["deposit"]), balances(b["user_id"])["blocked"]), "release",
                 s["id"], "Снятие блокировки по заявке")
        # 2) match: asks by price/time, bids by price/time (bids above cap are equal at the cap → time priority)
        eff = lambda b: min(b["price"], cap) if cap else b["price"]
        live_bids = [dict(b, left=b["qty"]) for b in sorted(bids, key=lambda o: (-eff(o), o["ts"])) if price and eff(b) >= price]
        live_asks = [dict(a, left=a["qty"]) for a in asks if price and a["price"] <= price]
        remaining, fills = volume, {}
        for a in live_asks:
            for b in live_bids:
                if remaining <= 0 or a["left"] <= 0:
                    break
                f = min(a["left"], b["left"], remaining)
                if f <= 0:
                    continue
                a["left"] -= f; b["left"] -= f; remaining -= f
                fills.setdefault(b["id"], 0)
                fills[b["id"]] += f
                _create_deal(c, s, a, b, f, price)
        # 3) mark orders, release unsold seller deposits
        for b in bids:
            f = fills.get(b["id"], 0)
            c.execute("update orders set status=?, filled=? where id=?", ("filled" if f else "unfilled", f, b["id"]))
            if not f and b["mandate_id"]:
                notify(c, b["user_id"], "agent", f"Заявка не исполнена: {ins['name_ru']}",
                       (f"Цена сессии {fmt(price)} выше заявки агента {fmt(b['price'])}. Агент повторит ближе к лимиту."
                        if price else "Предложения не хватило.") if not capped else
                       "Спрос превысил предложение при ценовом коридоре — товар распределён по времени заявок.",
                       f"/market/{key}")
        for a in asks:
            sold = sum(x["qty"] - x["left"] for x in live_asks if x["id"] == a["id"])
            c.execute("update orders set status=?, filled=? where id=?", ("filled" if sold else "unfilled", sold, a["id"]))
            post(c, acct(a["user_id"], "blocked"), acct(a["user_id"], "wallet"),
                 int((a["qty"] - sold) * a["price"] * ins["deposit"]), "release", s["id"],
                 "Возврат задатка за непроданный объём")
            if a["mandate_id"] and not sold:
                notify(c, a["user_id"], "agent", f"Товар не продан в этой сессии: {ins['name_ru']}",
                       f"Цена клиринга {fmt(price)} ниже вашей цены {fmt(a['price'])}. Агент снизит цену ближе к сроку."
                       if price else "Покупателей не нашлось.", f"/market/{key}")
        explain = {"supply": supply or s["offered"], "demand": demand, "bidders": len({b["user_id"] for b in bids}),
                   "sellers": len({a["user_id"] for a in asks}), "pools": len({b["pool_id"] for b in bids if b["pool_id"]}),
                   "start": s["start_price"], "price": price, "matched": volume, "cap": cap, "capped": capped}
        c.execute("update sessions set status='cleared', clearing_price=?, matched=?, demand=?, bidders=?, explain=? "
                  "where id=?", (price, volume, demand, explain["bidders"], json.dumps(explain, ensure_ascii=False), s["id"]))
    if price:
        check_price_alerts(key, price)
    broadcast({"type": "session", "id": s["id"], "status": "cleared", "instrument": key, "price": price})


def _scenario_for(buyer):
    if not buyer.startswith("bot_"):
        sc, _demo["next_scenario"] = _demo["next_scenario"], "normal"
        return sc
    return random.choice(["short_loading", "transit_loss", "no_shipment"]) if random.random() < 0.03 else "normal"


def _create_deal(c, s, ask, bid, qty, price, forward=None):
    ins = INSTRUMENTS[s["instrument"]]
    did = uid("D")
    amount = qty * price
    dep_b, dep_s = int(amount * ins["deposit"]), int(qty * ask["price"] * ins["deposit"])
    post(c, acct(bid["user_id"], "wallet"), acct(bid["user_id"], "blocked"), dep_b, "deposit", did, "Задаток покупателя по сделке")
    pay_due = now() + PAY if not forward else forward["delivery_at"] + PAY
    c.execute("insert into deals(id, session_id, instrument, buyer, seller, qty, price, amount, deposit_buyer, "
              "deposit_seller, status, pool_id, mandate_id, created_at, pay_due, flags) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (did, s["id"], s["instrument"], bid["user_id"], ask["user_id"], qty, price, amount, dep_b, dep_s,
               "forward" if forward else "signed", bid.get("pool_id"), bid.get("mandate_id") or ask.get("mandate_id"),
               now(), pay_due, json.dumps({"scenario": _scenario_for(bid["user_id"]), "seller_mandate": ask.get("mandate_id"),
                                           **({"forward": forward} if forward else {})})))
    add_event(c, did, "matched", "exchange", {"session": s["id"], "qty": qty, "price": price, "amount": amount,
                                              "pool": bid.get("pool_id"), "forward": bool(forward)})
    docs.contract(c, did)
    for side, o in (("buy", bid), ("sell", ask)):
        if o.get("mandate_id"):
            c.execute("update mandates set filled=filled+?, spent=spent+? where id=?", (qty, amount, o["mandate_id"]))
            m = q1("select * from mandates where id=?", o["mandate_id"])
            if m and m["filled"] >= m["qty"]:
                c.execute("update mandates set status='filled' where id=?", (m["id"],))
            notify(c, o["user_id"], "deal", f"{'Куплено' if side == 'buy' else 'Продано'}: {qty} т {ins['name_ru']}",
                   f"Цена {fmt(price)} сум/т, сумма {fmt(amount)} сум. Договор подписан агентом по вашему поручению.",
                   f"/deals/{did}")
    return did


# ------------------------------------------------------------------ forward price lock («ценовой щит»)
def forward_quote(key, qty, weeks):
    f = market.forecast(key, max(weeks, 1))
    pt = f["points"][min(weeks, len(f["points"])) - 1]
    premium = min(0.04, f["mape"] / 100 * 0.5)
    price = int(round(pt["price"] * (1 + premium), -3))
    return {"instrument": key, "qty": qty, "weeks": weeks, "price": price, "forecast": pt["price"], "low": pt["low"],
            "high": pt["high"], "premium_pct": round(premium * 100, 1), "deposit_pct": 15,
            "deposit": int(qty * price * 0.15), "delivery_week": pt["time"],
            "explain": f"Цена = прогноз на неделю {pt['time']} ({fmt(pt['price'])}) + премия продавца за риск "
                       f"{round(premium * 100, 1)}%. Если рынок вырастет выше — вы всё равно платите {fmt(price)}."}


def create_forward(user_id, key, qty, weeks):
    ins = INSTRUMENTS[key]
    quote = forward_quote(key, qty, weeks)
    seller = _seller_for(key, random.randint(0, 9))
    sid = f"F{key[:3].upper()}{int(now())}"
    delivery_at = now() + weeks * WEEK
    with tx() as c:
        c.execute("insert into sessions(id, instrument, announce_at, opens_at, closes_at, status, seller, offered, "
                  "start_price, clearing_price, matched, explain) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, key, now(), now(), now(), "forward", seller, qty, quote["price"], quote["price"], qty,
                   json.dumps({"forward": True, **quote}, ensure_ascii=False)))
        extra = int(qty * quote["price"] * 0.05)   # forward deposit 15% = 10% standard + 5% extra guarantee
        post(c, acct(user_id, "wallet"), acct(user_id, "blocked"), extra, "deposit", sid, "Доп. гарантия форварда 5%")
        post(c, acct(seller, "wallet"), acct(seller, "blocked"), int(qty * quote["price"] * ins["deposit"]), "block", sid,
             "Гарантийный задаток продавца по форварду")
        did = _create_deal(c, {"id": sid, "instrument": key}, {"user_id": seller, "price": quote["price"]},
                           {"user_id": user_id}, qty, quote["price"],
                           forward={"delivery_at": delivery_at, "weeks": weeks, "extra": extra, **quote})
        notify(c, user_id, "deal", f"Цена зафиксирована: {qty} т {ins['name_ru']}",
               f"{fmt(quote['price'])} сум/т с поставкой через {weeks} нед. Рынок может меняться — ваша цена нет.",
               f"/deals/{did}")
    return did


# ------------------------------------------------------------------ deal lifecycle
def _gps(a_region, b_region, frac):
    a, b = REGIONS.get(a_region, (41.3, 69.3)), REGIONS.get(b_region, (41.3, 69.3))
    return [round(a[0] + (b[0] - a[0]) * frac, 4), round(a[1] + (b[1] - a[1]) * frac, 4)]


def tick_deals():
    t = now()
    for d in q("select * from deals where status in ('forward','signed','paid','in_transit','delivered')"):
        try:
            _advance(d, t)
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def _human(uid_):
    return not uid_.startswith("bot_")


def load(deal_id, qty, truck, seal, actor, evidence=None):
    """Seller-side loading (human seller confirms in the app; bots automatically)."""
    d = q1("select * from deals where id=?", deal_id)
    if not d or d["status"] != "paid":
        return {"error": "Сделка не ожидает отгрузки"}
    s, b = q1("select * from users where id=?", d["seller"]), q1("select * from users where id=?", d["buyer"])
    with tx() as c:
        c.execute("update deals set status='in_transit', loaded_qty=?, carrier=?, truck=?, seal=?, deliver_eta=? where id=?",
                  (qty, random.choice(CARRIERS), truck, seal, now() + TRANSIT, deal_id))
        add_event(c, deal_id, "loaded", actor, {"weighbridge_qty": qty, "contract_qty": d["qty"], "truck": truck, "seal": seal,
                                                "gps": _gps(s["region"], b["region"], 0),
                                                "source": "весы продавца + фото пломбы", **(evidence or {})})
        docs.ttn(c, deal_id)
        notify(c, d["buyer"], "deal", "Товар отгружен",
               f"{qty} т, машина {truck}, пломба {seal}. Следите за машиной на карте.", f"/deals/{deal_id}")
    return {"status": "in_transit"}


def _advance(d, t):
    flags = json.loads(d["flags"] or "{}")
    scenario = flags.get("scenario", "normal")
    buyer = q1("select * from users where id=?", d["buyer"])
    seller = q1("select * from users where id=?", d["seller"])
    if d["status"] == "forward":
        if t >= flags["forward"]["delivery_at"]:
            with tx() as c:
                post(c, acct(d["buyer"], "blocked"), acct(d["buyer"], "wallet"), flags["forward"]["extra"], "release",
                     d["id"], "Возврат доп. гарантии форварда")
                c.execute("update deals set status='signed', pay_due=? where id=?", (t + PAY, d["id"]))
                add_event(c, d["id"], "forward_due", "exchange", {"price": d["price"], "spot": market.last_price(d["instrument"])})
                spot = market.last_price(d["instrument"])
                notify(c, d["buyer"], "deal", "Наступил срок поставки по зафиксированной цене",
                       f"Ваша цена {fmt(d['price'])}, рынок сейчас {fmt(spot)} сум/т — "
                       f"{'вы экономите ' + fmt((spot - d['price']) * d['qty']) + ' сум' if spot > d['price'] else 'рынок ниже, но цена была гарантирована'}.",
                       f"/deals/{d['id']}")
        return
    if d["status"] == "signed":
        rest, fees = d["amount"] - d["deposit_buyer"], int(d["amount"] * (FEE_BUYER + FEE_CLEARING))
        if balances(d["buyer"])["wallet"] >= rest + fees:
            with tx() as c:
                post(c, acct(d["buyer"], "wallet"), SYS["escrow"], rest, "payment", d["id"], "Оплата остатка в сейф биржи")
                post(c, acct(d["buyer"], "blocked"), SYS["escrow"], d["deposit_buyer"], "payment", d["id"], "Задаток зачтён в оплату")
                post(c, acct(d["buyer"], "wallet"), SYS["fees"], int(d["amount"] * FEE_BUYER), "fee", d["id"], "Биржевой сбор покупателя 0,13%")
                post(c, acct(d["buyer"], "wallet"), SYS["clearing"], int(d["amount"] * FEE_CLEARING), "fee", d["id"], "Клиринговый сбор 0,05%")
                ship_due = t + (SHIP_WINDOW if _human(d["seller"]) else SHIP * 3)
                c.execute("update deals set status='paid', ship_due=? where id=?", (ship_due, d["id"]))
                add_event(c, d["id"], "paid", d["buyer"], {"amount": d["amount"], "escrow": True})
                docs.invoice(c, d["id"])
                notify(c, d["buyer"], "deal", "Оплачено, деньги в сейфе биржи",
                       f"Продавец получит {fmt(d['amount'])} сум только после вашей приёмки.", f"/deals/{d['id']}")
                notify(c, d["seller"], "deal", "Покупатель оплатил — отгружайте",
                       f"Деньги {fmt(d['amount'])} сум в сейфе. Срок отгрузки до {time.strftime('%H:%M', time.localtime(ship_due))}.",
                       f"/deals/{d['id']}")
        elif t > d["pay_due"]:
            with tx() as c:
                post(c, acct(d["buyer"], "blocked"), acct(d["seller"], "wallet"), d["deposit_buyer"], "penalty", d["id"],
                     "Задаток покупателя переходит продавцу (неоплата, п.170 Правил; ст.312 ГК)")
                post(c, acct(d["seller"], "blocked"), acct(d["seller"], "wallet"), d["deposit_seller"], "release", d["id"],
                     "Возврат задатка продавца")
                c.execute("update deals set status='annulled' where id=?", (d["id"],))
                add_event(c, d["id"], "annulled_nonpayment", "clearing", {"deposit_to_seller": d["deposit_buyer"]})
                for u in (d["buyer"], d["seller"]):
                    notify(c, u, "deal", "Сделка аннулирована: нет оплаты",
                           f"Задаток покупателя {fmt(d['deposit_buyer'])} сум перешёл продавцу.", f"/deals/{d['id']}")
        elif t > d["pay_due"] - PAY / 2 and not flags.get("pay_warned"):
            with tx() as c:
                flags["pay_warned"] = True
                c.execute("update deals set flags=? where id=?", (json.dumps(flags), d["id"]))
                notify(c, d["buyer"], "deal", "Пополните кошелёк для оплаты",
                       f"Иначе сделка будет аннулирована и задаток {fmt(d['deposit_buyer'])} сум уйдёт продавцу.", "/wallet")
        return
    if d["status"] == "paid":
        if _human(d["seller"]):
            if t > d["ship_due"]:
                import arbitration
                with tx() as c:
                    c.execute("update deals set status='disputed' where id=?", (d["id"],))
                    add_event(c, d["id"], "ship_deadline_missed", "exchange", {"ship_due": d["ship_due"]})
                    arbitration.open_dispute(c, d["id"], "system", "non_delivery", "Продавец не отгрузил товар в срок")
            elif t > d["ship_due"] - SHIP_WINDOW / 3 and not flags.get("ship_warned"):
                with tx() as c:
                    flags["ship_warned"] = True
                    c.execute("update deals set flags=? where id=?", (json.dumps(flags), d["id"]))
                    notify(c, d["seller"], "deal", "Срок отгрузки скоро истекает",
                           "Без отгрузки ваш задаток уйдёт покупателю (п.171 Правил, ст.25 Закона №670-I).", f"/deals/{d['id']}")
            return
        if t > (d["ship_due"] or 0) - SHIP * 2:
            if scenario == "no_shipment":
                if t > d["ship_due"]:
                    import arbitration
                    with tx() as c:
                        c.execute("update deals set status='disputed' where id=?", (d["id"],))
                        add_event(c, d["id"], "ship_deadline_missed", "exchange", {"ship_due": d["ship_due"]})
                        arbitration.open_dispute(c, d["id"], "system", "non_delivery", "Продавец не отгрузил товар в срок")
                return
            qty = d["qty"] if scenario != "short_loading" else round(d["qty"] * random.uniform(0.9, 0.95), 2)
            truck = f"{random.choice(['01', '10', '25', '30', '40', '50', '60', '70', '75', '80', '85', '90', '95'])} " \
                    f"{random.choice('ABDEFHKLMNSTXYZ')}{random.randint(100, 999)}{random.choice(['AA', 'BA', 'CA'])}"
            load(d["id"], qty, truck, f"UZX-{random.randint(100000, 999999)}", d["seller"])
        return
    if d["status"] == "in_transit":
        frac = min(1, (t - (d["deliver_eta"] - TRANSIT)) / TRANSIT)
        with tx() as c:
            c.execute("update deals set gps=? where id=?", (json.dumps(_gps(seller["region"], buyer["region"], frac)), d["id"]))
            if scenario == "transit_loss" and frac > 0.5 and not flags.get("stop"):
                flags["stop"] = True
                c.execute("update deals set flags=? where id=?", (json.dumps(flags), d["id"]))
                add_event(c, d["id"], "gps_anomaly", "telematics", {"gps": _gps(seller["region"], buyer["region"], frac),
                                                                    "stop_minutes": 38, "note": "Незапланированная остановка вне маршрута"})
            if t >= d["deliver_eta"]:
                c.execute("update deals set status='delivered', accept_due=? where id=?", (t + ACCEPT, d["id"]))
                seal_ok = scenario != "transit_loss"
                add_event(c, d["id"], "arrived", "telematics", {
                    "gps": _gps(seller["region"], buyer["region"], 1), "seal_intact": seal_ok,
                    "seal_seen": d["seal"] if seal_ok else f"UZX-{random.randint(100000, 999999)}"})
                notify(c, d["buyer"], "deal", "Машина прибыла — проверьте вес",
                       f"Сфотографируйте весовой талон, агент сверит его с договором. Окно приёмки {ACCEPT // 60} мин.",
                       f"/deals/{d['id']}")
        return
    if d["status"] == "delivered":
        if not _human(d["buyer"]):
            actual = d["loaded_qty"] if scenario != "transit_loss" else round(d["loaded_qty"] * 0.94, 2)
            receive(d["id"], actual, "bot")
        elif t > d["accept_due"]:
            receive(d["id"], None, "timeout")
        elif t > d["accept_due"] - ACCEPT / 3 and not flags.get("acc_warned"):
            with tx() as c:
                flags["acc_warned"] = True
                c.execute("update deals set flags=? where id=?", (json.dumps(flags), d["id"]))
                notify(c, d["buyer"], "deal", "Окно приёмки заканчивается",
                       "Если не заявить замечания, товар будет считаться принятым (Правила UzEx, ред. 01.06.2026: 6 рабочих часов на замечания).", f"/deals/{d['id']}")


def receive(deal_id: str, weight, source: str, evidence: dict | None = None):
    import arbitration
    d = q1("select * from deals where id=?", deal_id)
    if not d or d["status"] != "delivered":
        return {"error": "Сделка не ожидает приёмки"}
    with tx() as c:
        if weight is None:
            weight = d["loaded_qty"]
            add_event(c, deal_id, "auto_accepted", "exchange", {"reason": "окно замечаний истекло (Правила UzEx, ред. 01.06.2026)"})
        add_event(c, deal_id, "unloaded", d["buyer"], {"weighbridge_qty": weight, "source": source, **(evidence or {})})
        c.execute("update deals set delivered_qty=? where id=?", (weight, deal_id))
        if weight < d["qty"] * (1 - TOLERANCE):
            c.execute("update deals set status='disputed' where id=?", (deal_id,))
            dsp = arbitration.open_dispute(c, deal_id, d["buyer"], "short_weight", f"Принято {weight} т вместо {d['qty']} т")
            return {"status": "disputed", "dispute": dsp}
        _settle(c, d)
    return {"status": "settled"}


def withhold_self_employed(c, d, amount):
    """Self-employed sellers pay 1% turnover tax; a legal-entity buyer withholds it as tax agent (Tax Code, 2026 regime)."""
    st = q1("select status from users where id=?", d["seller"])
    if st and st["status"] == "self_employed":
        post(c, acct(d["seller"], "wallet"), "sys:tax", int(amount * 0.01), "tax", d["id"],
             "Налог самозанятого 1% с оборота (удержан налоговым агентом)")


def _settle(c, d):
    post(c, SYS["escrow"], acct(d["seller"], "wallet"), d["amount"], "settlement", d["id"], "Оплата продавцу из сейфа")
    withhold_self_employed(c, d, d["amount"])
    post(c, acct(d["seller"], "wallet"), SYS["fees"], int(d["amount"] * FEE_SELLER), "fee", d["id"], "Биржевой сбор продавца 0,05%")
    post(c, acct(d["seller"], "wallet"), SYS["clearing"], int(d["amount"] * FEE_CLEARING), "fee", d["id"], "Клиринговый сбор 0,05%")
    post(c, acct(d["seller"], "blocked"), acct(d["seller"], "wallet"), d["deposit_seller"], "release", d["id"],
         "Возврат гарантийного задатка продавца")
    c.execute("update deals set status='settled' where id=?", (d["id"],))
    add_event(c, d["id"], "settled", "clearing", {"to_seller": d["amount"] - int(d["amount"] * (FEE_SELLER + FEE_CLEARING))})
    docs.acceptance(c, d["id"])
    for u in (d["buyer"], d["seller"]):
        notify(c, u, "deal", "Сделка завершена", "Товар принят, продавец получил оплату. Документы готовы.", f"/deals/{d['id']}")


# ------------------------------------------------------------------ main loop
_started = False


def loop():
    bot_rounds = {}
    while True:
        try:
            ensure_schedule()
            remind_upcoming()
            t = now()
            for s in q("select * from sessions where status='scheduled' and opens_at<=?", t):
                open_session(s)
            for s in q("select * from sessions where status='open'"):
                k = s["id"]
                if t >= s["closes_at"]:
                    clear_session(s)
                elif bot_rounds.get(k, 0) < 2 and t > s["opens_at"] + bot_rounds.get(k, 0) * OPEN / 2 + 3:
                    bot_bids(s)
                    bot_rounds[k] = bot_rounds.get(k, 0) + 1
            tick_deals()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        time.sleep(1)


def start():
    global _started
    if _started:
        return
    _started = True
    seed()
    threading.Thread(target=loop, daemon=True, name="engine").start()
