"""Zero-paper deals: documents are generated from deal data, signed (Ed25519) by the parties and the exchange."""
import html
import io
import json
import time

import segno

from core import INSTRUMENTS, canon, new_keypair, now, q, q1, sha, sign, uid, verify

TITLES = {"contract": "Биржевой договор", "invoice": "Электронный счёт-фактура (ЭСФ)", "ttn": "Электронная товарно-транспортная накладная (ЭТТН)",
          "acceptance": "Акт приёмки товара", "decision": "Решение по спору", "mandate": "Мандат (поручение агенту)",
          "claim": "Досудебная претензия"}


def _exchange_key(c):
    r = c.execute("select sign_pub, sign_priv from users where id='exchange'").fetchone()
    if r:
        return r[0], r[1]
    pub, priv = new_keypair()
    c.execute("insert into users(id, name, role, sign_pub, sign_priv, created_at) values('exchange',"
              "'АО «UZEX» — клиринг и регистрация',?,?,?,?)", ("exchange", pub, priv, now()))
    return pub, priv


def _party(c, user_id):
    r = c.execute("select id, name, company, inn, pinfl, region, status, sign_pub, sign_priv from users where id=?",
                  (user_id,)).fetchone()
    return dict(zip(["id", "name", "company", "inn", "pinfl", "region", "status", "pub", "priv"], r)) if r else None


def _make(c, deal_id, kind, payload, signers):
    _exchange_key(c)
    payload = {"kind": kind, "deal": deal_id, "created": time.strftime("%d.%m.%Y %H:%M:%S"), **payload}
    body = canon(payload)
    h = sha(body)
    sigs = []
    for sid, role in signers + [("exchange", "Биржа (регистрация)")]:
        p = _party(c, sid)
        if p and p["priv"]:
            sigs.append({"signer": sid, "name": p["company"] or p["name"], "role": role, "pub": p["pub"],
                         "sig": sign(p["priv"], body), "ts": now()})
    did = uid("DOC")
    c.execute("insert into documents(id, deal_id, kind, title, payload, hash, signatures, created_at) "
              "values(?,?,?,?,?,?,?,?)", (did, deal_id, kind, TITLES[kind], json.dumps(payload, ensure_ascii=False),
                                          h, json.dumps(sigs), now()))
    from core import add_event
    add_event(c, deal_id, "document", "exchange", {"doc": did, "kind": kind, "hash": h})
    return did


_MX = None


