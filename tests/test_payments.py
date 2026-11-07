"""Payme JSON-RPC and Click SHOP API protocol tests against a throwaway DB."""
import base64, hashlib, os, sys, tempfile
os.environ.update(DATA_DIR=tempfile.mkdtemp(), PAYME_MERCHANT_ID="test", PAYME_KEY="secret123",
                  CLICK_SERVICE_ID="1", CLICK_MERCHANT_ID="2", CLICK_SECRET_KEY="sk")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import core, integrations as I  # noqa: E402
core.init_db(); I.init()
with core.tx() as c: core.ensure_accounts(c, "U1")
pid = I.new_payment("U1", "payme", 150000)
auth = "Basic " + base64.b64encode(b"Paycom:secret123").decode()
rpc = lambda m, p: I.payme_rpc(auth, {"id": 1, "method": m, "params": p})
assert I.payme_rpc("Basic xx", {"id": 1, "method": "CheckTransaction", "params": {}})["error"]["code"] == -32504
assert rpc("CheckPerformTransaction", {"amount": 1, "account": {"order_id": pid}})["error"]["code"] == -31001
assert rpc("CheckPerformTransaction", {"amount": 15000000, "account": {"order_id": pid}})["result"]["allow"]
assert rpc("CreateTransaction", {"id": "PM1", "time": 1, "amount": 15000000, "account": {"order_id": pid}})["result"]["state"] == 1
assert rpc("CreateTransaction", {"id": "PM1", "time": 1, "amount": 15000000, "account": {"order_id": pid}})["result"]["state"] == 1
assert rpc("PerformTransaction", {"id": "PM1"})["result"]["state"] == 2 and core.balances("U1")["wallet"] == 150000
assert rpc("PerformTransaction", {"id": "PM1"})["result"]["state"] == 2 and core.balances("U1")["wallet"] == 150000  # idempotent
assert rpc("CancelTransaction", {"id": "PM1", "reason": 5})["result"]["state"] == -2 and core.balances("U1")["wallet"] == 0
print("payme: auth, amount check, create (idempotent), perform (idempotent), cancel-after-perform refund — OK")
pid2 = I.new_payment("U1", "click", 50000)
f = {"click_trans_id": "777", "service_id": "1", "merchant_trans_id": pid2, "amount": "50000.00", "action": "0", "sign_time": "2026-11-07 15:00:00"}
f["sign_string"] = hashlib.md5(("7771sk" + pid2 + "50000.00" + "0" + f["sign_time"]).encode()).hexdigest()
assert I.click_callback(f, False)["error"] == 0
f2 = dict(f, action="1", merchant_prepare_id=pid2, error="0")
f2["sign_string"] = hashlib.md5(("7771sk" + pid2 + pid2 + "50000.00" + "1" + f["sign_time"]).encode()).hexdigest()
assert I.click_callback(f2, True)["error"] == 0 and core.balances("U1")["wallet"] == 50000
assert I.click_callback(dict(f2, sign_string="bad"), True)["error"] == -1
assert I.click_callback(f2, True)["error"] == -4   # already paid
print("click: md5 sign check, prepare, complete credits wallet, bad sign rejected, double-complete rejected — OK")
print("checkout url:", I.payme_checkout_url(pid, 150000, "https://uzex-2035.fly.dev/#/wallet")[:70], "…")
