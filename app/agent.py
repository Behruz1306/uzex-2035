"""Personal AI agent: understands intent, explains the market, drafts mandates, remembers the user."""
import json
import os
import re
import threading
import time

import anthropic
import duckdb

import arbitration
import market
from core import HISTORY_DB, INSTRUMENTS, balances, now, q, q1, tx, uid

MODEL = os.environ.get("UZEX_MODEL", "claude-sonnet-5-5")
_client = None
_local = threading.local()


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def fmt(n):
    return f"{n:,.0f}".replace(",", " ")


# ------------------------------------------------------------------ tools
def t_market(user, instrument=None):
    keys = [instrument] if instrument in INSTRUMENTS else list(INSTRUMENTS)
    out = []
    for k in keys:
        c = market.candles(k)
        cur = market.last_price(k)
        wk = c[-5]["vwap"] if len(c) > 5 else cur
        nxt = q1("select * from sessions where instrument=? and status in ('scheduled','open') order by opens_at limit 1", k)
        out.append({"instrument": k, "name": INSTRUMENTS[k]["name_ru"], "unit": "т", "price": cur,
                    "change_4w_pct": round(100 * (cur - wk) / wk, 1), "min_lot_t": INSTRUMENTS[k]["lot"],
                    "next_session": nxt and {"opens_at": time.strftime("%H:%M:%S", time.localtime(nxt["opens_at"])),
                                             "offered_t": nxt["offered"], "start_price": nxt["start_price"],
                                             "status": nxt["status"]}})
    return {"instruments": out, "price_note": "сум за тонну, последняя цена клиринга или средневзвешенная за неделю"}


def t_recommend(user, instrument, side="buy", horizon_weeks=6):
    if instrument not in INSTRUMENTS:
        return {"error": f"instrument must be one of {list(INSTRUMENTS)}"}
    return market.recommend(instrument, side, int(horizon_weeks))


def t_explain(user, instrument):
    s = q("select * from sessions where instrument=? and status='cleared' order by closes_at desc limit 3", instrument)
    return {"last_sessions": [{"time": time.strftime("%H:%M", time.localtime(x["closes_at"])), "start": x["start_price"],
                               "clearing_price": x["clearing_price"], "offered_t": x["offered"], "matched_t": x["matched"],
                               **json.loads(x["explain"] or "{}")} for x in s]} or {"note": "сессий ещё не было"}


def t_calendar(user, instrument=None):
    rows = q("select s.*, u.name seller_name from sessions s join users u on u.id=s.seller where s.status in "
             "('scheduled','open') " + ("and instrument=? " if instrument else "") + "order by opens_at limit 12",
             *([instrument] if instrument else []))
    return {"upcoming": [{"instrument": r["instrument"], "name": INSTRUMENTS[r["instrument"]]["name_ru"],
                          "seller": r["seller_name"], "offered_t": r["offered"], "start_price": r["start_price"],
                          "opens_at": time.strftime("%H:%M:%S", time.localtime(r["opens_at"])), "status": r["status"]}
                         for r in rows]}


def t_propose(user, side, instrument, qty, limit_price, deadline_days=7, strategy="smart", note=""):
    if instrument not in INSTRUMENTS:
        return {"error": f"instrument must be one of {list(INSTRUMENTS)}"}
    if side not in ("buy", "sell"):
        return {"error": "side must be buy or sell"}
    qty, limit_price = int(qty), int(limit_price)
    if qty <= 0 or limit_price <= 0:
        return {"error": "qty and limit_price must be positive"}
    mid = uid("M")
    deadline = now() + float(deadline_days) * 86400
    with tx() as c:
        c.execute("insert into mandates(id, user_id, side, instrument, qty, limit_price, deadline, strategy, status, "
                  "confirm_above, note, created_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (mid, user["id"], side, instrument, qty, limit_price, deadline, strategy, "draft",
                   int(qty * limit_price), note, now()))
    ins = INSTRUMENTS[instrument]
    dep = int(qty * limit_price * ins["deposit"])
    if side == "sell" and qty < ins["lot"]:
        with tx() as c:
            c.execute("delete from mandates where id=?", (mid,))
        return {"error": f"Минимальная партия для продажи — {ins['lot']} т"}
    return {"mandate_id": mid, "card": True, "side": side, "instrument": instrument, "name": ins["name_ru"], "qty": qty,
            "limit_price": limit_price, "max_total": qty * limit_price, "deposit_estimate": dep,
            "strategy": strategy, "deadline_days": deadline_days, "pooled": qty < ins["lot"], "min_lot": ins["lot"],
            "wallet": balances(user["id"]),
            "status": "draft — пользователь должен подтвердить PIN-кодом в карточке"}


