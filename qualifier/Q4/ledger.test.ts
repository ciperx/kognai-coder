import test from "node:test";
import assert from "node:assert/strict";
import { createLedger } from "./ledger.ts";

test("A1 posts an amount and reports the balance as a string", () => {
  const ledger = createLedger({ cap: "100" });
  const res = ledger.post({ key: "k1", account: "alice", amount: "30" });
  assert.equal(res.duplicate, false);
  assert.equal(typeof res.id, "string");
  assert.equal(ledger.balance("alice"), "30");
  assert.equal(ledger.balance("bob"), "0");
});

test("A1 replays the same key with the same payload once", () => {
  const ledger = createLedger({ cap: "100" });
  const first = ledger.post({ key: "k1", account: "alice", amount: "30" });
  const second = ledger.post({ key: "k1", account: "alice", amount: "30" });
  assert.equal(second.duplicate, true);
  assert.equal(second.id, first.id);
  assert.equal(ledger.balance("alice"), "30");
});

test("A1 throws when a key is reused with another payload", () => {
  const ledger = createLedger({ cap: "100" });
  ledger.post({ key: "k1", account: "alice", amount: "30" });
  assert.throws(() => ledger.post({ key: "k1", account: "alice", amount: "31" }));
  assert.throws(() => ledger.post({ key: "k1", account: "bob", amount: "30" }));
  assert.equal(ledger.balance("alice"), "30");
  assert.equal(ledger.balance("bob"), "0");
});

test("A1 refuses a post that would pass the cap and changes nothing", () => {
  const ledger = createLedger({ cap: "100" });
  ledger.post({ key: "k1", account: "alice", amount: "60" });
  assert.throws(() => ledger.post({ key: "k2", account: "alice", amount: "41" }));
  assert.equal(ledger.balance("alice"), "60");
  const ok = ledger.post({ key: "k3", account: "alice", amount: "40" });
  assert.equal(ok.duplicate, false);
  assert.equal(ledger.balance("alice"), "100");
});

test("A1 keeps the cap per account and calls it a success at the limit", () => {
  const ledger = createLedger({ cap: "10" });
  ledger.post({ key: "a", account: "alice", amount: "10" });
  ledger.post({ key: "b", account: "bob", amount: "10" });
  assert.equal(ledger.balance("alice"), "10");
  assert.equal(ledger.balance("bob"), "10");
});

test("A1 rejects malformed input", () => {
  const ledger = createLedger({ cap: "100" });
  assert.throws(() => ledger.post({ key: "k", account: "alice", amount: "-1" }));
  assert.throws(() => ledger.post({ key: "k", account: "alice", amount: "1.5" }));
  assert.throws(() => ledger.post({ key: "", account: "alice", amount: "1" }));
  assert.throws(() => createLedger({ cap: "-5" }));
});