def mxik(key):
    global _MX
    if _MX is None:
        import os
        try:
            _MX = json.load(open(os.path.join(os.path.dirname(__file__), "data", "mxik.json"), encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _MX = {}
    m = _MX.get(key)
    return f"{m['code']} — {m['name']} ({m['kind']})" if m else None


def _deal(c, deal_id):
    cols = [d[0] for d in c.execute("select * from deals where id=?", (deal_id,)).description]
    return dict(zip(cols, c.execute("select * from deals where id=?", (deal_id,)).fetchone()))


def _parties(c, d):
    b, s = _party(c, d["buyer"]), _party(c, d["seller"])
    clean = lambda p: {k: p[k] for k in ("name", "company", "inn", "pinfl", "region", "status") if p.get(k)}
    return clean(b), clean(s)


def contract(c, deal_id):
    d = _deal(c, deal_id)
    ins = INSTRUMENTS[d["instrument"]]
    b, s = _parties(c, d)
    return _make(c, deal_id, "contract", {
        "buyer": b, "seller": s, "goods": ins["name_ru"], "mxik": mxik(d["instrument"]), "qty_t": d["qty"], "price": d["price"], "amount": d["amount"],
        "deposit_buyer": d["deposit_buyer"], "deposit_seller": d["deposit_seller"], "session": d["session_id"],
        "terms": ["Цена определена единым клирингом сессии; все покупатели сессии платят одну цену.",
                  "Деньги покупателя хранятся в сейфе биржи до подтверждённой приёмки.",
                  "Неоплата в срок: задаток покупателя переходит продавцу.",
                  "Неотгрузка или недовес по вине продавца: возврат за недопоставку и неустойка из задатка продавца; "
                  "дополнительно — пеня 0,5% в день, не более 50% (ст.25 Закона №670-I).",
                  "Просрочка оплаты: пеня 0,4% в день, не более 50%; отказ от оплаты — штраф 15% (ст.32 Закона №670-I).",
                  "Потеря в пути по вине перевозчика: компенсация из страхового фонда перевозчиков.",
                  "Допуск по весу ±0,5%. Споры разрешаются по цепочке доказательств, затем Арбитражной комиссией."],
        "pool": d["pool_id"]}, [(d["buyer"], "Покупатель (агент по мандату)"), (d["seller"], "Продавец")])


def invoice(c, deal_id):
    d = _deal(c, deal_id)
    ins = INSTRUMENTS[d["instrument"]]
    b, s = _parties(c, d)
    vat = round(d["amount"] * 12 / 112)
    return _make(c, deal_id, "invoice", {"seller": s, "buyer": b, "basis": f"Биржевой договор по сделке {deal_id}",
                                         "goods": ins["name_ru"], "mxik": mxik(d["instrument"]), "unit": "тонна",
                                         "qty_t": d["qty"], "price": d["price"], "amount": d["amount"],
                                         "vat_rate": "12% (ст.258 НК РУз)", "vat_included": vat,
                                         "note": "Поля по Положению к ПКМ №489 от 14.08.2020. Отправка и подпись — через оператора ЭДО (Didox API) с E-IMZO"},
                 [(d["seller"], "Продавец")])


def ttn(c, deal_id):
    d = _deal(c, deal_id)
    ins = INSTRUMENTS[d["instrument"]]
    b, s = _parties(c, d)
    return _make(c, deal_id, "ttn", {"shipper": s, "consignee": b, "goods": ins["name_ru"], "mxik": mxik(d["instrument"]),
                                     "basis": f"Биржевой договор и ЭСФ по сделке {deal_id} (объединённый ЭСФ+ЭТТН — ПКМ №168 от 18.03.2025)",
                                     "qty_contract": d["qty"],
                                     "qty_loaded": d["loaded_qty"], "carrier": d["carrier"], "truck": d["truck"],
                                     "seal": d["seal"], "route": f"{s.get('region')} → {b.get('region')}"},
                 [(d["seller"], "Грузоотправитель")])


def acceptance(c, deal_id):
    d = _deal(c, deal_id)
    ins = INSTRUMENTS[d["instrument"]]
    b, s = _parties(c, d)
    return _make(c, deal_id, "acceptance", {"buyer": b, "seller": s, "goods": ins["name_ru"], "qty_contract": d["qty"],
                                            "qty_loaded": d["loaded_qty"], "qty_received": d["delivered_qty"],
                                            "result": "Принято без расхождений"},
                 [(d["buyer"], "Покупатель"), (d["seller"], "Продавец")])


def decision(c, deal_id, payload):
    d = _deal(c, deal_id)
    return _make(c, deal_id, "decision", payload, [])


def claim(c, deal_id, user_id, payload):
    return _make(c, deal_id, "claim", payload, [(user_id, "Заявитель")])


def mandate_doc(c, user_id, mandate):
    """The mandate itself is a signed power of attorney for the agent."""
    p = _party(c, user_id)
    body = canon({k: mandate[k] for k in ("id", "side", "instrument", "qty", "limit_price", "deadline", "strategy",
                                         "confirm_above")})
    return sign(p["priv"], body)


# ------------------------------------------------------------------ rendering & verification
def check(doc_id: str) -> dict:
    r = q1("select * from documents where id=?", doc_id)
    if not r:
        return {"ok": False, "error": "Документ не найден"}
    payload = json.loads(r["payload"])
    body = canon(payload)
    sigs = json.loads(r["signatures"])
    res = [{"name": s["name"], "role": s["role"], "valid": verify(s["pub"], body, s["sig"]),
            "pub": s["pub"][:16] + "…", "ts": s["ts"]} for s in sigs]
    from core import verify_chain
    chain = verify_chain(r["deal_id"]) if r["deal_id"] else None
    return {"ok": sha(body) == r["hash"] and all(x["valid"] for x in res), "hash": r["hash"],
            "hash_matches": sha(body) == r["hash"], "signatures": res, "chain": chain, "doc": r, "payload": payload}


def qr_svg(url: str) -> str:
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=3, dark="#13213C", border=1)
    return buf.getvalue().decode()


def _fmt(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    if isinstance(v, dict) and ("company" in v or "name" in v):
        st = {"company": "юридическое лицо", "ip": "индивидуальный предприниматель", "self_employed": "самозанятый",
              "individual": "физическое лицо"}.get(v.get("status"), v.get("status") or "")
        idn = (f"ИНН {v['inn']}" if v.get("inn") and len(str(v["inn"])) == 9 else
               f"рег. № {v['inn']}" if v.get("inn") else "")
        name = v.get("company") or v.get("name")
        rep = f" (в лице {v['name']})" if v.get("company") and v.get("name") and v["name"] != v["company"] else ""
        return (f"<b>{html.escape(name)}</b>{html.escape(rep)}<br><span class='muted'>"
                + html.escape(", ".join(x for x in (st, idn, v.get("region"), v.get("note")) if x)) + "</span>")
    if isinstance(v, dict):
        return "<br>".join(f"{html.escape(str(k))}: {html.escape(str(x))}" for k, x in v.items())
    if isinstance(v, list):
        return "<ol>" + "".join(f"<li>{html.escape(str(x))}</li>" for x in v) + "</ol>"
    return html.escape(str(v))


LABELS = {"buyer": "Покупатель", "seller": "Продавец", "goods": "Товар", "qty_t": "Количество, т", "price": "Цена, сум/т",
          "amount": "Сумма, сум", "deposit_buyer": "Задаток покупателя", "deposit_seller": "Задаток продавца",
          "session": "Торговая сессия", "terms": "Условия", "pool": "Общий лот", "vat_included": "в т.ч. НДС 12%",
          "note": "Примечание", "shipper": "Грузоотправитель", "consignee": "Грузополучатель",
          "qty_contract": "По договору, т", "qty_loaded": "Погружено, т", "qty_received": "Принято, т",
          "carrier": "Перевозчик", "truck": "Автомобиль", "seal": "Пломба", "route": "Маршрут", "result": "Результат",
          "fault": "Виновная сторона", "reasoning": "Обоснование", "money": "Движение денег", "norms": "Нормы",
          "precedents": "Прецеденты", "created": "Дата", "deal": "Сделка", "kind": "Тип", "from": "От кого", "to": "Кому",
          "deal_amount": "Сумма сделки, сум", "demands": "Требования", "total": "Итого требований, сум", "text": "Текст претензии",
          "deadline": "Срок ответа", "statutory": "Санкции по закону", "basis": "Основание", "unit": "Единица измерения",
          "vat_rate": "Ставка НДС", "accepted_by": "Принято", "mxik": "ИКПУ (MXIK)"}


def render(doc_id: str, base_url: str) -> str:
    v = check(doc_id)
    if "doc" not in v:
        return "<h1>Документ не найден</h1>"
    p, r = v["payload"], v["doc"]
    rows = "".join(f"<tr><th>{LABELS.get(k, k)}</th><td>{_fmt(x)}</td></tr>" for k, x in p.items()
                   if k not in ("kind",) and x not in (None, ""))
    sigs = "".join(f"<li>{'✅' if s['valid'] else '❌'} <b>{html.escape(s['name'])}</b> — {html.escape(s['role'])}"
                   f"<br><small>ключ {s['pub']} · {time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(s['ts']))}</small></li>"
                   for s in v["signatures"])
    url = f"{base_url}/verify/{doc_id}"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(r['title'])} {doc_id}</title><style>
body{{font:15px/1.5 Onest,system-ui,sans-serif;color:#13213C;max-width:820px;margin:0 auto;padding:28px 20px;background:#fff}}
h1{{font-size:24px;margin:0 0 4px}} .muted{{color:#66728A;font-size:13px}} table{{width:100%;border-collapse:collapse;margin:18px 0}}
th{{text-align:left;width:210px;vertical-align:top;color:#46536B;font-weight:600;padding:8px 10px 8px 0;border-bottom:1px solid #E1E6EF}}
td{{padding:8px 0;border-bottom:1px solid #E1E6EF}} ol{{margin:0;padding-left:18px}} .box{{display:flex;gap:20px;align-items:center;
border:1px solid #E1E6EF;border-radius:12px;padding:14px 16px;margin-top:18px}} ul{{padding-left:18px}} .ok{{color:#0F8F8C;font-weight:600}}
.bad{{color:#B4432B;font-weight:600}} @media print{{.noprint{{display:none}}}}
.hdr{{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #13213C;padding-bottom:10px;margin-bottom:16px;font-size:13px}}
.hdr .mk{{font:700 15px/1 monospace;letter-spacing:.1em;border:2px solid #13213C;padding:8px 10px}}
.muted{{color:#66728A}} button{{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid #c9d1de;background:#fff;cursor:pointer}}</style></head><body>
<div class="hdr"><div><b>UZEX 2035</b> · биржа агентов<br><span class="muted">Документ сформирован из данных сделки и подписан электронными подписями сторон. Песочница платформы.</span></div><div class="mk">UZEX</div></div>
<h1>{html.escape(r['title'])}</h1><div class="muted">№ {doc_id} · сделка {html.escape(r['deal_id'] or '')}</div>
<table>{rows}</table>
<h3>Электронные подписи (Ed25519)</h3><ul>{sigs}</ul>
<div class="box">{qr_svg(url)}<div><div class="{'ok' if v['ok'] else 'bad'}">{'Документ подлинный: подписи верны, содержимое не изменено' if v['ok'] else 'Проверка не пройдена'}</div>
<div class="muted">SHA-256: {v['hash']}</div><div class="muted">Цепочка доказательств сделки: {'целостна' if v['chain'] and v['chain']['ok'] else 'нарушена'} · событий: {v['chain']['events'] if v['chain'] else 0}</div>
<div class="muted">Проверить: {html.escape(url)}</div></div></div>
<p class="noprint"><button onclick="print()">Скачать PDF / печать</button></p></body></html>"""
