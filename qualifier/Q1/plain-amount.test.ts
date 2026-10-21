import test from "node:test";
import assert from "node:assert/strict";
import { plainAmount } from "./plain-amount.ts";

test("A1 formats a plain integer with two decimals", () => {
  assert.equal(plainAmount("123450", 6, "USDC"), "0.12345 USDC");
  assert.equal(plainAmount("1000000", 6, "USDC"), "1.00 USDC");
});

test("A1 groups thousands with commas", () => {
  assert.equal(plainAmount("1234500000", 6, "USDC"), "1,234.50 USDC");
  assert.equal(plainAmount("1234567000000", 6, "USDC"), "1,234,567.00 USDC");
});

test("A1 keeps at least two and at most decimals fraction digits", () => {
  assert.equal(plainAmount("1500000", 6, "USDC"), "1.50 USDC");
  assert.equal(plainAmount("1000001", 6, "USDC"), "1.000001 USDC");
  assert.equal(plainAmount("1000100", 6, "USDC"), "1.0001 USDC");
  assert.equal(plainAmount("5", 2, "USDC"), "0.05 USDC");
});

test("A1 writes negatives with the word minus and never a dash", () => {
  const out = plainAmount("-1234500000", 6, "USDC");
  assert.equal(out, "minus 1,234.50 USDC");
  assert.ok(!/[-−–—]/.test(out), "output must not contain a dash");
});

test("A1 reads Arabic Indic digits", () => {
  assert.equal(plainAmount("١٢٣٤٥٠٠٠٠٠", 6, "USDC"), "1,234.50 USDC");
  assert.equal(plainAmount("-١٢٣٤٥٠٠٠٠٠", 6, "USDC"), "minus 1,234.50 USDC");
});

test("A1 throws on invalid input", () => {
  assert.throws(() => plainAmount("", 6, "USDC"));
  assert.throws(() => plainAmount("12.5", 6, "USDC"));
  assert.throws(() => plainAmount("1,000", 6, "USDC"));
  assert.throws(() => plainAmount("abc", 6, "USDC"));
  assert.throws(() => plainAmount("100", 1, "USDC"));
  assert.throws(() => plainAmount("100", 6, ""));
});
