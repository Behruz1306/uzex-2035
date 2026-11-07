"""Production integrations (live when credentials are configured, sandbox otherwise):
Payme Merchant API (JSON-RPC), Click SHOP API, Eskiz SMS, MyID OAuth2, Telegram notifications.
Specs: app/data/integrations.json (gathered from official developer docs)."""
import base64
import hashlib
import json
import os
import secrets
import threading
import time

import httpx

from core import SYS, acct, now, post, q, q1, tx, uid

ENV = os.environ.get


def mode() -> dict:
    return {
        "payme": bool(ENV("PAYME_MERCHANT_ID") and ENV("PAYME_KEY")),
        "click": bool(ENV("CLICK_SERVICE_ID") and ENV("CLICK_MERCHANT_ID") and ENV("CLICK_SECRET_KEY")),
        "sms": bool(ENV("ESKIZ_EMAIL") and ENV("ESKIZ_PASSWORD")),
        "myid": bool(ENV("MYID_CLIENT_ID") and ENV("MYID_CLIENT_SECRET")),
        "telegram": bool(ENV("TELEGRAM_BOT_TOKEN")) and ENV("RUN_TGBOT", "0") == "1",
        "anthropic": bool(ENV("ANTHROPIC_API_KEY")),
    }


SCHEMA = """
create table if not exists payments(id text primary key, user_id text, provider text, amount integer, state integer,
  ext_id text unique, create_time integer, perform_time integer, cancel_time integer, reason integer, created_at real);
create table if not exists tg_links(token text primary key, user_id text, created_at real);
"""


def init():
    from core import conn
    conn().executescript(SCHEMA)
    for ddl in ("alter table users add column tg_chat integer",):
        try:
            conn().execute(ddl)
        except Exception:  # noqa: BLE001
            pass


def new_payment(user_id: str, provider: str, amount: int) -> str:
    pid = uid("PAY")
    with tx() as c:
        c.execute("insert into payments(id, user_id, provider, amount, state, created_at) values(?,?,?,?,?,?)",
                  (pid, user_id, provider, amount, 0, now()))
    return pid


def _credit(c, p):
    post(c, SYS["bank"], acct(p["user_id"], "wallet"), p["amount"], "topup", p["id"], f"Пополнение через {p['provider']}")


# ------------------------------------------------------------------ Payme
def payme_checkout_url(pid: str, amount_sum: int, return_url: str, lang: str = "ru") -> str:
    params = f"m={ENV('PAYME_MERCHANT_ID')};ac.order_id={pid};a={amount_sum * 100};c={return_url};l={lang}"
    host = "https://test.paycom.uz/" if ENV("PAYME_TEST", "1") == "1" else "https://checkout.paycom.uz/"
    return host + base64.b64encode(params.encode()).decode()


def _perr(rid, code, msg):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": {"ru": msg, "uz": msg, "en": msg}}}