def t_mandates(user):
    rows = q("select * from mandates where user_id=? and status!='draft' order by created_at desc limit 10", user["id"])
    return {"mandates": [{"id": r["id"], "instrument": r["instrument"], "qty": r["qty"], "filled": r["filled"],
                          "limit_price": r["limit_price"], "status": r["status"], "strategy": r["strategy"],
                          "avg_price": round(r["spent"] / r["filled"]) if r["filled"] else None} for r in rows]}


def t_cancel(user, mandate_id):
    with tx() as c:
        n = c.execute("update mandates set status='cancelled' where id=? and user_id=? and status in ('active','draft')",
                      (mandate_id, user["id"])).rowcount
    return {"cancelled": bool(n)}


def t_deals(user, deal_id=None):
    if deal_id:
        d = q1("select * from deals where id=? and (buyer=? or seller=?)", deal_id, user["id"], user["id"])
        if not d:
            return {"error": "сделка не найдена"}
        ev = q("select ts, type, payload from events where deal_id=? order by id", deal_id)
        return {"deal": d, "events": [{"time": time.strftime("%H:%M:%S", time.localtime(e["ts"])), "type": e["type"],
                                       "data": json.loads(e["payload"])} for e in ev]}
    rows = q("select id, instrument, qty, price, amount, status, created_at from deals where buyer=? or seller=? "
             "order by created_at desc limit 10", user["id"], user["id"])
    return {"deals": rows}


def t_wallet(user):
    return balances(user["id"])


def t_remember(user, fact, kind="preference"):
    with tx() as c:
        c.execute("insert into memory(user_id, kind, text, created_at) values(?,?,?,?)", (user["id"], kind, fact[:300], now()))
    return {"saved": True}


_FORBID = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|copy|export|import|install|load|pragma|set|"
                     r"call|read_\w+|glob)\b", re.I)


def t_registry(user, sql):
    s = sql.strip().rstrip(";")
    if ";" in s or not re.match(r"^\s*(select|with)\b", s, re.I) or _FORBID.search(s):
        return {"error": "только один SELECT/WITH"}
    con = getattr(_local, "duck", None) or duckdb.connect(str(HISTORY_DB), read_only=True)
    _local.duck = con
    try:
        cur = con.execute(s)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(41)
        return {"columns": cols, "rows": [[str(v) if not isinstance(v, (int, float)) else round(v, 2) for v in r]
                                          for r in rows[:40]], "truncated": len(rows) > 40}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:500]}


def t_legal(user, topic):
    base = arbitration.legal_base()
    return {"norms": base.get("norms", [])[:15], "cases": base.get("cases", [])[:6],
            "platform_rules": [
                "Неоплата в срок: задаток покупателя переходит продавцу, сделка аннулируется (п.170 Правил UzEx).",
                "Неотгрузка: задаток продавца переходит покупателю; на платформе это делается автоматически по цепочке "
                "доказательств (п.171 Правил — через Арбитражную комиссию).",
                "Приёмка: допуск по весу ±0,5%; расхождение сверх допуска автоматически открывает спор.",
                "Потеря в пути при нарушенной пломбе или отклонении маршрута — ответственность перевозчика.",
                "Решение ИИ-арбитра — предложение; несогласная сторона обращается в Арбитражную комиссию биржи, "
                "затем в экономический суд."]}


def t_dispute(user, deal_id, text):
    d = q1("select * from deals where id=? and buyer=?", deal_id, user["id"])
    if not d:
        return {"error": "сделка не найдена"}
    if d["dispute_id"]:
        return {"error": "спор уже открыт", "dispute": d["dispute_id"]}
    with tx() as c:
        did = arbitration.open_dispute(c, deal_id, user["id"], "short_weight" if d["status"] == "delivered" else "other",
                                       text)
    return {"dispute": did}


