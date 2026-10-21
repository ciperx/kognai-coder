# kognai-coder

Coding agent for the Kognai LAX job `314ed058` ("Best coding agent for Kognai").
Qualifier modules are plain TypeScript, run by `tsx` with `node:test`, no network.

## Live endpoint

- `GET https://coder.ggez.my.id/health` answers 200 with `{"ok":true,"service":"kognai-coder","paid":true}`.
- `POST https://coder.ggez.my.id/patch` answers **402** with the x402 terms (scheme `exact`, network `base`, asset `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`, payTo `0x27EbD1DDCB6607bE8641784A1bf654623Fc8290e`, 10000 base units = 0.01 USDC).
- A paid call carries `X-PAYMENT` (base64 JSON). The route verifies and settles through the facilitator, then answers with `X-PAYMENT-RESPONSE`.

## Qualifier

- `qualifier/Q1/plain-amount.ts` exports `plainAmount(value, decimals, symbol)`.
- `qualifier/Q2/paid-route.ts` exports `createPaidRoute({price, payTo, network, facilitator})`.
- `qualifier/Q3/lax-offer.json` is the LAX offer for this agent.
- `qualifier/Q4/ledger.ts` exports `createLedger({cap})`.
- `qualifier/Q5/split.ts` is the function copied verbatim from the brief; `qualifier/Q5/split.test.ts` is the test file that must kill every planted bug.

## Run

```bash
npm install
npx tsx --test qualifier/Q1/plain-amount.test.ts
npx tsx --test qualifier/Q4/ledger.test.ts
npx tsx --test qualifier/Q5/split.test.ts
python3 qualifier/Q5/mutation_check.py
```

`mutation_check.py` plants five bugs in a copy of `split.ts` and asserts the test
file fails on every one of them. Current result: 5 of 5 killed.

## Status

Q1 (6 tests), Q4 (6 tests) and Q5 (10 tests) pass locally, and the Q5 mutants are
all killed. Q2 and the patch generator are the remaining M2 work; the endpoint
currently answers 402 unpaid and refuses a spec it cannot solve rather than
pretending to have solved it.
