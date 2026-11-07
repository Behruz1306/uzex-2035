import base64
import hashlib
import json
import os
import queue
import random
import re
import secrets
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import duckdb  # noqa: E402
from fastapi import FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import agent  # noqa: E402
import arbitration  # noqa: E402
import core  # noqa: E402
import docs  # noqa: E402
import engine  # noqa: E402
import integrations  # noqa: E402
import market  # noqa: E402
from core import (INSTRUMENTS, REGIONS, SYS, acct, balances, ensure_accounts, hash_pin, new_keypair, now, post, q,  # noqa: E402
                  q1, tx, uid)

app = FastAPI(title="UZEX 2035 — Agent Exchange")
STATIC = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
@app.middleware("http")
async def no_stale_assets(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        resp.headers["Cache-Control"] = "no-cache"
    return resp


_otp: dict = {}
_rate: dict = {}


@app.on_event("startup")
def startup():
    core.init_db()
    integrations.init()
    core.NOTIFY_HOOKS.append(integrations.on_notify)
    integrations.start_telegram()
    market.load_history()
    if os.environ.get("ENGINE", "1") == "1":
        engine.start()


def user_from(auth: str | None):
    tok = (auth or "").replace("Bearer ", "").strip()
    u = q1("select * from users where token=?", tok) if tok else None
    if not u:
        raise HTTPException(401, "Нужен вход")
    return u


def limited(key: str, n: int = 30, per: int = 600) -> bool:
    t = time.time()
    lst = [x for x in _rate.get(key, []) if t - x < per]
    _rate[key] = lst + [t]
    return len(lst) >= n


def public_user(u):
    a = q1("select * from agents where user_id=?", u["id"])
    return {"id": u["id"], "name": u["name"], "phone": u["phone"], "status": u["status"], "company": u["company"],
            "region": u["region"], "lang": u["lang"], "verified": bool(u["verified_at"]), "has_pin": bool(u["pin_hash"]),
            "inn": u["inn"], "pinfl_masked": (u["pinfl"] or "")[:4] + "••••••" + (u["pinfl"] or "")[-2:] if u["pinfl"] else None,
            "agent": a and {"name": a["name"], "avatar": a["avatar"], "profile": json.loads(a["profile"] or "{}")},
            "sign_pub": (u["sign_pub"] or "")[:20]}


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"ok": True}


# ------------------------------------------------------------------ auth & onboarding (sandbox of national services)
@app.post("/api/auth/start")
async def auth_start(req: Request):
    body = await req.json()
    phone = re.sub(r"\D", "", body.get("phone", ""))
    if not re.fullmatch(r"998\d{9}", phone):
        raise HTTPException(400, "Номер в формате +998 XX XXX XX XX")
    if limited("otp:" + phone, 8):
        raise HTTPException(429, "Слишком много попыток")
    code = f"{random.randint(0, 999999):06d}"
    _otp[phone] = (code, time.time())
    if integrations.send_sms(phone, f"UZEX: kod {code}. Hech kimga aytmang / Никому не сообщайте"):
        return {"sent": True}
    return {"sent": True, "sandbox_sms": code, "note": "Песочница: в боевой версии код приходит по SMS (Eskiz)"}


@app.post("/api/auth/verify")
async def auth_verify(req: Request):
    body = await req.json()
    phone = re.sub(r"\D", "", body.get("phone", ""))
    code, ts = _otp.get(phone, (None, 0))
    if not code or body.get("code") != code or time.time() - ts > 600:
        raise HTTPException(400, "Неверный или просроченный код")
    _otp.pop(phone, None)
    u = q1("select * from users where phone=? and role='user'", phone)
    token = secrets.token_urlsafe(24)
    with tx() as c:
        if not u:
            uidv = uid("U")
            pub, priv = new_keypair()
            c.execute("insert into users(id, phone, role, lang, sign_pub, sign_priv, token, created_at) values(?,?,?,?,?,?,?,?)",
                      (uidv, phone, "user", body.get("lang", "ru"), pub, priv, token, now()))
            ensure_accounts(c, uidv)
        else:
            c.execute("update users set token=? where id=?", (token, u["id"]))
    u = q1("select * from users where token=?", token)
    return {"token": token, "user": public_user(u)}


