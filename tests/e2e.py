"""End-to-end API test of the full deal lifecycle (fast demo clock)."""
import base64, sys, time
import httpx
B = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090"
c = httpx.Client(base_url=B, timeout=60)
def j(r):
    if r.status_code >= 400: raise SystemExit(f"{r.request.url} -> {r.status_code} {r.text}")
    return r.json()
r = j(c.post("/api/auth/start", json={"phone": "+998 90 123 45 67"})); print("otp", r["sandbox_sms"])
r = j(c.post("/api/auth/verify", json={"phone": "+998901234567", "code": r["sandbox_sms"]}))
H = {"Authorization": "Bearer " + r["token"]}
selfie = "data:image/jpeg;base64," + base64.b64encode(b"x" * 6000).decode()
print(j(c.post("/api/kyc/myid", json={"pinfl": "31234567890123", "name": "Akmal Karimov", "selfie": selfie}, headers=H)))
print(j(c.post("/api/profile/status", json={"status": "ip", "inn": "312345678", "company": "IP Karimov", "region": "Namangan viloyati"}, headers=H)))
print(j(c.post("/api/agent/create", json={"name": "Baraka", "pin": "1234", "business": "nonvoyxona", "interests": ["flour", "cement"], "risk": "balanced", "lang": "ru"}, headers=H))["ok"])
p = j(c.post("/api/wallet/topup/start", json={"amount": 2_000_000_000, "card": "8600123412341234"}, headers=H))
print("wallet", j(c.post("/api/wallet/topup/confirm", json={"payment_id": p["payment_id"], "code": p["sandbox_sms"]}, headers=H))["wallet"])
# create mandate through the agent tool function directly (LLM-free test)
import importlib, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
mk = j(c.get("/api/market/cement"))
price = mk["candles"][-1]["vwap"]
print("cement price", price, "rec", mk["recommendation"]["action"])
import sqlite3, json
db = sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "app", "data", "state.sqlite"))
uid_ = j(c.get("/api/me", headers=H))["user"]["id"]
mid = "M_test" + str(int(time.time()))
db.execute("insert into mandates(id,user_id,side,instrument,qty,limit_price,deadline,strategy,status,confirm_above,created_at) values(?,?,?,?,?,?,?,?,?,?,?)",
           (mid, uid_, "buy", "cement", 40, int(price * 1.08), time.time() + 3600, "now", "draft", 0, time.time())); db.commit()
print(j(c.post(f"/api/mandates/{mid}/confirm", json={"pin": "1234"}, headers=H)))
deadline = time.time() + 180
seen = set()
while time.time() < deadline:
    ds = j(c.get("/api/deals", headers=H))["deals"]
    for d in ds:
        k = (d["id"], d["status"])
        if k not in seen:
            seen.add(k); print(time.strftime("%H:%M:%S"), d["id"], d["status"], d["qty"], d["price"])
        if d["status"] == "delivered":
            print("receive", j(c.post(f"/api/deals/{d['id']}/receive", json={"weight": d["qty"], "method": "manual"}, headers=H)))
    if ds and all(d["status"] in ("settled", "resolved", "annulled") for d in ds):
        break
    time.sleep(2)
dd = j(c.get(f"/api/deals/{ds[0]['id']}", headers=H))
print("chain", dd["chain"], "docs", [x["kind"] for x in dd["documents"]])
v = j(c.get(f"/api/verify/{dd['documents'][0]['id']}"))
print("verify contract", v["ok"], [s["valid"] for s in v["signatures"]])
w = j(c.get("/api/wallet", headers=H)); print("balances", w["balances"])
print("ops", j(c.get("/api/ops/overview"))["deals_by_status"])
