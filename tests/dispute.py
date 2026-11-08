import sys, time, os, sqlite3, httpx, json
B = "http://localhost:8090"; c = httpx.Client(base_url=B, timeout=90)
j = lambda r: r.json() if r.status_code < 400 else (_ for _ in ()).throw(SystemExit(f"{r.status_code} {r.text}"))
r = j(c.post("/api/auth/start", json={"phone": "+998901234567"})); r = j(c.post("/api/auth/verify", json={"phone": "998901234567", "code": r["sandbox_sms"]}))
H = {"Authorization": "Bearer " + r["token"]}; uid_ = r["user"]["id"]
print(j(c.post("/api/ops/scenario", json={"scenario": sys.argv[1]}, headers={"Authorization": "Bearer " + os.environ.get("OPS_KEY", "test-ops")})))
db = sqlite3.connect("app/data/state.sqlite")
price = j(c.get("/api/market/sugar"))["candles"][-1]["vwap"]
mid = "M_d" + str(int(time.time()))
db.execute("insert into mandates(id,user_id,side,instrument,qty,limit_price,deadline,strategy,status,confirm_above,created_at) values(?,?,?,?,?,?,?,?,?,?,?)",
           (mid, uid_, "buy", "sugar", 10, int(price * 1.1), time.time() + 3600, "now", "draft", 0, time.time())); db.commit()
j(c.post(f"/api/mandates/{mid}/confirm", json={"pin": "1234"}, headers=H))
end = time.time() + 200; did = None
while time.time() < end:
    ds = [d for d in j(c.get("/api/deals", headers=H))["deals"] if d["mandate_id"] == mid]
    if ds:
        d = ds[0]; did = d["id"]
        if d["status"] == "delivered":
            got = round(d["loaded_qty"] * 0.94, 2) if sys.argv[1] == "transit_loss" else d["loaded_qty"]
            print("receive", got, j(c.post(f"/api/deals/{did}/receive", json={"weight": got}, headers=H)))
        if d["status"] == "disputed":
            dd = j(c.get(f"/api/deals/{did}", headers=H))
            if dd["dispute"] and dd["dispute"]["status"] in ("proposed", "needs_review"):
                dec = dd["dispute"]["decision"]
                print("FAULT", dec["summary"]); print("FINDINGS", json.dumps(dec["findings"], ensure_ascii=False))
                print("MOVES", dec["moves"]); print("REASONING", dec["reasoning"][:900])
                print("accept", j(c.post(f"/api/disputes/{dd['dispute']['id']}/accept", headers=H)))
        if d["status"] in ("resolved", "settled"):
            print("final", d["status"], j(c.get("/api/wallet", headers=H))["balances"]); break
    time.sleep(2)