def t_alert(user, instrument, kind="session", value=0):
    if instrument not in INSTRUMENTS or kind not in ("session", "below", "above"):
        return {"error": "instrument/kind"}
    with tx() as c:
        c.execute("insert into alerts(user_id, instrument, kind, value, created_at) values(?,?,?,?,?)",
                  (user["id"], instrument, kind, int(value or 0), now()))
    return {"ok": True, "note": {"session": "уведомлю при анонсе и за минуту до начала продаж",
                                 "below": "уведомлю, когда цена клиринга опустится до порога",
                                 "above": "уведомлю, когда цена клиринга поднимется до порога"}[kind]}


def t_seasonality(user, instrument):
    return market.seasonality(instrument) if instrument in INSTRUMENTS else {"error": "instrument"}


def t_lock_quote(user, instrument, qty, weeks=4):
    import engine
    if instrument not in INSTRUMENTS:
        return {"error": "instrument"}
    qte = engine.forward_quote(instrument, int(qty), max(1, min(8, int(weeks))))
    return {"forward_card": True, "name": INSTRUMENTS[instrument]["name_ru"], **qte,
            "status": "котировка — пользователь фиксирует цену PIN-кодом в карточке"}


TOOLS = [
    ("market", t_market, "Текущие цены, изменение за 4 недели, минимальный лот и ближайшая торговая сессия.",
     {"instrument": {"type": "string", "enum": list(INSTRUMENTS)}}, []),
    ("recommend", t_recommend, "Прогноз и рекомендация «покупать сейчас или ждать» с объяснением и точностью модели.",
     {"instrument": {"type": "string", "enum": list(INSTRUMENTS)}, "side": {"type": "string", "enum": ["buy", "sell"]},
      "horizon_weeks": {"type": "integer"}}, ["instrument"]),
    ("explain_price", t_explain, "Почему сложилась цена в последних сессиях: спрос, предложение, участники, общие лоты.",
     {"instrument": {"type": "string", "enum": list(INSTRUMENTS)}}, ["instrument"]),
    ("calendar", t_calendar, "Ближайшие торговые сессии: кто продаёт, сколько, стартовая цена, время начала.",
     {"instrument": {"type": "string", "enum": list(INSTRUMENTS)}}, []),
    ("propose_mandate", t_propose, "Создать ЧЕРНОВИК поручения агенту купить (side=buy, limit_price = цена не выше) или продать (side=sell, limit_price = цена не ниже; партия не меньше лота). Пользователь подтверждает его "
     "PIN-кодом в карточке; без подтверждения агент ничего не покупает. strategy: smart — агент торгуется и ждёт выгодную "
     "цену до срока; now — купить на ближайшей сессии по цене до лимита; alert — только уведомлять.",
     {"side": {"type": "string", "enum": ["buy", "sell"]}, "instrument": {"type": "string", "enum": list(INSTRUMENTS)},
      "qty": {"type": "integer", "description": "тонн"}, "limit_price": {"type": "integer", "description": "сум за тонну"},
      "deadline_days": {"type": "number"}, "strategy": {"type": "string", "enum": ["smart", "now", "alert"]},
      "note": {"type": "string"}}, ["side", "instrument", "qty", "limit_price"]),
    ("set_alert", t_alert, "Подписка: kind=session — сообщать об анонсе и за минуту до продаж товара (например, "
     "пропилен/полипропилен открывается в 11:00 — будьте готовы); below/above — когда цена клиринга пересечёт value (сум/т).",
     {"instrument": {"type": "string", "enum": list(INSTRUMENTS)}, "kind": {"type": "string", "enum": ["session", "below", "above"]},
      "value": {"type": "integer"}}, ["instrument", "kind"]),
    ("seasonality", t_seasonality, "В какие месяцы товар исторически дешевле/дороже (реальные котировки UZEX 2024–2026).",
     {"instrument": {"type": "string", "enum": list(INSTRUMENTS)}}, ["instrument"]),
    ("price_lock_quote", t_lock_quote, "Ценовой щит: котировка форварда — зафиксировать цену сейчас с поставкой через "
     "N недель (1–8). Показывает цену, премию, задаток 15%. Фиксирует пользователь PIN-кодом в карточке.",
     {"instrument": {"type": "string", "enum": list(INSTRUMENTS)}, "qty": {"type": "integer"}, "weeks": {"type": "integer"}},
     ["instrument", "qty"]),
    ("my_mandates", t_mandates, "Активные и прошлые мандаты пользователя.", {}, []),
    ("cancel_mandate", t_cancel, "Отменить мандат.", {"mandate_id": {"type": "string"}}, ["mandate_id"]),
    ("my_deals", t_deals, "Сделки пользователя; с deal_id — подробности и цепочка событий.",
     {"deal_id": {"type": "string"}}, []),
    ("wallet", t_wallet, "Баланс кошелька: доступно и заблокировано (задатки).", {}, []),
    ("remember", t_remember, "Запомнить устойчивый факт о пользователе (товары, объёмы, регион, бюджет, отношение к "
     "риску, как предпочитает общаться). Вызывай, когда узнаёшь что-то новое и полезное надолго.",
     {"fact": {"type": "string"}, "kind": {"type": "string", "enum": ["preference", "fact", "feedback"]}}, ["fact"]),
    ("registry_query", t_registry, "SQL (DuckDB, только чтение) к реестру 500 000 сделок 2022–2026: представление "
     "v_deals(deal_date, year, month, product_family, brand, region, volume, unit, amount_uzs, unit_price, status, "
     "is_valid, seller_name, buyer_name, seller_inn, buyer_inn, contract_form, auction_type). Для исторической аналитики.",
     {"sql": {"type": "string"}}, ["sql"]),
    ("legal_help", t_legal, "Нормы права, правила биржи и реальные судебные дела по биржевым спорам Узбекистана.",
     {"topic": {"type": "string"}}, ["topic"]),
    ("open_dispute", t_dispute, "Открыть спор по сделке покупателя.", {"deal_id": {"type": "string"},
                                                                         "text": {"type": "string"}}, ["deal_id", "text"]),
]
TOOL_SPECS = [{"name": n, "description": d, "input_schema": {"type": "object", "properties": p, "required": r}}
              for n, _, d, p, r in TOOLS]
