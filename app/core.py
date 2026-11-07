"""Core: state DB (SQLite), double-entry clearing ledger, Ed25519 signatures, hash-chained evidence, notifications."""
import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DATA = Path(os.environ.get("DATA_DIR", Path(__file__).with_name("data")))
STATE_DB = DATA / "state.sqlite"
HISTORY_DB = Path(__file__).with_name("data") / "history.duckdb"
_lock = threading.RLock()
_local = threading.local()

# ------------------------------------------------------------------ instruments
# lot = minimal tradable quantity on a session (tonnes). Smaller mandates are pooled.
INSTRUMENTS = {
    "cement":  {"name_ru": "Портландцемент 42,5Н (навал)", "name_uz": "Portlandsement 42,5N (toʻkma)", "unit": "т", "lot": 20,
                "family": "Цемент", "brand": None, "deposit": 0.10, "hist_mult": 1, "real": "cement"},
    "propane": {"name_ru": "Газ сжиженный", "name_uz": "Suyultirilgan gaz", "unit": "т", "lot": 5,
                "family": "Газ сжиженный", "brand": None, "deposit": 0.15, "hist_mult": 1, "real": "lpg"},
    "ai92":    {"name_ru": "Автобензин А-92", "name_uz": "A-92 avtobenzini", "unit": "т", "lot": 5,
                "family": "Бензин", "brand": "АИ-92", "deposit": 0.10, "hist_mult": 1, "hist_unit": "тонна",
                "real": "gasoline_ai92"},
    "pp":      {"name_ru": "Полипропилен Y130", "name_uz": "Polipropilen Y130", "unit": "т", "lot": 5,
                "family": "Полипропилен", "brand": None, "deposit": 0.15, "hist_mult": 1, "real": "polypropylene"},
    "urea":    {"name_ru": "Карбамид «Б» (удобрение)", "name_uz": "Karbamid «B» (oʻgʻit)", "unit": "т", "lot": 10,
                "family": "Карбамид", "brand": None, "deposit": 0.10, "hist_mult": 1, "real": "urea"},
    "wheat":   {"name_ru": "Пшеница 3 класс", "name_uz": "Bugʻdoy 3-sinf", "unit": "т", "lot": 20,
                "family": "Пшеница", "brand": None, "deposit": 0.10, "hist_mult": 1, "real": "wheat"},
    "sugar":   {"name_ru": "Сахар-песок ТС-2", "name_uz": "Shakar qumi TS-2", "unit": "т", "lot": 5,
                "family": "Сахар", "brand": None, "deposit": 0.10, "hist_mult": 1, "real": "sugar"},
    "rebar":   {"name_ru": "Арматура 12 мм Ст35ГС", "name_uz": "Armatura 12 mm St35GS", "unit": "т", "lot": 5,
                "family": "Арматура", "brand": None, "deposit": 0.10, "hist_mult": 1, "real": None, "anchor_real": "rebar"},
}
FEE_BUYER, FEE_SELLER, FEE_CLEARING = 0.0013, 0.0005, 0.0005   # UzEx tariffs from 01.10.2026

REGIONS = {  # region -> (lat, lon) of the regional centre, used for logistics/GPS
    "Toshkent shahri": (41.311, 69.279), "Toshkent viloyati": (41.003, 69.555), "Andijon viloyati": (40.783, 72.344),
    "Buxoro viloyati": (39.768, 64.421), "Fargʻona viloyati": (40.389, 71.784), "Jizzax viloyati": (40.116, 67.842),
    "Xorazm viloyati": (41.550, 60.631), "Namangan viloyati": (40.998, 71.672), "Navoiy viloyati": (40.103, 65.374),
    "Qashqadaryo viloyati": (38.861, 65.789), "Qoraqalpogʻiston Respublikasi": (42.460, 59.603),
    "Samarqand viloyati": (39.654, 66.976), "Sirdaryo viloyati": (40.484, 68.785), "Surxondaryo viloyati": (37.224, 67.278),
}


