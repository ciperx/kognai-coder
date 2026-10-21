
import base64, json, os, subprocess, sys, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

class Fac(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        ok = body.get("paymentPayload", {}).get("payload", {}).get("signature") == "0xsig"
        out = {"isValid": ok, "invalidReason": None if ok else "bad signature"} if self.path.endswith("/verify") else {"success": ok, "transaction": "0xdeadbeef", "network": "eip155:8453"}
        raw = json.dumps(out).encode()
        self.send_response(200); self.send_header("content-type","application/json")
        self.send_header("content-length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

fac = ThreadingHTTPServer(("127.0.0.1", 8898), Fac)
threading.Thread(target=fac.serve_forever, daemon=True).start()

env = dict(os.environ, X402_PAY_TO="0x27EbD1DDCB6607bE8641784A1bf654623Fc8290e", PORT="8899",
           X402_FACILITATOR="http://127.0.0.1:8898")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=".", env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
time.sleep(1.5)

def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:8899" + path, data=data, method=method)
    req.add_header("content-type", "application/json")
    for k, v in (headers or {}).items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()

spec = "add retry with exponential backoff to fetchUser"
s, h, b = call("GET", "/health"); print("health", s, b.decode()[:80])
s, h, b = call("POST", "/patch", {"spec": spec}); print("unpaid", s, "challenge-in-header:", bool(h.get("PAYMENT-REQUIRED")))
challenge = b
s, h, b = call("POST", "/patch?dry=1", {"spec": spec}); print("dry", s, json.loads(b)["dryRun"], len(json.loads(b)["patch"]))
s, h, b = call("GET", "/patch?dry=1&spec=add+timeout+to+fetchUser"); print("dry-get", s, json.loads(b)["target"])

pay = base64.b64encode(json.dumps({"x402Version": 2, "scheme": "exact", "network": "eip155:8453",
    "payload": {"signature": "0xsig", "authorization": {"from": "0x0", "to": "0x1", "value": "10000"}}}).encode()).decode()
s, h, b = call("POST", "/patch", {"spec": spec}, {"X-PAYMENT": pay})
paid = json.loads(b)
print("paid", s, "has X-PAYMENT-RESPONSE:", bool(h.get("X-PAYMENT-RESPONSE")), "applied:", paid["applied"],
      "keys:", sorted(paid.keys()))
print("paid patch has + and -:", any(l.startswith('+') for l in paid["patch"].splitlines()), any(l.startswith('-') for l in paid["patch"].splitlines()))
print("tests:", paid["tests"])
s, h, b = call("POST", "/patch", {"spec": "add validate input to get_user", "target": "app/users.py"}, {"X-PAYMENT": base64.b64encode(json.dumps({"x402Version":2,"payload":{"signature":"0xsig"}}).encode()).decode()})
print("paid-python", s, json.loads(b)["language"], json.loads(b)["target"])

bad = base64.b64encode(json.dumps({"x402Version": 2, "payload": {"signature": "bad"}}).encode()).decode()
s, h, b = call("POST", "/patch", {"spec": spec}, {"X-PAYMENT": bad}); print("bad-payment", s, b.decode()[:70])
s, h, b = call("GET", "/openapi.json"); print("openapi", s, json.loads(b)["info"]["version"])

# 402 byte equality against the deployed live challenge snapshot
live = json.load(open("/tmp/p.txt"))
print("402 identical to live:", live == json.loads(challenge))
open("/tmp/paid_patch.json","w").write(paid["patch"])
srv.terminate()
