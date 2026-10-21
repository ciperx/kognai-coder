#!/usr/bin/env python3
"""Kognai coder endpoint: x402 payment wall in front of /patch.

Unpaid calls get the x402 terms. Paid calls are verified and settled through a
facilitator, then answered by the patch generator. No secrets live in this file:
the payout address and facilitator URL come from the environment.
"""
import base64
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAY_TO = os.environ.get("X402_PAY_TO", "")
NETWORK = os.environ.get("X402_NETWORK", "base")
ASSET = os.environ.get("X402_ASSET", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
PRICE = os.environ.get("X402_PRICE", "10000")
FACILITATOR = os.environ.get("X402_FACILITATOR", "https://x402.org/facilitator")
PORT = int(os.environ.get("PORT", "8795"))
RESOURCE = os.environ.get("X402_RESOURCE", "https://coder.ggez.my.id/patch")


def v1_requirements():
    return {
        "x402Version": 1,
        "accepts": [
            {
                "scheme": "exact",
                "network": NETWORK,
                "maxAmountRequired": PRICE,
                "resource": RESOURCE,
                "description": "Patch a job spec into a unified diff with tests",
                "mimeType": "application/json",
                "payTo": PAY_TO,
                "maxTimeoutSeconds": 60,
                "asset": ASSET,
                "extra": {"name": "USD Coin", "version": "2"},
            }
        ],
        "error": "payment required",
    }


def requirements():
    """x402 v2 challenge (discovery + indexers require v2). Overridable by file."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "x402-402.json")
    try:
        with open(path) as fh:
            body = json.load(fh)
        for accept in body.get("accepts", []):
            accept["payTo"] = PAY_TO or accept.get("payTo")
            accept["asset"] = ASSET or accept.get("asset")
            accept["amount"] = PRICE or accept.get("amount")
        return body
    except Exception:
        return v1_requirements()


def post_json(url, payload, timeout=25):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("user-agent", "kognai-coder/0.1")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")


class Handler(BaseHTTPRequestHandler):
    server_version = "kognai-coder/0.1"

    def log_message(self, fmt, *args):  # quiet, structured-ish
        print(json.dumps({"method": self.command, "path": self.path}), flush=True)

    def send(self, code, body, extra=None):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def send_raw(self, code, raw, ctype):
        if isinstance(raw, str):
            raw = raw.encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(raw)))
        self.send_header("cache-control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(raw)

    def serve_doc(self, filename, ctype):
        import os.path as osp
        path = osp.join(osp.dirname(osp.abspath(__file__)), filename)
        if not osp.isfile(path):
            return self.send(404, {"error": filename + " missing"})
        with open(path, "rb") as fh:
            return self.send_raw(200, fh.read(), ctype)

    def discovery_document(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wellknown.json")
        try:
            with open(path) as fh:
                return json.load(fh)
        except Exception:
            return {"x402Version": 2, "resources": [{
                "resource": RESOURCE, "type": "http", "method": "POST", "x402Version": 2,
                "description": "Patch a job spec into a unified diff with tests",
                "mimeType": "application/json", "accepts": requirements()["accepts"],
            }]}

    def do_GET(self):
        if self.path in ("/health", "/"):
            return self.send(200, {"ok": True, "service": "kognai-coder", "paid": bool(PAY_TO), "x402": True})
        if self.path == "/openapi.json":
            return self.serve_doc("openapi.json", "application/json")
        if self.path == "/llms.txt":
            return self.serve_doc("llms.txt", "text/plain; charset=utf-8")
        if self.path in ("/.well-known/x402", "/.well-known/x402.json"):
            return self.send_raw(200, json.dumps(self.discovery_document()), "application/json")
        if self.path.startswith("/media/"):
            return self.serve_media(self.path[len("/media/"):])
        return self.send(404, {"error": "not found"})

    def serve_media(self, name):
        import mimetypes
        import os.path as osp
        base = osp.join(osp.dirname(osp.abspath(__file__)), "media")
        path = osp.join(base, osp.basename(name))
        if not osp.isfile(path):
            return self.send(404, {"error": "no such media"})
        with open(path, "rb") as fh:
            blob = fh.read()
        self.send_response(200)
        self.send_header("content-type", mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("content-length", str(len(blob)))
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self):
        if self.path != "/patch":
            return self.send(404, {"error": "not found"})

        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:
            return self.send(400, {"error": "body must be JSON"})

        header = self.headers.get("x-payment")
        if not header:
            body = requirements()
            # x402 v2 requires the challenge to ride in the PAYMENT-REQUIRED header
            # (base64 JSON); discovery crawlers only parse v2 from that header.
            challenge = base64.b64encode(json.dumps(body).encode()).decode()
            return self.send(402, body, {
                "PAYMENT-REQUIRED": challenge,
                "X-PAYMENT-REQUIRED": challenge,
                "X-PAYMENT-PROTOCOL": "x402",
                "Access-Control-Expose-Headers": "PAYMENT-REQUIRED, X-PAYMENT-RESPONSE",
            })

        try:
            payment = json.loads(base64.b64decode(header).decode())
        except Exception:
            return self.send(402, {"error": "malformed X-PAYMENT header"})

        version = payment.get("x402Version") or requirements().get("x402Version") or 2
        reqs = (v1_requirements() if version == 1 else requirements())["accepts"][0]
        try:
            status, verdict = post_json(f"{FACILITATOR}/verify", {
                "x402Version": version, "paymentPayload": payment, "paymentRequirements": reqs,
            })
        except Exception as exc:
            return self.send(502, {"error": f"facilitator verify failed: {exc}"})
        if status != 200 or not verdict.get("isValid"):
            return self.send(402, {"error": verdict.get("invalidReason") or "payment invalid"})

        try:
            status, settled = post_json(f"{FACILITATOR}/settle", {
                "x402Version": version, "paymentPayload": payment, "paymentRequirements": reqs,
            })
        except Exception as exc:
            return self.send(502, {"error": f"facilitator settle failed: {exc}"})
        if status != 200:
            return self.send(502, {"error": "settlement failed"})

        answer = {"refused": True, "reason": "patch generation for this spec is not enabled in this build"}
        encoded = base64.b64encode(json.dumps(settled).encode()).decode()
        return self.send(200, answer, {"X-PAYMENT-RESPONSE": encoded})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
