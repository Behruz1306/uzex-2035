import sys, time, base64, httpx
B = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090"
c = httpx.Client(base_url=B, timeout=90)
def j(r):
    if r.status_code >= 400: raise SystemExit(f"{r.request.url} -> {r.status_code} {r.text}")
    return r.json()
def user(phone, status, region, name):
    r = j(c.post("/api/auth/start", json={"phone": phone})); r = j(c.post("/api/auth/verify", json={"phone": phone, "code": r["sandbox_sms"]}))
    H = {"Authorization": "Bearer " + r["token"]}
    j(c.post("/api/kyc/myid", json={"pinfl": str(abs(hash(phone)))[:14].ljust(14, "7"), "name": name, "selfie": "data:image/jpeg;base64," + base64.b64encode(b"x" * 6000).decode()}, headers=H))
    j(c.post("/api/profile/status", json={"status": status, "region": region}, headers=H))
    j(c.post("/api/agent/create", json={"name": "A", "pin": "1234"}, headers=H))
    p = j(c.post("/api/wallet/topup/start", json={"amount": 3_000_000_000, "card": "8600123412341234"}, headers=H))
    j(c.post("/api/wallet/topup/confirm", json={"payment_id": p["payment_id"], "code": p["sandbox_sms"]}, headers=H))
    return H
# --- farmer sells wheat
F = user("+998911110001", "self_employed", "Jizzax viloyati", "Fermer Test")
price = j(c.get("/api/market/wheat"))["recommendation"]["current"]
m = j(c.post("/api/mandates", json={"side": "sell", "instrument": "wheat", "qty": 40, "limit_price": int(price * 0.97 // 1000 * 1000), "strategy": "now", "deadline_days": 1}, headers=F))
print("sell confirm", j(c.post(f"/api/mandates/{m['mandate_id']}/confirm", json={"pin": "1234"}, headers=F)))
# --- forward price lock (bakery)
K = user("+998911110002", "ip" if False else "self_employed", "Namangan viloyati", "Pekar Test")
qt = j(c.post("/api/forward/quote", json={"instrument": "sugar", "qty": 10, "weeks": 1}))
print("forward quote", qt["price"], qt["premium_pct"], qt["delivery_week"])
fw = j(c.post("/api/forward/create", json={"instrument": "sugar", "qty": 10, "weeks": 1, "pin": "1234"}, headers=K))
print("forward deal", fw)
t0 = time.time(); done = set()
while time.time() - t0 < 400:
    fd = j(c.get("/api/deals", headers=F))["deals"]
    for d in fd:
        if d["status"] == "paid" and d["id"] not in done:
            print("farmer loads", j(c.post(f"/api/deals/{d['id']}/load", json={"qty": d["qty"], "truck": "30 A777BC", "seal": "SEAL-0001"}, headers=F))); done.add(d["id"])
    kd = j(c.get("/api/deals", headers=K))["deals"]
    for d in kd:
        if d["status"] == "delivered":
            print("bakery receives", j(c.post(f"/api/deals/{d['id']}/receive", json={"weight": d["loaded_qty"]}, headers=K)))
    fs = {d["status"] for d in fd}; ks = {d["status"] for d in kd}
    print(time.strftime("%H:%M:%S"), "farmer", sorted(fs), "bakery", sorted(ks))
    if fd and fs <= {"settled", "resolved"} and ks <= {"settled", "resolved"} and kd:
        break
    time.sleep(6)
print("farmer wallet", j(c.get("/api/wallet", headers=F))["balances"], "home saved", j(c.get("/api/home", headers=F))["saved"])