def payme_rpc(auth_header: str | None, body: dict) -> dict:
    rid, method, p = body.get("id"), body.get("method"), body.get("params", {})
    expected = "Basic " + base64.b64encode(f"Paycom:{ENV('PAYME_KEY', '')}".encode()).decode()
    if not ENV("PAYME_KEY") or auth_header != expected:
        return _perr(rid, -32504, "Недостаточно привилегий")
    ms = lambda: int(time.time() * 1000)
    if method in ("CheckPerformTransaction", "CreateTransaction"):
        order = (p.get("account") or {}).get("order_id")
        pay = q1("select * from payments where id=? and provider='payme'", order)
        if not pay:
            return _perr(rid, -31050, "Заказ не найден")
        if pay["amount"] * 100 != int(p.get("amount", -1)):
            return _perr(rid, -31001, "Неверная сумма")
        if method == "CheckPerformTransaction":
            return {"jsonrpc": "2.0", "id": rid, "result": {"allow": pay["state"] in (0, 1)}}
        if pay["ext_id"] and pay["ext_id"] != p.get("id"):
            return _perr(rid, -31050, "Заказ уже оплачивается другой транзакцией")
        if not pay["ext_id"]:
            with tx() as c:
                c.execute("update payments set ext_id=?, state=1, create_time=? where id=?", (p["id"], ms(), pay["id"]))
            pay = q1("select * from payments where id=?", pay["id"])
        return {"jsonrpc": "2.0", "id": rid, "result": {"create_time": pay["create_time"], "transaction": pay["id"], "state": pay["state"]}}
    pay = q1("select * from payments where ext_id=?", p.get("id"))
    if not pay:
        return _perr(rid, -31003, "Транзакция не найдена")
    if method == "PerformTransaction":
        if pay["state"] == 1:
            with tx() as c:
                c.execute("update payments set state=2, perform_time=? where id=?", (ms(), pay["id"]))
                _credit(c, pay)
            pay = q1("select * from payments where id=?", pay["id"])
        if pay["state"] != 2:
            return _perr(rid, -31008, "Невозможно выполнить операцию")
        return {"jsonrpc": "2.0", "id": rid, "result": {"transaction": pay["id"], "perform_time": pay["perform_time"], "state": 2}}
    if method == "CancelTransaction":
        if pay["state"] in (1, 2):
            new_state = -1 if pay["state"] == 1 else -2
            with tx() as c:
                if pay["state"] == 2:
                    post(c, acct(pay["user_id"], "wallet"), SYS["bank"], pay["amount"], "refund", pay["id"], "Отмена платежа Payme")
                c.execute("update payments set state=?, cancel_time=?, reason=? where id=?", (new_state, ms(), p.get("reason"), pay["id"]))
            pay = q1("select * from payments where id=?", pay["id"])
        return {"jsonrpc": "2.0", "id": rid, "result": {"transaction": pay["id"], "cancel_time": pay["cancel_time"], "state": pay["state"]}}
    if method == "CheckTransaction":
        return {"jsonrpc": "2.0", "id": rid, "result": {k: pay[k] or 0 for k in ("create_time", "perform_time", "cancel_time")} |
                {"transaction": pay["id"], "state": pay["state"], "reason": pay["reason"]}}
    if method == "GetStatement":
        rows = q("select * from payments where provider='payme' and create_time between ? and ?", p.get("from", 0), p.get("to", 0))
        return {"jsonrpc": "2.0", "id": rid, "result": {"transactions": [
            {"id": r["ext_id"], "time": r["create_time"], "amount": r["amount"] * 100, "account": {"order_id": r["id"]},
             "create_time": r["create_time"], "perform_time": r["perform_time"] or 0, "cancel_time": r["cancel_time"] or 0,
             "transaction": r["id"], "state": r["state"], "reason": r["reason"]} for r in rows]}}
    return _perr(rid, -32601, "Метод не найден")


# ------------------------------------------------------------------ Click
def click_pay_url(pid: str, amount_sum: int, return_url: str) -> str:
    return (f"https://my.click.uz/services/pay?service_id={ENV('CLICK_SERVICE_ID')}&merchant_id={ENV('CLICK_MERCHANT_ID')}"
            f"&amount={amount_sum:.2f}&transaction_param={pid}&return_url={return_url}")


def click_callback(f: dict, complete: bool) -> dict:
    parts = [f.get("click_trans_id", ""), f.get("service_id", ""), ENV("CLICK_SECRET_KEY", ""), f.get("merchant_trans_id", "")]
    if complete:
        parts.append(f.get("merchant_prepare_id", ""))
    parts += [f.get("amount", ""), f.get("action", ""), f.get("sign_time", "")]
    base = {"click_trans_id": f.get("click_trans_id"), "merchant_trans_id": f.get("merchant_trans_id")}
    if hashlib.md5("".join(parts).encode()).hexdigest() != f.get("sign_string"):
        return base | {"error": -1, "error_note": "SIGN CHECK FAILED!"}
    pay = q1("select * from payments where id=? and provider='click'", f.get("merchant_trans_id"))
    if not pay:
        return base | {"error": -5, "error_note": "User does not exist"}
    if abs(float(f.get("amount", 0)) - pay["amount"]) > 0.01:
        return base | {"error": -2, "error_note": "Incorrect parameter amount"}
    if pay["state"] == 2:
        return base | {"error": -4, "error_note": "Already paid"}
    if not complete:
        with tx() as c:
            c.execute("update payments set state=1, ext_id=? where id=?", (f.get("click_trans_id"), pay["id"]))
        return base | {"merchant_prepare_id": pay["id"], "error": 0, "error_note": "Success"}
    if str(f.get("error", "0")) != "0":
        with tx() as c:
            c.execute("update payments set state=-1 where id=?", (pay["id"],))
        return base | {"merchant_confirm_id": pay["id"], "error": -9, "error_note": "Transaction cancelled"}
    with tx() as c:
        c.execute("update payments set state=2, perform_time=? where id=?", (int(time.time() * 1000), pay["id"]))
        _credit(c, pay)
    return base | {"merchant_confirm_id": pay["id"], "error": 0, "error_note": "Success"}


