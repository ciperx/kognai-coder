# poidh payout proof — an AI agent paid by two independent buyers

Two PoidhV3 (Base) claims submitted by an autonomous agent were accepted and paid by two
different issuers who commissioned the work. Everything below is re-checkable with a public
RPC node and a browser; no explorer key, no login.

| # | bounty (UI) | issuer | accept tx | gross | net to agent | accepted (UTC) |
|---|---|---|---|---|---|---|
| 1 | https://poidh.xyz/base/bounty/1450 | 0xa21e61165a97cba8e02558ece645da45ae4eaf0a | `0xb907e797eee08db15633e0ca2b1541894d2ccba49bf6d4fcb9bd2c7430b962b0` | 0.00188 ETH | 0.001833 ETH | 2026-10-06 17:04:57 |
| 2 | https://poidh.xyz/base/bounty/1451 | 0x10fc964ef70c8467cd8c53e9ed9347422adf96a8 | `0x5556fce4e34adc62d09e291dbb23560e086c76975b2c8c269532b873be42251c` | 0.002 ETH | 0.00195 ETH | 2026-10-05 20:02:25 |

Claimer (agent wallet) both times: `0xAD4B40D1E7C98778E4555207A37B8D75fDe4f9b6`.
PoidhV3 on Base: `0x5555fa783936c260f77385b4e153b9725fef1719`.

## Reproduce

```bash
python3 verify_claim_payment.py 0xb907e797eee08db15633e0ca2b1541894d2ccba49bf6d4fcb9bd2c7430b962b0 0xAD4B40D1E7C98778E4555207A37B8D75fDe4f9b6
python3 verify_claim_payment.py 0x5556fce4e34adc62d09e291dbb23560e086c76975b2c8c269532b873be42251c 0xAD4B40D1E7C98778E4555207A37B8D75fDe4f9b6
```

The script reads `eth_getTransactionReceipt` from `https://mainnet.base.org`, finds the
`ClaimPaid` log (`topic0 = 0x46fffb58…8070a`), checks the indexed claimer, and verifies that
`net + fee == gross` with `fee = gross * 2.5%`. It also reads `pendingWithdrawals(address)`
(`0xf3f43703`), which is 0 now — the credits were withdrawn.

Negative control (same tx, different wallet) returns `"paid_to_claimer": false`.

Sample output is in `run_1450.json` and `run_1451.json`.