@app.post("/api/kyc/myid")
async def kyc_myid(req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    b = await req.json()
    pinfl = re.sub(r"\D", "", b.get("pinfl", ""))
    name = (b.get("name") or "").strip()
    selfie = b.get("selfie") or ""
    if len(pinfl) != 14:
        raise HTTPException(400, "ПИНФЛ — 14 цифр (на обороте ID-карты)")
    if not name or len(name) < 3:
        raise HTTPException(400, "Укажите имя и фамилию как в паспорте")
    if not selfie.startswith("data:image") or len(selfie) < 5000:
        raise HTTPException(400, "Нужно селфи с камеры для проверки живости")
    if q1("select 1 from users where pinfl=? and id!=?", pinfl, u["id"]):
        raise HTTPException(409, "Этот ПИНФЛ уже привязан к другому аккаунту (защита от подставных лиц)")
    h = hashlib.sha256(selfie.encode()).hexdigest()
    with tx() as c:
        c.execute("update users set pinfl=?, name=?, selfie_hash=?, verified_at=? where id=?", (pinfl, name, h, now(), u["id"]))
    return {"verified": True, "liveness": "passed", "selfie_hash": h[:16], "provider": "MyID (песочница)"}


@app.post("/api/profile/status")
async def profile_status(req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    b = await req.json()
    status = b.get("status")
    if status not in ("individual", "self_employed", "ip", "company"):
        raise HTTPException(400, "Неизвестный статус")
    inn = re.sub(r"\D", "", b.get("inn", ""))
    company = (b.get("company") or "").strip()
    reg_no = None
    if status == "self_employed" and not inn:
        reg_no = f"SE-{random.randint(10**7, 10**8 - 1)}"     # instant online self-employment (sandbox of soliq.uz)
    if status in ("ip", "company") and len(inn) != 9:
        raise HTTPException(400, "ИНН — 9 цифр")
    region = b.get("region") if b.get("region") in REGIONS else "Toshkent shahri"
    with tx() as c:
        c.execute("update users set status=?, inn=?, company=?, region=? where id=?",
                  (status, inn or reg_no, company or None, region, u["id"]))
    return {"ok": True, "self_employed_reg": reg_no,
            "limits": {"individual": "до 50 млн сум в месяц, без дефицитных товаров",
                       "self_employed": "до 1 млрд сум в год", "ip": "без лимитов", "company": "без лимитов"}[status]}


@app.post("/api/agent/create")
async def agent_create(req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    b = await req.json()
    pin = str(b.get("pin", ""))
    if not re.fullmatch(r"\d{4,6}", pin):
        raise HTTPException(400, "PIN — 4–6 цифр. Им вы подтверждаете мандаты агенту")
    name = (b.get("name") or "Agent").strip()[:24]
    profile = {k: b.get(k) for k in ("business", "interests", "volume", "risk", "goal", "lang")}
    with tx() as c:
        c.execute("insert or replace into agents(user_id, name, avatar, profile, created_at) values(?,?,?,?,?)",
                  (u["id"], name, b.get("avatar", "spark"), json.dumps(profile, ensure_ascii=False), now()))
        c.execute("update users set pin_hash=?, lang=? where id=?", (hash_pin(u["id"], pin), b.get("lang", "ru"), u["id"]))
        for k in profile.get("interests") or []:
            if k in INSTRUMENTS:
                c.execute("insert into memory(user_id, kind, text, created_at) values(?,?,?,?)",
                          (u["id"], "preference", f"Интересуется товаром: {INSTRUMENTS[k]['name_ru']}", now()))
    return {"ok": True, "user": public_user(q1("select * from users where id=?", u["id"]))}


@app.get("/api/me")
def me(authorization: str = Header(None)):
    u = user_from(authorization)
    unread = q1("select count(*) n from notifications where user_id=? and read=0", u["id"])["n"]
    return {"user": public_user(u), "wallet": balances(u["id"]), "unread": unread}


# ------------------------------------------------------------------ wallet (sandbox of Payme/Click/instant payments)
_pay: dict = {}


@app.post("/api/wallet/topup/start")
async def topup_start(req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    b = await req.json()
    amount = int(b.get("amount", 0))
    card = re.sub(r"\D", "", b.get("card", ""))
    if amount < 100_000 or amount > 20_000_000_000:
        raise HTTPException(400, "Сумма от 100 000 до 20 млрд сум")
    if len(card) != 16 or not card.startswith(("8600", "9860", "5614", "4")):
        raise HTTPException(400, "Карта Uzcard / Humo / Visa, 16 цифр")
    prov = b.get("provider", "sandbox")
    base_url = os.environ.get("PUBLIC_URL", "https://uzex-2035.fly.dev")
    if prov == "payme" and integrations.mode()["payme"]:
        pid = integrations.new_payment(u["id"], "payme", amount)
        return {"redirect": integrations.payme_checkout_url(pid, amount, base_url + "/#/wallet", u["lang"] or "ru")}
    if prov == "click" and integrations.mode()["click"]:
        pid = integrations.new_payment(u["id"], "click", amount)
        return {"redirect": integrations.click_pay_url(pid, amount, base_url + "/#/wallet")}
    pid = uid("PAY")
    code = f"{random.randint(0, 999999):06d}"
    _pay[pid] = {"user": u["id"], "amount": amount, "card": card[-4:], "code": code, "ts": time.time()}
    return {"payment_id": pid, "sandbox_sms": code, "provider": b.get("provider", "Payme")}


@app.post("/api/wallet/topup/confirm")
async def topup_confirm(req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    b = await req.json()
    p = _pay.get(b.get("payment_id"))
    if not p or p["user"] != u["id"] or p["code"] != b.get("code") or time.time() - p["ts"] > 600:
        raise HTTPException(400, "Неверный код подтверждения")
    _pay.pop(b["payment_id"])
    with tx() as c:
        post(c, SYS["bank"], acct(u["id"], "wallet"), p["amount"], "topup", b["payment_id"],
             f"Пополнение с карты •••• {p['card']}")
    return {"ok": True, "wallet": balances(u["id"])}


@app.get("/api/wallet")
def wallet(authorization: str = Header(None)):
    u = user_from(authorization)
    rows = q("select * from ledger where debit like ? or credit like ? order by id desc limit 60",
             u["id"] + ":%", u["id"] + ":%")
    for r in rows:
        r["sign"] = 1 if r["credit"].startswith(u["id"]) else -1
        r["internal"] = r["debit"].startswith(u["id"]) and r["credit"].startswith(u["id"])
    return {"balances": balances(u["id"]), "ledger": rows}


# ------------------------------------------------------------------ market
@app.get("/api/market")
def market_list():
    out = []
    for k, ins in INSTRUMENTS.items():
        c = market.candles(k)
        cur = market.last_price(k)
        prev = c[-2]["close"] if len(c) > 1 else cur
        nxt = q1("select * from sessions where instrument=? and status in ('scheduled','open') order by opens_at limit 1", k)
        out.append({"key": k, **{f: ins[f] for f in ("name_ru", "name_uz", "unit", "lot", "deposit")}, "price": cur,
                    "change_pct": round(100 * (cur - prev) / prev, 2), "spark": [x["close"] for x in c[-26:]],
                    "next": nxt and {"opens_at": nxt["opens_at"], "status": nxt["status"], "offered": nxt["offered"],
                                     "start_price": nxt["start_price"]},
                    "anchor": market.load_history()[k]["anchor"] and {kk: market.load_history()[k]["anchor"][kk]
                                                                      for kk in ("price", "date", "source")}})
    return {"instruments": out, "server_time": now()}


@app.get("/api/market/{key}")
def market_one(key: str):
    if key not in INSTRUMENTS:
        raise HTTPException(404)
    sessions = q("select s.*, u.name seller_name, u.region seller_region from sessions s join users u on u.id=s.seller "
                 "where instrument=? order by opens_at desc limit 12", key)
    for s in sessions:
        s["explain"] = json.loads(s["explain"] or "null")
        if s["status"] == "open":
            o = q("select price, qty, pool_id from orders where session_id=? and side='buy' and status='open'", s["id"])
            book = {}
            for x in o:
                book[x["price"]] = book.get(x["price"], 0) + x["qty"]
            s["book"] = sorted(book.items(), reverse=True)[:12]
            s["pools"] = len({x["pool_id"] for x in o if x["pool_id"]})
    return {"key": key, **INSTRUMENTS[key], "candles": market.candles(key), "forecast": market.forecast(key, 8),
            "recommendation": market.recommend(key, "buy", 6), "sessions": sessions, "server_time": now(),
            "anchor": market.load_history()[key]["anchor"]}


@app.get("/api/calendar")
def calendar():
    rows = q("select s.id, s.instrument, s.opens_at, s.closes_at, s.status, s.offered, s.start_price, u.name seller "
             "from sessions s join users u on u.id=s.seller where s.status in ('scheduled','open') order by opens_at limit 24")
    return {"sessions": rows, "server_time": now()}


# ------------------------------------------------------------------ mandates
@app.get("/api/mandates")
def mandates(authorization: str = Header(None)):
    u = user_from(authorization)
    return {"mandates": q("select * from mandates where user_id=? and status!='draft' order by created_at desc", u["id"])}


@app.get("/api/mandates/{mid}")
def mandate_get(mid: str, authorization: str = Header(None)):
    u = user_from(authorization)
    m = q1("select * from mandates where id=? and user_id=?", mid, u["id"])
    if not m:
        raise HTTPException(404)
    return m


@app.post("/api/mandates")
async def mandate_create(req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    b = await req.json()
    r = agent.t_propose(u, b.get("side", "buy"), b.get("instrument"), b.get("qty", 0), b.get("limit_price", 0), b.get("deadline_days", 7),
                        b.get("strategy", "smart"), "создано с экрана рынка")
    if r.get("error"):
        raise HTTPException(400, r["error"])
    return r


@app.get("/api/deals/{did}/scale")
def deal_scale(did: str, authorization: str = Header(None)):
    """Buyer-side weighbridge reading (sandbox scale). The truck's real cargo depends on what happened on the road."""
    u = user_from(authorization)
    d = q1("select * from deals where id=? and buyer=?", did, u["id"])
    if not d or d["status"] != "delivered":
        raise HTTPException(400, "Машина ещё не на весах")
    flags = json.loads(d["flags"] or "{}")
    net = d["loaded_qty"] * (0.94 if flags.get("scenario") == "transit_loss" else 1.0)
    net = round(net + random.uniform(-0.01, 0.01) * (0 if flags.get("scenario") == "transit_loss" else 0.2), 3)
    tare = round(random.uniform(13.2, 15.8), 2)
    return {"net_t": net, "tare_t": tare, "gross_t": round(net + tare, 3), "truck": d["truck"], "ticket_no": f"VT-{random.randint(10000, 99999)}",
            "scale": "Весы покупателя № 2 (поверка до 2027)"}


@app.post("/api/mandates/{mid}/confirm")
async def mandate_confirm(mid: str, req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    b = await req.json()
    if not u["pin_hash"] or hash_pin(u["id"], str(b.get("pin", ""))) != u["pin_hash"]:
        raise HTTPException(403, "Неверный PIN")
    m = q1("select * from mandates where id=? and user_id=? and status='draft'", mid, u["id"])
    if not m:
        raise HTTPException(404, "Мандат не найден или уже подтверждён")
    if not u["verified_at"]:
        raise HTTPException(403, "Сначала пройдите проверку MyID")
    ins = INSTRUMENTS[m["instrument"]]
    if m["side"] == "sell" and u["status"] == "individual":
        raise HTTPException(403, "Продавать на бирже могут самозанятые, ИП и компании. Самозанятость оформляется за минуту")
    if u["status"] == "individual" and m["side"] == "buy":
        if m["instrument"] in ("propane", "ai92"):
            raise HTTPException(403, "Физлицам дефицитные товары недоступны (защита от перекупщиков)")
        if m["qty"] * m["limit_price"] > 50_000_000:
            raise HTTPException(403, "Лимит для физлица — 50 млн сум в месяц. Оформите самозанятость за минуту")
    with tx() as c:
        for k in ("qty", "limit_price"):
            if b.get(k):
                c.execute(f"update mandates set {k}=? where id=?", (int(b[k]), mid))
        m = q1("select * from mandates where id=?", mid)
        sig = docs.mandate_doc(c, u["id"], m)
        c.execute("update mandates set status='active', signature=? where id=?", (sig, mid))
        c.execute("insert into memory(user_id, kind, text, created_at) values(?,?,?,?)",
                  (u["id"], "feedback", f"Подтвердил мандат: {m['qty']} т {ins['name_ru']}, лимит {m['limit_price']} сум/т, "
                                         f"стратегия {m['strategy']}", now()))
        core.notify(c, u["id"], "mandate", "Мандат подписан и активен",
                    f"Агент будет покупать {m['qty']} т {ins['name_ru']} не дороже {m['limit_price']:,} сум/т."
                    .replace(",", " "), "/agent")
    return {"ok": True, "signature": sig[:24] + "…"}


@app.post("/api/mandates/{mid}/cancel")
def mandate_cancel(mid: str, authorization: str = Header(None)):
    u = user_from(authorization)
    with tx() as c:
        c.execute("update mandates set status='cancelled' where id=? and user_id=? and status in ('active','draft')",
                  (mid, u["id"]))
    return {"ok": True}


# ------------------------------------------------------------------ deals
def _deal_view(d, me_id=None):
    d = dict(d)
    d["name"] = INSTRUMENTS[d["instrument"]]["name_ru"]
    for f in ("buyer", "seller"):
        p = q1("select name, company, region from users where id=?", d[f])
        d[f + "_info"] = p
    d["role"] = "buyer" if d["buyer"] == me_id else "seller" if d["seller"] == me_id else "observer"
    d["gps"] = json.loads(d["gps"]) if d["gps"] else None
    d["flags"] = json.loads(d["flags"] or "{}")
    return d


@app.get("/api/deals")
def deals(authorization: str = Header(None)):
    u = user_from(authorization)
    rows = q("select * from deals where buyer=? or seller=? order by created_at desc limit 50", u["id"], u["id"])
    return {"deals": [_deal_view(d, u["id"]) for d in rows]}


@app.get("/api/deals/{did}")
def deal(did: str, authorization: str = Header(None)):
    u = user_from(authorization)
    d = q1("select * from deals where id=?", did)
    if not d or (u["id"] not in (d["buyer"], d["seller"]) and u["role"] != "operator"):
        raise HTTPException(404)
    ev = q("select * from events where deal_id=? order by id", did)
    for e in ev:
        e["payload"] = json.loads(e["payload"])
    dsp = q1("select * from disputes where deal_id=? order by created_at desc limit 1", did)
    if dsp and dsp.get("decision"):
        dsp["decision"] = json.loads(dsp["decision"])
    s = q1("select * from sessions where id=?", d["session_id"])
    return {"deal": _deal_view(d, u["id"]), "events": ev, "chain": core.verify_chain(did),
            "documents": q("select id, kind, title, hash, created_at from documents where deal_id=? order by created_at", did),
            "dispute": dsp, "session": s and {k: s[k] for k in ("id", "clearing_price", "matched", "demand", "offered")},
            "route": {"from": REGIONS.get(_deal_view(d)["seller_info"]["region"]),
                      "to": REGIONS.get(_deal_view(d)["buyer_info"]["region"])},
            "windows": {"pay": engine.PAY, "accept": engine.ACCEPT, "transit": engine.TRANSIT}, "server_time": now()}


VISION_PROMPT = """Это фото весового талона (или накладной) с автомобильных весов. Извлеки данные и верни ТОЛЬКО JSON:
{"net_t": число тонн нетто или null, "gross_t": брутто или null, "tare_t": тара или null, "ticket_no": "...",
"truck": "госномер если виден", "date": "...", "readable": true/false, "confidence": 0..1, "note": "коротко"}
Если вес в кг — переведи в тонны. Не выдумывай: нечитаемое поле = null."""


@app.post("/api/deals/{did}/scan")
async def deal_scan(did: str, req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    if limited("scan:" + u["id"], 20):
        raise HTTPException(429, "Слишком много сканов")
    d = q1("select * from deals where id=? and buyer=?", did, u["id"])
    if not d:
        raise HTTPException(404)
    b = await req.json()
    m = re.match(r"data:(image/\w+);base64,(.+)", b.get("image", ""), re.S)
    if not m:
        raise HTTPException(400, "Нужно изображение")
    msg = agent.client().messages.create(model=agent.MODEL, max_tokens=500, messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)}},
        {"type": "text", "text": VISION_PROMPT}]}])
    txt = "".join(x.text for x in msg.content if x.type == "text")
    try:
        data = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    except Exception:  # noqa: BLE001
        data = {"readable": False, "note": txt[:200]}
    data["image_hash"] = hashlib.sha256(m.group(2).encode()).hexdigest()
    data["contract_qty"] = d["qty"]
    return data


@app.post("/api/deals/{did}/receive")
async def deal_receive(did: str, req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    d = q1("select * from deals where id=? and buyer=?", did, u["id"])
    if not d:
        raise HTTPException(404)
    b = await req.json()
    w = float(b.get("weight", 0))
    if w <= 0 or w > d["qty"] * 1.5:
        raise HTTPException(400, "Проверьте вес")
    ev = {k: b[k] for k in ("image_hash", "ticket_no", "method") if b.get(k)}
    return engine.receive(did, w, b.get("method", "manual"), ev)


@app.post("/api/disputes/{dsp}/accept")
def dispute_accept(dsp: str, authorization: str = Header(None)):
    u = user_from(authorization)
    r = arbitration.accept(dsp, u["id"], operator=u["role"] == "operator")
    if r.get("error"):
        raise HTTPException(400, r["error"])
    return r


# ------------------------------------------------------------------ documents (public verification by QR)
@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def doc_page(doc_id: str, request: Request):
    return docs.render(doc_id, str(request.base_url).rstrip("/"))


@app.get("/verify/{doc_id}", response_class=HTMLResponse)
def verify_page(doc_id: str, request: Request):
    return docs.render(doc_id, str(request.base_url).rstrip("/"))


@app.get("/api/verify/{doc_id}")
def verify_api(doc_id: str):
    v = docs.check(doc_id)
    v.pop("doc", None)
    return v


# ------------------------------------------------------------------ notifications & live stream
@app.get("/api/notifications")
def notifications(authorization: str = Header(None)):
    u = user_from(authorization)
    rows = q("select * from notifications where user_id=? order by id desc limit 50", u["id"])
    with tx() as c:
        c.execute("update notifications set read=1 where user_id=?", (u["id"],))
    return {"notifications": rows}


@app.get("/api/stream")
def stream(token: str):
    u = q1("select id from users where token=?", token)
    if not u:
        raise HTTPException(401)
    qq: queue.Queue = queue.Queue(maxsize=200)
    core.subscribe(u["id"], qq)

    def gen():
        try:
            yield "data: {\"type\":\"hello\"}\n\n"
            while True:
                try:
                    ev = qq.get(timeout=15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            core.unsubscribe(u["id"], qq)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache",
                                                                             "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ agent chat
@app.post("/api/chat")
async def chat(req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    if limited("chat:" + u["id"], 60):
        raise HTTPException(429, "Слишком много сообщений")
    b = await req.json()
    msg = (b.get("message") or "").strip()[:2000]
    if not msg:
        raise HTTPException(400)

    def gen():
        try:
            for ev in agent.run(u, msg, b.get("lang", "ru")):
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:300]})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/agent/memory")
def agent_memory(authorization: str = Header(None)):
    u = user_from(authorization)
    stats = q("select instrument, count(*) n, sum(filled) bought, avg(limit_price) avg_limit, "
              "sum(case when strategy='smart' then 1 else 0 end) smart from mandates where user_id=? and status!='draft' "
              "group by 1", u["id"])
    return {"memory": q("select * from memory where user_id=? order by id desc", u["id"]), "stats": stats,
            "agent": q1("select * from agents where user_id=?", u["id"])}


@app.delete("/api/agent/memory/{mid}")
def agent_forget(mid: int, authorization: str = Header(None)):
    u = user_from(authorization)
    with tx() as c:
        c.execute("delete from memory where id=? and user_id=?", (mid, u["id"]))
    return {"ok": True}


@app.get("/api/chat/history")
def chat_history(authorization: str = Header(None)):
    u = user_from(authorization)
    return {"messages": q("select role, content, ts from chat where user_id=? order by id desc limit 30", u["id"])[::-1]}


# ------------------------------------------------------------------ exchange operator / regulator console
_integrity_cache = {}


@app.get("/api/ops/overview")
def ops_overview():
    t = now()
    return {
        "sessions_today": q1("select count(*) n, coalesce(sum(matched),0) t, coalesce(sum(matched*clearing_price),0) v "
                             "from sessions where status='cleared'"),
        "open": q("select * from sessions where status='open'"),
        "deals_by_status": q("select status, count(*) n from deals group by 1"),
        "users": q1("select count(*) n from users where role='user'")["n"],
        "agents": q1("select count(*) n from agents")["n"],
        "mandates": q("select status, count(*) n from mandates group by 1"),
        "pools": q1("select count(distinct pool_id) n from orders where pool_id is not null")["n"],
        "disputes": q("select d.*, dl.instrument, dl.qty, dl.amount from disputes d join deals dl on dl.id=d.deal_id "
                      "order by (dl.buyer like 'bot_%'), d.created_at desc limit 12"),
        "fees": {k: q1("select balance from accounts where id=?", v) for k, v in SYS.items()},
        "recent": q("select id, instrument, clearing_price, matched, demand, bidders, closes_at from sessions where "
                    "status='cleared' order by closes_at desc limit 12"),
        "scenario": engine._demo["next_scenario"], "server_time": t,
    }


@app.get("/api/ops/integrity")
def ops_integrity():
    if _integrity_cache:
        return _integrity_cache
    con = duckdb.connect(str(core.HISTORY_DB), read_only=True)
    sq = lambda s: con.execute(s).fetchall()
    serial = sq("""select buyer_inn, any_value(b.name), count(*) n, sum(amount_uzs) s from deals d
                   left join participants b on b.inn=d.buyer_inn
                   left join (select deal_id, amount_uzs from v_deals) v using(deal_id)
                   where status='Аннулирован(Не оплачен)' group by 1 having count(*)>=30 order by n desc limit 10""")
    total_serial = sq("""select count(*) from (select buyer_inn from deals where status='Аннулирован(Не оплачен)'
                         group by 1 having count(*)>=30)""")[0][0]
    share = sq("select round(100.0*avg((status='Аннулирован(Не оплачен)')::int),1) from deals")[0][0]
    conc = sq("""with b as (select buyer_inn, sum(amount_uzs) s from v_deals where is_valid group by 1),
                 r as (select s, ntile(100) over (order by s desc) p from b)
                 select round(100*sum(s) filter (where p=1)/sum(s),1) from r""")[0][0]
    small = sq("select round(median(amount_uzs)/1e6,1), round(100.0*avg((amount_uzs<20e6)::int),1) from v_deals where is_valid")[0]
    dep = sq("""with t as (select seller_inn, buyer_inn, sum(amount_uzs) s from v_deals where is_valid group by all),
                tot as (select seller_inn, sum(s) ts from t group by 1)
                select t.seller_inn, any_value(sp.name), t.buyer_inn, any_value(bp.name), round(100*max(s/ts),1) share, round(max(ts)/1e9,1)
                from t join tot using(seller_inn) left join participants sp on sp.inn=t.seller_inn
                left join participants bp on bp.inn=t.buyer_inn where ts>5e9 group by all order by share desc limit 8""")
    _integrity_cache.update({
        "serial_nonpayers": [{"inn": r[0], "name": r[1], "annulled": r[2], "amount_bln": round((r[3] or 0) / 1e9, 1)} for r in serial],
        "serial_count": total_serial, "annulled_share_pct": share, "top1pct_share": conc,
        "median_deal_mln": small[0], "small_deal_share_pct": small[1],
        "dependency": [{"seller": r[1], "seller_inn": r[0], "buyer": r[3], "buyer_inn": r[2], "share_pct": r[4],
                        "seller_turnover_bln": r[5]} for r in dep],
        "source": "реестр 500 000 сделок 2022–2026 (данные хакатона)"})
    con.close()
    return _integrity_cache


@app.post("/api/ops/scenario")
async def ops_scenario(req: Request):
    b = await req.json()
    s = b.get("scenario")
    if s not in ("normal", "short_loading", "transit_loss", "no_shipment"):
        raise HTTPException(400)
    engine.set_next_scenario(s)
    return {"next_scenario": s}


@app.post("/api/ops/disputes/{dsp}/approve")
def ops_approve(dsp: str):
    r = arbitration.accept(dsp, "operator", operator=True)
    if r.get("error"):
        raise HTTPException(400, r["error"])
    return r


@app.get("/api/legal")
def legal():
    base = dict(arbitration.legal_base())
    try:
        lu = json.load(open(Path(__file__).with_name("data") / "legal_uz.json", encoding="utf-8"))
        extra = [{"code": x.get("law", "")[:70], "article": x.get("article", ""), "summary": x.get("rule") or x.get("title", ""),
                  "url": x.get("source_url")} for x in lu.get("penalties", []) if x.get("verified") in (True, "true")]
        have = {(n.get("article"), (n.get("code") or "")[:12]) for n in base.get("norms", [])}
        base["norms"] = base.get("norms", []) + [e for e in extra if (e["article"], e["code"][:12]) not in have][:20]
        base["claim_procedure"] = lu.get("claim_procedure", [])
    except Exception:  # noqa: BLE001
        pass
    return base


@app.exception_handler(ValueError)
def value_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ------------------------------------------------------------------ v2: home, alerts, forwards, selling, analytics
@app.get("/api/home")
def home(authorization: str = Header(None)):
    u = user_from(authorization)
    me_deals = q("select * from deals where buyer=? or seller=? order by created_at desc limit 200", u["id"], u["id"])
    saved, bought_t, sold_t = 0, 0, 0
    for d in me_deals:
        if d["status"] in ("annulled",):
            continue
        ref = q1("select avg(clearing_price) p from sessions where instrument=? and status='cleared' and clearing_price>0 "
                 "and closes_at between ? and ?", d["instrument"], d["created_at"] - 3600, d["created_at"] + 3600)["p"]
        if ref and d["buyer"] == u["id"]:
            saved += (ref - d["price"]) * d["qty"]
            bought_t += d["qty"]
        elif ref and d["seller"] == u["id"]:
            saved += (d["price"] - ref) * d["qty"]
            sold_t += d["qty"]
    active = [d for d in me_deals if d["status"] not in ("settled", "resolved", "annulled")]
    interests = {m["instrument"] for m in q("select instrument from mandates where user_id=?", u["id"])}
    interests |= {a["instrument"] for a in q("select instrument from alerts where user_id=? and active=1", u["id"])}
    a = q1("select profile from agents where user_id=?", u["id"])
    interests |= set((json.loads(a["profile"] or "{}").get("interests") or []) if a else [])
    up = q("select s.id, s.instrument, s.opens_at, s.status, s.offered, s.start_price, u.name seller from sessions s "
           "join users u on u.id=s.seller where s.status in ('scheduled','open') order by s.opens_at limit 40")
    return {"wallet": balances(u["id"]), "saved": round(saved), "bought_t": bought_t, "sold_t": sold_t,
            "deals_total": len(me_deals), "active_deals": [_deal_view(d, u["id"]) for d in active[:6]],
            "mandates": q("select * from mandates where user_id=? and status='active' order by created_at desc", u["id"]),
            "upcoming": [x for x in up if x["instrument"] in interests][:6] or up[:6], "interests": sorted(interests),
            "index": market.index(), "server_time": now()}


@app.get("/api/index")
def commodity_index():
    return market.index()


@app.get("/api/market/{key}/seasonality")
def seasonality(key: str):
    if key not in INSTRUMENTS:
        raise HTTPException(404)
    return market.seasonality(key)


@app.get("/api/alerts")
def alerts_list(authorization: str = Header(None)):
    u = user_from(authorization)
    return {"alerts": q("select * from alerts where user_id=? order by id desc", u["id"])}


@app.post("/api/alerts")
async def alerts_add(req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    b = await req.json()
    if b.get("instrument") not in INSTRUMENTS or b.get("kind") not in ("session", "below", "above"):
        raise HTTPException(400, "Неверная подписка")
    with tx() as c:
        c.execute("insert into alerts(user_id, instrument, kind, value, created_at) values(?,?,?,?,?)",
                  (u["id"], b["instrument"], b["kind"], int(b.get("value") or 0), now()))
    return {"ok": True}


@app.delete("/api/alerts/{aid}")
def alerts_del(aid: int, authorization: str = Header(None)):
    u = user_from(authorization)
    with tx() as c:
        c.execute("delete from alerts where id=? and user_id=?", (aid, u["id"]))
    return {"ok": True}


@app.post("/api/forward/quote")
async def forward_quote(req: Request):
    b = await req.json()
    if b.get("instrument") not in INSTRUMENTS:
        raise HTTPException(400)
    return engine.forward_quote(b["instrument"], int(b.get("qty", 10)), max(1, min(8, int(b.get("weeks", 4)))))


@app.post("/api/forward/create")
async def forward_create(req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    b = await req.json()
    if not u["pin_hash"] or hash_pin(u["id"], str(b.get("pin", ""))) != u["pin_hash"]:
        raise HTTPException(403, "Неверный PIN")
    if u["status"] == "individual":
        raise HTTPException(403, "Фиксация цены доступна самозанятым, ИП и компаниям")
    key, qty, weeks = b.get("instrument"), int(b.get("qty", 0)), max(1, min(8, int(b.get("weeks", 4))))
    if key not in INSTRUMENTS or qty < INSTRUMENTS[key]["lot"]:
        raise HTTPException(400, f"Минимальный объём — {INSTRUMENTS.get(key, {}).get('lot', 1)} т")
    did = engine.create_forward(u["id"], key, qty, weeks)
    return {"deal_id": did}


@app.post("/api/deals/{did}/load")
async def deal_load(did: str, req: Request, authorization: str = Header(None)):
    u = user_from(authorization)
    d = q1("select * from deals where id=? and seller=?", did, u["id"])
    if not d:
        raise HTTPException(404)
    b = await req.json()
    qty = float(b.get("qty", 0))
    truck = re.sub(r"\s+", " ", (b.get("truck") or "").upper()).strip()
    seal = (b.get("seal") or "").strip().upper()
    if qty <= 0 or qty > d["qty"] * 1.2:
        raise HTTPException(400, "Проверьте вес погрузки")
    if not re.fullmatch(r"\d{2} ?[A-Z]?\d{3}[A-Z]{2,3}", truck.replace(" ", "")[:2] + " " + truck.replace(" ", "")[2:]) and len(truck) < 6:
        raise HTTPException(400, "Госномер машины, например 01 A123BC")
    if len(seal) < 4:
        raise HTTPException(400, "Номер пломбы")
    r = engine.load(did, qty, truck, seal, u["id"], {k: b[k] for k in ("image_hash",) if b.get(k)})
    if r.get("error"):
        raise HTTPException(400, r["error"])
    return r


@app.get("/api/deals/{did}/statutory")
def deal_statutory(did: str, authorization: str = Header(None)):
    u = user_from(authorization)
    d = q1("select * from deals where id=? and (buyer=? or seller=?)", did, u["id"], u["id"])
    if not d:
        raise HTTPException(404)
    return {"sanctions": arbitration.statutory(did), "precedents": arbitration.precedents_for(
        (q1("select reason from disputes where deal_id=?", did) or {}).get("reason", "non_delivery"))}


@app.post("/api/deals/{did}/claim")
def deal_claim(did: str, authorization: str = Header(None)):
    u = user_from(authorization)
    if limited("claim:" + u["id"], 10):
        raise HTTPException(429, "Слишком много претензий")
    return {"doc_id": arbitration.claim(did, u["id"])}


# ------------------------------------------------------------------ v3: production integrations
@app.post("/api/payme")
async def payme_endpoint(req: Request):
    return JSONResponse(integrations.payme_rpc(req.headers.get("authorization"), await req.json()))


@app.post("/api/click/{stage}")
async def click_endpoint(stage: str, req: Request):
    form = dict(await req.form())
    return JSONResponse(integrations.click_callback(form, complete=(stage == "complete")))


@app.get("/api/kyc/myid/start")
def myid_start(authorization: str = Header(None)):
    u = user_from(authorization)
    if not integrations.mode()["myid"]:
        return {"mode": "sandbox"}
    state = secrets.token_urlsafe(16)
    _otp["myid:" + state] = (u["id"], time.time())
    return {"mode": "live", "url": integrations.myid_authorize_url(state, os.environ.get("PUBLIC_URL", "") + "/myid/callback")}


@app.get("/myid/callback")
def myid_callback(code: str, state: str):
    uid_, ts = _otp.pop("myid:" + state, (None, 0))
    if not uid_ or time.time() - ts > 600:
        raise HTTPException(400, "Сессия MyID истекла")
    prof = integrations.myid_profile(code)
    with tx() as c:
        c.execute("update users set pinfl=?, name=?, verified_at=? where id=?", (prof["pinfl"], prof["name"], now(), uid_))
    return HTMLResponse('<script>location.href="/#/home"</script>')


@app.post("/api/telegram/link")
def telegram_link(authorization: str = Header(None)):
    u = user_from(authorization)
    if not integrations.mode()["telegram"]:
        return {"mode": "off", "note": "Telegram-бот уведомлений не подключён на этом сервере"}
    tok = integrations.tg_link_token(u["id"])
    return {"mode": "live", "url": f"https://t.me/{os.environ.get('TELEGRAM_BOT_USERNAME', 'zenc_ai')}?start={tok}"}


@app.get("/api/ops/integrations")
def ops_integrations():
    spec = json.load(open(Path(__file__).with_name("data") / "integrations.json", encoding="utf-8"))
    m = integrations.mode()
    keymap = {"payme": "payme", "click": "click", "eskiz_sms": "sms", "myid": "myid", "telegram_bot": "telegram"}
    return {"mode": m, "integrations": [{"key": i["key"], "name": i["name"], "purpose": i["purpose"], "docs_url": i["docs_url"],
                                          "verified": i["verified"], "live": m.get(keymap.get(i["key"], ""), False),
                                          "implemented": i["key"] in keymap} for i in spec["integrations"]],
            "compliance": [
                {"item": "Локализация данных (ЗРУ-547, ст.27¹ в ред. ЗРУ-1125 от 26.03.2026): биометрия — только в Узбекистане", "status": "done",
                 "how": "Платформа не хранит биометрию: селфи проверяет MyID, у нас только SHA-256 хеш. Для гос. запуска база — в UzCloud"},
                {"item": "Согласие на обработку персональных данных при регистрации", "status": "done", "how": "Шаг онбординга"},
                {"item": "Электронная подпись документов", "status": "partial",
                 "how": "Ed25519 внутри платформы; ЗРУ-793 допускает облачную подпись при двухфакторной аутентификации (PIN + устройство). ЭСФ/ЭТТН — через оператора ЭДО (Didox) с E-IMZO"},
                {"item": "Идентификация клиентов (ПОД/ФТ)", "status": "partial", "how": "MyID OAuth2 подключается ключами MYID_CLIENT_ID/SECRET"},
                {"item": "Приём платежей", "status": "ready", "how": "Payme Merchant API и Click SHOP API реализованы; нужны ключи кассы"},
                {"item": "Допуск физлиц и самозанятых к торгам", "status": "regulatory",
                 "how": "Изменение Правил биржевой торговли (п.1, 4): прецеденты agro.uzex.uz и MOBILRAQAM"},
            ]}
