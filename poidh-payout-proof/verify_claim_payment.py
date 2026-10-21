#!/usr/bin/env python3
"""Verify that a poidh (PoidhV3) claim was paid to a specific wallet.

Reads the acceptance transaction straight from a public Base RPC node, decodes
the ClaimPaid log and checks the indexed claimer address plus the two value
fields (gross pot and net-to-claimer after poidh's 2.5% fee).

No API key, no explorer login, no third-party indexer: only eth_getTransactionReceipt.

Usage:
    python3 verify_claim_payment.py 0xb907e797... 0xAD4B40D1...
"""
import json
import sys
import urllib.request

RPC = "https://mainnet.base.org"
POIDH_V3 = "0x5555fa783936c260f77385b4e153b9725fef1719"
# keccak256("ClaimPaid(uint256,uint256,address,uint256,uint256,uint256,bool)")
CLAIM_PAID_TOPIC = "0x46fffb589554d79a52571e78a5a713b327069bbc5afd8b997c7ca512ab38070a"
FEE_BPS = 250
BPS_DENOM = 10_000


def rpc(method, params, url=RPC):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "curl/8.5.0"},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.load(resp)
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["result"]


def word(data_hex, i):
    """i-th 32-byte word of 0x-prefixed hex data."""
    raw = data_hex[2:]
    return int(raw[i * 64:(i + 1) * 64], 16)


def verify(tx_hash, claimer):
    claimer = claimer.lower().replace("0x", "")
    if len(claimer) != 40:
        raise SystemExit("claimer must be a 20-byte hex address")
    receipt = rpc("eth_getTransactionReceipt", [tx_hash])
    if receipt is None:
        raise SystemExit("tx not found on Base")
    if int(receipt["status"], 16) != 1:
        raise SystemExit("tx reverted")

    hits = []
    for log in receipt["logs"]:
        if log["address"].lower() != POIDH_V3:
            continue
        if log["topics"][0].lower() != CLAIM_PAID_TOPIC:
            continue
        indexed_claimer = log["topics"][3][-40:].lower()
        if indexed_claimer != claimer:
            continue
        gross = word(log["data"], 1)
        net = word(log["data"], 2)
        fee = word(log["data"], 3)
        expected_fee = gross * FEE_BPS // BPS_DENOM
        hits.append({
            # indexed: bountyId, claimId in that order (both are protocol counters)
            "bounty_id": int(log["topics"][1], 16),
            "claim_id": int(log["topics"][2], 16),
            "issuer": "0x" + log["data"][2:][24:64],
            "claimer": "0x" + indexed_claimer,
            "gross_wei": gross,
            "net_wei": net,
            "fee_wei": fee,
            "gross_eth": gross / 1e18,
            "net_eth": net / 1e18,
            "fee_matches_2_5pct": expected_fee == fee,
            "net_plus_fee_equals_gross": net + fee == gross,
        })

    out = {
        "tx": tx_hash,
        "block": int(receipt["blockNumber"], 16),
        "poidh_v3": POIDH_V3,
        "paid_to_claimer": bool(hits),
        "events": hits,
        "withdrawable_now_wei": int(
            rpc("eth_call", [{"to": POIDH_V3,
                              "data": "0xf3f43703" + claimer.rjust(64, "0")}, "latest"]), 16),
    }
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(json.dumps(verify(sys.argv[1], sys.argv[2]), indent=2))