TOOL_SPECS[-1]["cache_control"] = {"type": "ephemeral"}
TOOL_FN = {n: f for n, f, *_ in TOOLS}


def profile_text(user) -> str:
    a = q1("select * from agents where user_id=?", user["id"]) or {}
    prof = json.loads(a.get("profile") or "{}")
    mem = q("select kind, text from memory where user_id=? order by id desc limit 25", user["id"])
    hist = q("select instrument, count(*) n, sum(qty) t, avg(limit_price) p from mandates where user_id=? and status!='draft' "
             "group by 1", user["id"])
    return json.dumps({"agent_name": a.get("name"), "user": {k: user.get(k) for k in ("name", "status", "company", "region", "lang")},
                       "onboarding": prof, "memories": mem, "mandate_history": hist}, ensure_ascii=False)


SYSTEM = """Ты — {agent_name}, личный ИИ-агент пользователя на бирже UZEX 2035. В этой модели люди не торгуют сами и не ищут
брокеров: человек говорит, что ему нужно и какие у него границы, а ты превращаешь это в мандат, следишь за рынком,
торгуешься на аукционах, ведёшь сделку до приёмки товара и защищаешь интересы пользователя в спорах.

Профиль и память о пользователе (используй, подстраивайся под него; узнал новое — вызови remember):
{profile}

Как работает биржа (песочница UZEX 2035, всё реально исполняется): товары: {instruments}. Сессии идут по расписанию,
цена — единая цена клиринга (все платят одну цену). Мандаты меньше минимального лота автоматически объединяются в общий
лот с другими мелкими покупателями. Деньги лежат в сейфе биржи до приёмки. Документы создаются и подписываются сами.
Споры решаются по цепочке доказательств (весы, пломба, GPS). Сборы: 0,13% покупатель + 0,05% клиринг.

Что ещё умеешь: продавать за пользователя (фермер, завод, цех) — side=sell; ставить подписки и ценовые алерты
(set_alert); говорить, в какие месяцы товар обычно дешевле (seasonality); фиксировать цену на будущую поставку —
ценовой щит (price_lock_quote), это защищает от скачков вроде пропана в сентябре 2026 (+65% за два дня).
Право: штрафы считаются по Закону №670-I «О договорно-правовой базе…» (недопоставка 0,5% в день, не более 50%;
некачественный товар 20%; отказ от оплаты 15%; просрочка оплаты 0,4% в день, не более 50%), задаток — ст.311–312 ГК.
Факты для ответов: ценовой коридор +10% от старта действует только для сжиженного газа (Комитет по конкуренции, с 12.01.2026);
на замечания по отгрузке у покупателя 6 рабочих часов (Правила UzEx, ред. 01.06.2026); ответ на претензию — 15 дней
(ст.18 Закона №670-I), претензия не обязательна, если не предусмотрена договором (ст.19); решение Арбитражной комиссии
биржи окончательно внутри биржи, но сторона вправе обратиться в суд (п.57 Положения), при этом суды по-разному оценивали
подведомственность (дело 4-1001-2303/20270); госпошлина в экономический суд 2% цены иска, не менее 1 БРВ, малому бизнесу 50%;
самозанятые платят 1% с оборота, покупатель-юрлицо удерживает налог как налоговый агент; коды товаров — по каталогу ИКПУ
(tasnif.soliq.uz).

ПРАВИЛА:
1. Отвечай на языке пользователя (узбекский латиница/кириллица или русский), просто и коротко, как опытный брокер
   объясняет другу. Без жаргона; если нужен термин — объясни в скобках.
2. Все цифры — только из инструментов. Не выдумывай. Если данных нет — скажи.
3. Прогноз — это рекомендация, не указание. Всегда говори уверенность и точность модели; решение за человеком.
4. Когда пользователь хочет купить: уточни недостающее (товар, объём, лимит цены, срок) одним вопросом, если без
   этого никак; иначе предложи разумные значения сам (лимит — текущая цена + 3–5%, срок — 7 дней) и вызови
   propose_mandate. Скажи, что нужно подтвердить мандат PIN-кодом в карточке.
5. Перед советом о покупке посмотри recommend и calendar. Если скоро сессия по нужному товару — скажи когда.
6. Юридические вопросы — через legal_help; ссылайся на нормы и реальные дела, без выдумок.
7. Формат: 1–4 коротких абзаца или пункта, суммы с пробелами между тысячами, «сум/т». Не пиши текст перед вызовом
   инструментов.
"""


