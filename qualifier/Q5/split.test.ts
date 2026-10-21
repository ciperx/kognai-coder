import test from "node:test";
import assert from "node:assert/strict";
import { splitFees } from "./split.ts";

test("A2 rejects a negative total", () => {
  assert.throws(() => splitFees(-1n, [50, 50]), /negative total/);
});

test("A2 rejects an empty share list", () => {
  assert.throws(() => splitFees(100n, []), /bad shares/);
});

test("A2 rejects a non integer share", () => {
  assert.throws(() => splitFees(100n, [50.5, 49.5]), /bad shares/);
});

test("A2 rejects a negative share", () => {
  assert.throws(() => splitFees(100n, [-10, 110]), /bad shares/);
});

test("A2 rejects shares that do not sum to 100", () => {
  assert.throws(() => splitFees(100n, [50, 40]), /shares must sum to 100/);
  assert.throws(() => splitFees(100n, [60, 60]), /shares must sum to 100/);
});

test("A2 splits an even total without moving a unit", () => {
  assert.deepEqual(splitFees(100n, [50, 50]), [50n, 50n]);
  assert.deepEqual(splitFees(1000n, [25, 25, 25, 25]), [250n, 250n, 250n, 250n]);
  assert.deepEqual(splitFees(0n, [100]), [0n]);
});

test("A2 gives the remainder to the first share", () => {
  assert.deepEqual(splitFees(101n, [50, 50]), [51n, 50n]);
  assert.deepEqual(splitFees(1n, [1, 99]), [1n, 0n]);
});

test("A2 truncates each share instead of rounding it up", () => {
  assert.deepEqual(splitFees(3n, [50, 50]), [2n, 1n]);
  assert.deepEqual(splitFees(10n, [33, 33, 34]), [4n, 3n, 3n]);
});

test("A2 always returns parts that sum back to the total", () => {
  for (const total of [0n, 1n, 7n, 99n, 100n, 12345n, 999999999n]) {
    const parts = splitFees(total, [7, 13, 20, 60]);
    assert.equal(parts.length, 4);
    assert.equal(parts.reduce((a, b) => a + b, 0n), total);
  }
});

test("A2 keeps exact precision above the safe integer range", () => {
  const total = 2n ** 80n + 1n;
  const parts = splitFees(total, [50, 50]);
  assert.equal(parts.reduce((a, b) => a + b, 0n), total);
  assert.equal(parts[1], (total * 50n) / 100n);
});