# ------------------------------------------------------------------ Eskiz SMS
_eskiz = {"token": None, "ts": 0}


def send_sms(phone: str, text: str) -> bool:
    if not mode()["sms"]:
        return False
    try:
        if not _eskiz["token"] or time.time() - _eskiz["ts"] > 20 * 86400:
            r = httpx.post("https://notify.eskiz.uz/api/auth/login", data={"email": ENV("ESKIZ_EMAIL"), "password": ENV("ESKIZ_PASSWORD")}, timeout=15)
            _eskiz.update(token=r.json()["data"]["token"], ts=time.time())
        r = httpx.post("https://notify.eskiz.uz/api/message/sms/send", headers={"Authorization": f"Bearer {_eskiz['token']}"},
                       data={"mobile_phone": phone, "message": text, "from": ENV("ESKIZ_FROM", "4546")}, timeout=15)
        return r.status_code < 300
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ MyID OAuth2
MYID = ENV("MYID_HOST", "https://devmyid.uz")


def myid_authorize_url(state: str, redirect_uri: str) -> str:
    return (f"{MYID}/api/v1/oauth2/authorization?client_id={ENV('MYID_CLIENT_ID')}&response_type=code&redirect_uri={redirect_uri}"
            f"&scope=common_data,doc_data&method=strong&state={state}")


def myid_profile(code: str) -> dict:
    t = httpx.post(f"{MYID}/api/v1/oauth2/access-token", data={"grant_type": "authorization_code", "code": code,
                   "client_id": ENV("MYID_CLIENT_ID"), "client_secret": ENV("MYID_CLIENT_SECRET")}, timeout=20).json()
    me = httpx.get(f"{MYID}/api/v1/users/me", headers={"Authorization": f"Bearer {t['access_token']}"}, timeout=20).json()
    cd = (me.get("profile") or {}).get("common_data") or {}
    return {"pinfl": cd.get("pinfl"), "name": f"{cd.get('first_name', '')} {cd.get('last_name', '')}".strip(), "raw": cd}


# ------------------------------------------------------------------ Telegram (link + notifications)
def tg_link_token(user_id: str) -> str:
    tok = secrets.token_urlsafe(12).replace("-", "_")
    with tx() as c:
        c.execute("insert into tg_links(token, user_id, created_at) values(?,?,?)", (tok, user_id, now()))
    return tok


def tg_send(chat_id: int, text: str):
    if not ENV("TELEGRAM_BOT_TOKEN"):
        return
    try:
        httpx.post(f"https://api.telegram.org/bot{ENV('TELEGRAM_BOT_TOKEN')}/sendMessage",
                   json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def on_notify(user_id, kind, title, body, link):
    u = q1("select tg_chat from users where id=?", user_id)
    if u and u.get("tg_chat") and mode()["telegram"]:
        base = ENV("PUBLIC_URL", "https://uzex-2035.fly.dev")
        threading.Thread(target=tg_send, args=(u["tg_chat"], f"<b>{title}</b>\n{body}" + (f"\n{base}/#{link}" if link else "")),
                         daemon=True).start()


def _tg_loop():
    api = f"https://api.telegram.org/bot{ENV('TELEGRAM_BOT_TOKEN')}/"
    offset = 0
    httpx.post(api + "deleteWebhook", timeout=10)
    while True:
        try:
            r = httpx.post(api + "getUpdates", json={"offset": offset, "timeout": 50, "allowed_updates": ["message"]}, timeout=70).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                m = u.get("message") or {}
                text, chat = (m.get("text") or "").strip(), m.get("chat", {}).get("id")
                if text.startswith("/start"):
                    tok = text.split(" ", 1)[1].strip() if " " in text else ""
                    link = q1("select * from tg_links where token=?", tok) if tok else None
                    if link:
                        with tx() as c:
                            c.execute("update users set tg_chat=? where id=?", (chat, link["user_id"]))
                            c.execute("delete from tg_links where token=?", (tok,))
                        tg_send(chat, "✅ Готово! Агент UZEX 2035 будет присылать сюда анонсы торгов, сделки, отгрузки и споры.")
                    else:
                        tg_send(chat, "Это бот уведомлений UZEX 2035. Привяжите аккаунт в приложении: «Мой агент» → «Уведомления в Telegram».")
        except Exception:  # noqa: BLE001
            time.sleep(5)


def start_telegram():
    if mode()["telegram"]:
        threading.Thread(target=_tg_loop, daemon=True, name="tg").start()