def run(user, message, ui_lang="ru"):
    """Generator of SSE events for one user turn."""
    hist = q("select role, content from chat where user_id=? order by id desc limit 10", user["id"])[::-1]
    messages = [{"role": h["role"], "content": h["content"]} for h in hist]
    messages.append({"role": "user", "content": f"[ui:{ui_lang}] {message}"})
    a = q1("select name from agents where user_id=?", user["id"]) or {"name": "Agent"}
    system = [{"type": "text", "text": SYSTEM.format(agent_name=a["name"], profile=profile_text(user),
                                                     instruments=", ".join(f"{k} = {v['name_ru']} (лот {v['lot']} т)"
                                                                           for k, v in INSTRUMENTS.items())),
               "cache_control": {"type": "ephemeral"}}]
    cards, final = [], ""
    for _ in range(8):
        with client().messages.stream(model=MODEL, max_tokens=1600, system=system, tools=TOOL_SPECS,
                                      messages=messages) as st:
            streamed = False
            for ev in st:
                if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                    streamed = True
                    yield {"type": "text", "text": ev.delta.text}
            msg = st.get_final_message()
        uses = [b for b in msg.content if b.type == "tool_use"]
        if not uses:
            final = "".join(b.text for b in msg.content if b.type == "text")
            break
        if streamed:
            yield {"type": "reset"}
        messages.append({"role": "assistant", "content": msg.content})
        results = []
        for u in uses:
            yield {"type": "step", "tool": u.name, "input": u.input}
            try:
                res = TOOL_FN[u.name](user, **u.input)
            except Exception as e:  # noqa: BLE001
                res = {"error": str(e)[:300]}
            if isinstance(res, dict) and (res.get("card") or res.get("forward_card")):
                cards.append(res)
                yield {"type": "card", "card": res}
            if u.name == "recommend" and isinstance(res, dict) and "action" in res:
                yield {"type": "recommendation", "data": res}
            results.append({"type": "tool_result", "tool_use_id": u.id,
                            "content": json.dumps(res, ensure_ascii=False, default=str)[:12000]})
        messages.append({"role": "user", "content": results})
    with tx() as c:
        c.execute("insert into chat(user_id, role, content, ts) values(?,?,?,?)", (user["id"], "user", message, now()))
        c.execute("insert into chat(user_id, role, content, ts) values(?,?,?,?)",
                  (user["id"], "assistant", final or "…", now()))
    yield {"type": "done", "text": final, "cards": cards}