def now() -> float:
    return time.time()


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ------------------------------------------------------------------ database
SCHEMA = """
create table if not exists users(
  id text primary key, phone text, name text, pinfl text, status text, company text, inn text, region text,
  lang text default 'ru', verified_at real, selfie_hash text, pin_hash text, sign_pub text, sign_priv text,
  role text default 'user', token text, created_at real);
create table if not exists agents(user_id text primary key, name text, avatar text, profile text, created_at real);
create table if not exists memory(id integer primary key, user_id text, kind text, text text, created_at real);
create table if not exists chat(id integer primary key, user_id text, role text, content text, ts real);
create table if not exists accounts(id text primary key, owner text, kind text, balance integer default 0);
create table if not exists ledger(id integer primary key, ts real, debit text, credit text, amount integer,
  ref_type text, ref_id text, memo text);
create table if not exists sessions(id text primary key, instrument text, announce_at real, opens_at real, closes_at real,
  status text, seller text, offered integer, start_price integer, clearing_price integer, matched integer default 0,
  demand integer default 0, bidders integer default 0, explain text);
create table if not exists orders(id text primary key, session_id text, user_id text, side text, qty integer,
  price integer, mandate_id text, pool_id text, filled integer default 0, status text, ts real);
create table if not exists mandates(id text primary key, user_id text, side text, instrument text, qty integer,
  limit_price integer, deadline real, strategy text, status text, filled integer default 0, spent integer default 0,
  confirm_above integer, note text, created_at real, signature text);
create table if not exists deals(id text primary key, session_id text, instrument text, buyer text, seller text,
  qty integer, price integer, amount integer, deposit_buyer integer, deposit_seller integer, status text,
  pool_id text, mandate_id text, created_at real, pay_due real, ship_due real, deliver_eta real, accept_due real,
  loaded_qty real, delivered_qty real, carrier text, truck text, seal text, gps text, dispute_id text, flags text);
create table if not exists events(id integer primary key, deal_id text, ts real, type text, actor text,
  payload text, prev_hash text, hash text);
create table if not exists documents(id text primary key, deal_id text, kind text, title text, payload text,
  hash text, signatures text, created_at real);
create table if not exists disputes(id text primary key, deal_id text, opened_by text, reason text, status text,
  fault text, decision text, created_at real, resolved_at real);
create table if not exists notifications(id integer primary key, user_id text, ts real, kind text, title text,
  body text, link text, read integer default 0);
create table if not exists alerts(id integer primary key, user_id text, instrument text, kind text, value integer,
  active integer default 1, created_at real, fired_at real);
create index if not exists ix_orders_s on orders(session_id);
create index if not exists ix_deals_b on deals(buyer);
create index if not exists ix_deals_s on deals(seller);
create index if not exists ix_events_d on events(deal_id);
create index if not exists ix_notif_u on notifications(user_id, ts);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        DATA.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(STATE_DB, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("pragma journal_mode=wal")
        c.execute("pragma busy_timeout=30000")
        _local.c = c
    return c


def init_db():
    conn().executescript(SCHEMA)
    for ddl in ("alter table sessions add column reminded integer",):   # lightweight migrations for live DBs
        try:
            conn().execute(ddl)
        except sqlite3.OperationalError:
            pass


@contextmanager
def tx():
    """Serialized write transaction (single-process app)."""
    with _lock:
        c = conn()
        c.execute("begin immediate")
        try:
            yield c
            c.execute("commit")
        except Exception:
            c.execute("rollback")
            raise


def q(sql, *args):
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql, *args):
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


# ------------------------------------------------------------------ ledger (double entry, amounts in UZS)
SYS = {"bank": "sys:bank", "escrow": "sys:escrow", "fees": "sys:fees_exchange", "clearing": "sys:fees_clearing",
       "carrier": "sys:carrier_insurance"}


def acct(owner: str, kind: str) -> str:
    return f"{owner}:{kind}"


def ensure_accounts(c, owner: str):
    for k in ("wallet", "blocked"):
        c.execute("insert or ignore into accounts(id, owner, kind) values(?,?,?)", (acct(owner, k), owner, k))


def post(c, debit: str, credit: str, amount: int, ref_type: str, ref_id: str, memo: str):
    """Move `amount` from account `debit` to account `credit` (debit loses, credit gains)."""
    amount = int(round(amount))
    if amount <= 0:
        return
    for a in (debit, credit):
        c.execute("insert or ignore into accounts(id, owner, kind) values(?,?,?)",
                  (a, a.split(":")[0], a.split(":")[-1]))
    if not debit.startswith("sys:"):
        bal = c.execute("select balance from accounts where id=?", (debit,)).fetchone()[0]
        if bal < amount:
            raise ValueError(f"insufficient funds on {debit}: {bal} < {amount}")
    c.execute("update accounts set balance=balance-? where id=?", (amount, debit))
    c.execute("update accounts set balance=balance+? where id=?", (amount, credit))
    c.execute("insert into ledger(ts, debit, credit, amount, ref_type, ref_id, memo) values(?,?,?,?,?,?,?)",
              (now(), debit, credit, amount, ref_type, ref_id, memo))


def balances(owner: str) -> dict:
    rows = q("select kind, balance from accounts where owner=?", owner)
    d = {r["kind"]: r["balance"] for r in rows}
    return {"wallet": d.get("wallet", 0), "blocked": d.get("blocked", 0)}


# ------------------------------------------------------------------ signatures (Ed25519) and hashing
def new_keypair():
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(pub).decode(), base64.b64encode(priv).decode()


def sign(priv_b64: str, message: bytes) -> str:
    k = Ed25519PrivateKey.from_private_bytes(base64.b64decode(priv_b64))
    return base64.b64encode(k.sign(message)).decode()


def verify(pub_b64: str, message: bytes, sig_b64: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64)).verify(base64.b64decode(sig_b64), message)
        return True
    except Exception:  # noqa: BLE001
        return False


def canon(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_pin(user_id: str, pin: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), user_id.encode(), 120_000).hex()


# ------------------------------------------------------------------ evidence chain (per deal, tamper-evident)
def add_event(c, deal_id: str, type_: str, actor: str, payload: dict):
    prev = c.execute("select hash from events where deal_id=? order by id desc limit 1", (deal_id,)).fetchone()
    prev_hash = prev[0] if prev else "GENESIS"
    ts = now()
    h = sha(canon({"deal": deal_id, "ts": round(ts, 3), "type": type_, "actor": actor, "payload": payload,
                   "prev": prev_hash}))
    c.execute("insert into events(deal_id, ts, type, actor, payload, prev_hash, hash) values(?,?,?,?,?,?,?)",
              (deal_id, ts, type_, actor, json.dumps(payload, ensure_ascii=False), prev_hash, h))
    return h


def verify_chain(deal_id: str) -> dict:
    rows = q("select * from events where deal_id=? order by id", deal_id)
    prev = "GENESIS"
    for r in rows:
        h = sha(canon({"deal": deal_id, "ts": round(r["ts"], 3), "type": r["type"], "actor": r["actor"],
                       "payload": json.loads(r["payload"]), "prev": prev}))
        if r["prev_hash"] != prev or r["hash"] != h:
            return {"ok": False, "broken_at": r["id"], "events": len(rows)}
        prev = r["hash"]
    return {"ok": True, "events": len(rows), "head": prev}


# ------------------------------------------------------------------ notifications (+ SSE fan-out)
_subscribers: dict[str, list] = {}


def subscribe(user_id: str, queue):
    _subscribers.setdefault(user_id, []).append(queue)


def unsubscribe(user_id: str, queue):
    if queue in _subscribers.get(user_id, []):
        _subscribers[user_id].remove(queue)


def push(user_id: str, event: dict):
    for qq in list(_subscribers.get(user_id, [])):
        try:
            qq.put_nowait(event)
        except Exception:  # noqa: BLE001
            pass


def broadcast(event: dict):
    for uid_ in list(_subscribers):
        push(uid_, event)


NOTIFY_HOOKS = []


def notify(c, user_id: str, kind: str, title: str, body: str, link: str = ""):
    if not user_id or user_id.startswith("bot_"):
        return
    c.execute("insert into notifications(user_id, ts, kind, title, body, link) values(?,?,?,?,?,?)",
              (user_id, now(), kind, title, body, link))
    push(user_id, {"type": "notification", "kind": kind, "title": title, "body": body, "link": link})
    for hook in NOTIFY_HOOKS:
        try:
            hook(user_id, kind, title, body, link)
        except Exception:  # noqa: BLE001
            pass
