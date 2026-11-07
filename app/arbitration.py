"""Evidence-based arbitration: deterministic fault attribution + money plan; LLM writes the reasoning with precedents."""
import json
import os
import threading
import traceback

import docs
from core import (FEE_CLEARING, FEE_SELLER, INSTRUMENTS, SYS, acct, add_event, notify, now, post, q, q1, tx, uid)

TOL = 0.005
CASES_FILE = os.path.join(os.path.dirname(__file__), "data", "court_cases.json")


def legal_base() -> dict:
    try:
        return json.load(open(CASES_FILE, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"cases": [], "norms": []}


def open_dispute(c, deal_id, opened_by, reason, text):
    did = uid("ARB")
    c.execute("insert into disputes(id, deal_id, opened_by, reason, status, created_at) values(?,?,?,?,?,?)",
              (did, deal_id, opened_by, reason, "analyzing", now()))
    c.execute("update deals set dispute_id=? where id=?", (did, deal_id))
    add_event(c, deal_id, "dispute_opened", opened_by, {"dispute": did, "reason": reason, "text": text})
    d = c.execute("select buyer, seller from deals where id=?", (deal_id,)).fetchone()
    for u in d:
        notify(c, u, "dispute", "Открыт спор по сделке", f"{text}. ИИ-арбитр анализирует доказательства.",
               f"/deals/{deal_id}")
    threading.Thread(target=_analyze_bg, args=(did,), daemon=True).start()
    return did


def _ev(events, type_):
    for e in reversed(events):
        if e["type"] == type_:
            return json.loads(e["payload"]) | {"_hash": e["hash"], "_ts": e["ts"]}
    return None


def attribute(deal_id: str) -> dict:
    """Pure rules: who is at fault and how money must move. Fully explainable, no ML."""
    d = q1("select * from deals where id=?", deal_id)
    ev = q("select * from events where deal_id=? order by id", deal_id)
    Q, P = d["qty"], d["price"]
    loaded, unloaded = _ev(ev, "loaded"), _ev(ev, "unloaded")
    gps, arrived = _ev(ev, "gps_anomaly"), _ev(ev, "arrived")
    findings, moves, fault = [], [], {}
    if not loaded:
        findings.append({"fact": "Отгрузка не зафиксирована до истечения срока", "evidence": "ship_deadline_missed"})
        fault = {"seller": 1.0}
        moves = [("escrow→buyer", d["amount"], "Возврат оплаты покупателю"),
                 ("seller_deposit→buyer", d["deposit_seller"], "Задаток продавца переходит покупателю (п.171 Правил)")]
        return {"fault": fault, "findings": findings, "moves": moves, "summary": "Виноват продавец: товар не отгружен"}
    L, U = float(loaded["weighbridge_qty"]), float(unloaded["weighbridge_qty"]) if unloaded else float(loaded["weighbridge_qty"])
    findings.append({"fact": f"По договору {Q} т; весы продавца при погрузке: {L} т", "evidence": loaded["_hash"][:12]})
    findings.append({"fact": f"Весы покупателя при выгрузке: {U} т", "evidence": unloaded["_hash"][:12] if unloaded else "—"})
    seller_short = max(0.0, Q - L) if L < Q * (1 - TOL) else 0.0
    transit_loss = max(0.0, L - U) if U < L * (1 - TOL) else 0.0
    seal_ok = arrived.get("seal_intact", True) if arrived else True
    if seller_short:
        findings.append({"fact": f"Недогруз на складе продавца: {round(seller_short, 2)} т", "evidence": loaded["_hash"][:12]})
    carrier_guilty = bool(transit_loss) and (gps is not None or not seal_ok)
    if transit_loss:
        if gps:
            findings.append({"fact": f"GPS: незапланированная остановка {gps.get('stop_minutes')} мин вне маршрута",
                             "evidence": gps["_hash"][:12]})
        if arrived and not seal_ok:
            findings.append({"fact": f"Пломба при выгрузке ({arrived.get('seal_seen')}) не совпадает с пломбой при погрузке "
                                     f"({loaded.get('seal')})", "evidence": arrived["_hash"][:12]})
        findings.append({"fact": f"Потеря в пути: {round(transit_loss, 2)} т", "evidence": "расчёт L−U"})
    paid_to_seller = round(P * min(L, Q))
    if seller_short:
        fault["seller"] = round(seller_short / (seller_short + transit_loss), 2)
        moves.append(("escrow→buyer", round(P * seller_short), "Возврат за недогруженный товар"))
        moves.append(("seller_deposit→buyer", round(d["deposit_seller"] * seller_short / Q),
                      "Неустойка: доля задатка продавца пропорционально недопоставке (п.171 Правил)"))
    if transit_loss and carrier_guilty:
        fault["carrier"] = round(1 - fault.get("seller", 0), 2)
        moves.append(("carrier→buyer", round(P * transit_loss), "Компенсация перевозчика за потерю в пути"))
    elif transit_loss:
        fault["unclear"] = 1.0
        findings.append({"fact": "Пломба цела и маршрут без отклонений: нужна независимая перевеска", "evidence": "—"})
        moves.append(("escrow_hold", round(P * transit_loss), "Удерживается в сейфе до независимой перевески"))
        paid_to_seller -= round(P * transit_loss)
    moves.insert(0, ("escrow→seller", paid_to_seller, "Оплата продавцу за фактически отгруженный товар"))
    if not fault:
        fault = {"buyer": 1.0}
        findings.append({"fact": "Расхождение в пределах допуска 0,5% — претензия необоснованна", "evidence": "—"})
    who = {"seller": "продавец", "carrier": "перевозчик", "buyer": "покупатель", "unclear": "не установлено"}
    summary = "Виновн" + ("ы: " if len(fault) > 1 else "ый: ") + ", ".join(f"{who[k]} ({int(v * 100)}%)" for k, v in fault.items())
    return {"fault": fault, "findings": findings, "moves": moves, "summary": summary,
            "numbers": {"contract": Q, "loaded": L, "received": U, "price": P}}


def _llm_reasoning(d, res) -> str:
    base = legal_base()
    try:
        import anthropic
        client = anthropic.Anthropic()
        prompt = (
            "Ты — ИИ-арбитр товарной биржи UZEX. Напиши мотивировочную часть решения по спору на русском языке: "
            "4–6 коротких нумерованных пунктов, всего не более 140 слов, без заголовков и без markdown-разметки. Опирайся ТОЛЬКО на факты, расчёт и нормы ниже; ссылайся на "
            "доказательства по их хешам в скобках, на нормы — по названию и статье, на прецеденты — по номеру дела "
            "или названию, только если они действительно похожи по сути (если прямых аналогов нет — так и скажи одной фразой). Не выдумывай фактов. В конце одной фразой: "
            "что сторона может сделать, если не согласна (Арбитражная комиссия биржи, затем экономический суд).\n\n"
            f"Сделка: {json.dumps({k: d[k] for k in ('id', 'instrument', 'qty', 'price', 'amount')}, ensure_ascii=False)}\n"
            f"Результат правил: {json.dumps(res, ensure_ascii=False)}\n"
            f"Нормы: {json.dumps(base.get('norms', [])[:12], ensure_ascii=False)}\n"
            f"Прецеденты: {json.dumps(base.get('cases', [])[:6], ensure_ascii=False)}")
        msg = client.messages.create(model=os.environ.get("UZEX_MODEL", "claude-sonnet-5-5"), max_tokens=1500,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as e:  # noqa: BLE001
        return f"{res['summary']}. Решение принято по правилам распределения ответственности (ИИ-обоснование недоступно: {e})."


def precedents_for(reason: str) -> list:
    types = {"short_weight": ("short_weight", "non_delivery", "quality"), "non_delivery": ("non_delivery", "penalty"),
             "non_payment": ("non_payment",)}.get(reason, ())
    return [c for c in legal_base().get("cases", []) if c.get("dispute_type") in types][:3]


def _analyze_bg(dispute_id):
    try:
        dsp = q1("select * from disputes where id=?", dispute_id)
        d = q1("select * from deals where id=?", dsp["deal_id"])
        res = attribute(d["id"])
        res["reasoning"] = _llm_reasoning(d, res)
        res["statutory"] = statutory(d["id"])
        res["precedents"] = [{"case": c.get("case_number") or c.get("id"), "court": c.get("court"),
                              "outcome": c.get("outcome"), "url": c.get("source_url")} for c in precedents_for(dsp["reason"])]
        status = "needs_review" if "unclear" in res["fault"] else "proposed"
        with tx() as c:
            c.execute("update disputes set status=?, fault=?, decision=? where id=?",
                      (status, json.dumps(res["fault"]), json.dumps(res, ensure_ascii=False), dispute_id))
            add_event(c, d["id"], "decision_proposed", "ai_arbiter", {"dispute": dispute_id, "fault": res["fault"],
                                                                      "summary": res["summary"]})
            for u in (d["buyer"], d["seller"]):
                notify(c, u, "dispute", "Предложено решение по спору", res["summary"], f"/deals/{d['id']}")
        if d["buyer"].startswith("bot_") and status == "proposed":
            accept(dispute_id, d["buyer"])
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def accept(dispute_id, user_id, operator=False):
    dsp = q1("select * from disputes where id=?", dispute_id)
    if not dsp or dsp["status"] not in ("proposed", "needs_review"):
        return {"error": "Решение уже исполнено или ещё не готово"}
    if dsp["status"] == "needs_review" and not operator:
        return {"error": "Нужна независимая перевеска: решение утверждает арбитр биржи"}
    d = q1("select * from deals where id=?", dsp["deal_id"])
    if not operator and user_id not in (d["buyer"], d["seller"]):
        return {"error": "Нет доступа"}
    res = json.loads(dsp["decision"])
    with tx() as c:
        for kind, amount, memo in res["moves"]:
            if kind == "escrow→seller":
                post(c, SYS["escrow"], acct(d["seller"], "wallet"), amount, "settlement", d["id"], memo)
                import engine
                engine.withhold_self_employed(c, d, amount)
                post(c, acct(d["seller"], "wallet"), SYS["fees"], int(amount * FEE_SELLER), "fee", d["id"], "Сбор продавца")
                post(c, acct(d["seller"], "wallet"), SYS["clearing"], int(amount * FEE_CLEARING), "fee", d["id"], "Клиринг")
            elif kind == "escrow→buyer":
                post(c, SYS["escrow"], acct(d["buyer"], "wallet"), amount, "refund", d["id"], memo)
            elif kind == "seller_deposit→buyer":
                post(c, acct(d["seller"], "blocked"), acct(d["buyer"], "wallet"), amount, "penalty", d["id"], memo)
            elif kind == "carrier→buyer":
                post(c, SYS["carrier"], acct(d["buyer"], "wallet"), amount, "compensation", d["id"], memo)
        used = sum(a for k, a, _ in res["moves"] if k == "seller_deposit→buyer")
        post(c, acct(d["seller"], "blocked"), acct(d["seller"], "wallet"), d["deposit_seller"] - used, "release",
             d["id"], "Возврат оставшегося задатка продавца")
        c.execute("update disputes set status='resolved', resolved_at=? where id=?", (now(), dispute_id))
        c.execute("update deals set status='resolved' where id=?", (d["id"],))
        payload = {"fault": res["summary"], "reasoning": res.get("reasoning", ""),
                   "money": [f"{memo}: {amount:,} сум".replace(",", " ") for _, amount, memo in res["moves"]],
                   "precedents": [f"{p['case']} — {p.get('court') or ''}" for p in res.get("precedents", [])],
                   "accepted_by": "оператор биржи" if operator else user_id}
        docs.decision(c, d["id"], payload)
        add_event(c, d["id"], "decision_executed", "clearing", {"dispute": dispute_id, "moves": res["moves"]})
        for u in (d["buyer"], d["seller"]):
            notify(c, u, "dispute", "Решение исполнено", "Деньги распределены по решению. Документ подписан.",
                   f"/deals/{d['id']}")
    return {"status": "resolved"}


# ------------------------------------------------------------------ statutory sanctions (Law No. 670-I) & claims
def statutory(deal_id: str) -> list:
    """What the injured party may additionally claim under Law No.670-I «О договорно-правовой базе деятельности
    хозяйствующих субъектов» (art.25: short/late delivery 0.5% per day, max 50%; art.26: poor quality 20%;
    art.32: refusal to pay 15%, late payment 0.4% per day, max 50%). Exchange deposit rules (п.170–171 Правил,
    ст.311–312 ГК) apply in addition and are executed automatically by the clearing house."""
    d = q1("select * from deals where id=?", deal_id)
    ev = q("select * from events where deal_id=? order by id", deal_id)
    out = []
    loaded, unloaded = _ev(ev, "loaded"), _ev(ev, "unloaded")
    days_late = 1
    if d["ship_due"] and loaded:
        days_late = max(0, int((loaded["_ts"] - d["ship_due"]) // 86400) + (1 if loaded["_ts"] > d["ship_due"] else 0))
    if not loaded and d["status"] in ("disputed", "resolved"):
        base = d["amount"]
        out.append({"norm": "ст.25 Закона №670-I", "what": "неустойка за непоставку", "rate": "0,5% в день, не более 50%",
                    "base": base, "days": 1, "amount": round(base * 0.005), "max": round(base * 0.5),
                    "who_pays": "продавец"})
    elif loaded and float(loaded["weighbridge_qty"]) < d["qty"] * (1 - TOL):
        short = d["qty"] - float(loaded["weighbridge_qty"])
        base = round(short * d["price"])
        out.append({"norm": "ст.25 Закона №670-I", "what": "неустойка за недопоставку", "rate": "0,5% от стоимости "
                    "недопоставленного за каждый день, не более 50%", "base": base, "days": max(1, days_late),
                    "amount": round(base * 0.005 * max(1, days_late)), "max": round(base * 0.5), "who_pays": "продавец"})
    if d["status"] == "annulled":
        out.append({"norm": "ст.32 Закона №670-I; ст.312 ГК", "what": "штраф за отказ от оплаты (вместо него применён "
                    "задаток)", "rate": "15% от неоплаченной суммы", "base": d["amount"], "days": None,
                    "amount": round(d["amount"] * 0.15), "max": None, "who_pays": "покупатель"})
    if unloaded and loaded and float(unloaded["weighbridge_qty"]) < float(loaded["weighbridge_qty"]) * (1 - TOL):
        lost = float(loaded["weighbridge_qty"]) - float(unloaded["weighbridge_qty"])
        out.append({"norm": "ст.333 ГК; договор перевозки", "what": "возмещение стоимости утраченного в пути груза",
                    "rate": "полная стоимость утраты", "base": round(lost * d["price"]), "days": None,
                    "amount": round(lost * d["price"]), "max": None, "who_pays": "перевозчик"})
    return out


def claim(deal_id: str, user_id: str) -> str:
    """Pre-trial claim (претензия) generated from the evidence chain; signed by the claimant."""
    d = q1("select * from deals where id=?", deal_id)
    if not d or user_id not in (d["buyer"], d["seller"]):
        raise ValueError("Сделка не найдена")
    st = statutory(deal_id)
    res = attribute(deal_id)
    me = q1("select name, company, inn, pinfl, region from users where id=?", user_id)
    payer = st[0]["who_pays"] if st else ("продавец" if user_id == d["buyer"] else "покупатель")
    if payer == "перевозчик":
        other = {"company": d["carrier"], "note": f"перевозчик по ТТН, автомобиль {d['truck']}, пломба {d['seal']}"}
    else:
        other_id = d["seller"] if payer == "продавец" else d["buyer"]
        other = q1("select name, company, inn, region from users where id=?", other_id)
    total = sum(x["amount"] for x in st)
    ins = INSTRUMENTS[d["instrument"]]
    text = None
    try:
        import anthropic
        prompt = ("Составь текст досудебной претензии (Узбекистан, экономический спор по биржевой сделке) на русском. "
                  "Структура: кому, от кого, суть (факты с хешами доказательств в скобках), требования с суммами, правовое "
                  "основание (только из списка ниже), срок ответа — 15 дней (ст.18 Закона №670-I), указание, что при неудовлетворении "
                  "истец обратится в экономический суд. Без markdown-заголовков, деловым языком, 180–260 слов. Не выдумывай.\n"
                  f"Сделка: {json.dumps({k: d[k] for k in ('id', 'qty', 'price', 'amount')}, ensure_ascii=False)}, товар {ins['name_ru']}\n"
                  f"Заявитель: {json.dumps(me, ensure_ascii=False)}\nАдресат: {json.dumps(other, ensure_ascii=False)}\n"
                  f"Факты: {json.dumps(res['findings'], ensure_ascii=False)}\nСанкции: {json.dumps(st, ensure_ascii=False)}\n"
                  f"Нормы: {json.dumps(legal_base().get('norms', [])[:12], ensure_ascii=False)}")
        msg = anthropic.Anthropic().messages.create(model=os.environ.get("UZEX_MODEL", "claude-sonnet-5-5"), max_tokens=1500,
                                                    messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as e:  # noqa: BLE001
        text = f"Требование: уплатить {total} сум по основаниям: " + "; ".join(f"{x['norm']} — {x['what']}" for x in st) + f" ({e})"
    with tx() as c:
        did = docs.claim(c, deal_id, user_id, {"from": me, "to": other, "goods": ins["name_ru"], "deal_amount": d["amount"],
                                               "demands": [f"{x['what']} ({x['norm']}): {x['amount']:,} сум".replace(",", " ")
                                                           for x in st], "total": total, "text": text,
                                               "deadline": "15 дней с момента получения (ст.18 Закона №670-I)"})
    return did
