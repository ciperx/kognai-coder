import test from "node:test";
import assert from "node:assert/strict";
import { createPaidRoute, PAYMENT_HEADER, PAYMENT_RESPONSE_HEADER, USDC_BASE } from "./paid-route.ts";

const PAY_TO = "0x1111111111111111111111111111111111111111";
const NETWORK = "base";
const PRICE = "10000";
const RESOURCE = "https://agent.example.com/paid";

type Payment = Record<string, unknown>;

function encode(payment: Payment): string {
  return Buffer.from(JSON.stringify(payment), "utf8").toString("base64");
}

function paidPayment(network = NETWORK): Payment {
  return {
    x402Version: 1,
    scheme: "exact",
    network,
    payload: {
      signature: "0xdeadbeef",
      authorization: {
        from: "0x2222222222222222222222222222222222222222",
        to: PAY_TO,
        value: PRICE,
        validAfter: "0",
        validBefore: "9999999999",
        nonce: "0x" + "00".repeat(32),
      },
    },
  };
}

function capture() {
  const calls: { verify: unknown[][]; settle: unknown[][] } = { verify: [], settle: [] };
  return calls;
}

function makeRoute(
  overrides: {
    verifyResult?: unknown;
    settleResult?: unknown;
    verifyThrows?: boolean;
    settleThrows?: boolean;
    onVerify?: (payment: unknown, requirements: unknown) => void;
    onSettle?: (payment: unknown, requirements: unknown) => void;
  } = {},
) {
  const calls = capture();
  const verifyResult = "verifyResult" in overrides ? overrides.verifyResult : { isValid: true };
  const settleResult = "settleResult" in overrides ? overrides.settleResult : { success: true, transaction: "0xtx", network: NETWORK };

  const facilitator = {
    async verify(payment: unknown, requirements: unknown) {
      calls.verify.push([payment, requirements]);
      overrides.onVerify?.(payment, requirements);
      if (overrides.verifyThrows) throw new Error("facilitator unavailable");
      return verifyResult;
    },
    async settle(payment: unknown, requirements: unknown) {
      calls.settle.push([payment, requirements]);
      overrides.onSettle?.(payment, requirements);
      if (overrides.settleThrows) throw new Error("settlement reverted");
      return settleResult;
    },
  };

  const route = createPaidRoute({
    price: PRICE,
    payTo: PAY_TO,
    network: NETWORK,
    facilitator,
    resource: RESOURCE,
    handler: async () => Response.json({ answer: 42 }),
  });

  return { route, calls, verifyResult, settleResult };
}

function request(headers: Record<string, string> = {}): Request {
  return new Request(RESOURCE, { method: "POST", headers });
}

test("A4 answers 402 with payment requirements when no payment header is sent", async () => {
  const { route, calls } = makeRoute();
  const response = await route(request());

  assert.equal(response.status, 402);
  const body = (await response.json()) as Record<string, any>;
  assert.equal(body.x402Version, 1);
  assert.ok(Array.isArray(body.accepts));
  assert.equal(body.accepts.length, 1);

  const accepts = body.accepts[0];
  assert.equal(accepts.scheme, "exact");
  assert.equal(accepts.network, NETWORK);
  assert.equal(accepts.maxAmountRequired, PRICE);
  assert.equal(accepts.payTo, PAY_TO);
  assert.equal(accepts.asset, USDC_BASE);
  assert.equal(accepts.resource, RESOURCE);
  assert.equal(accepts.mimeType, "application/json");
  assert.equal(accepts.maxTimeoutSeconds, 60);

  assert.equal(calls.verify.length, 0);
  assert.equal(calls.settle.length, 0);
  assert.equal(response.headers.get(PAYMENT_RESPONSE_HEADER), null);
});

test("A4 answers 402 when the payment header is malformed", async () => {
  const { route, calls } = makeRoute();

  for (const header of ["not base64 at all", "e30=", Buffer.from("[]").toString("base64"), Buffer.from('{"scheme":"exact"}').toString("base64")]) {
    const response = await route(request({ [PAYMENT_HEADER]: header }));
    assert.equal(response.status, 402, `header ${header} must be rejected`);
    const body = (await response.json()) as Record<string, any>;
    assert.equal(typeof body.error, "string");
  }

  assert.equal(calls.verify.length, 0);
  assert.equal(calls.settle.length, 0);
});

test("A4 answers 402 when the payment network does not match the route", async () => {
  const { route, calls } = makeRoute();
  const response = await route(request({ [PAYMENT_HEADER]: encode(paidPayment("base-sepolia")) }));

  assert.equal(response.status, 402);
  const body = (await response.json()) as Record<string, any>;
  assert.equal(typeof body.error, "string");
  assert.equal(calls.verify.length, 0);
  assert.equal(calls.settle.length, 0);
});

test("A4 answers 402 with an error field when verify fails", async () => {
  const { route, calls } = makeRoute({ verifyResult: { isValid: false, invalidReason: "insufficient_funds" } });
  const response = await route(request({ [PAYMENT_HEADER]: encode(paidPayment()) }));

  assert.equal(response.status, 402);
  const body = (await response.json()) as Record<string, any>;
  assert.equal(body.error, "insufficient_funds");
  assert.equal(body.x402Version, 1);
  assert.ok(Array.isArray(body.accepts));
  assert.equal(calls.verify.length, 1);
  assert.equal(calls.settle.length, 0);
  assert.equal(response.headers.get(PAYMENT_RESPONSE_HEADER), null);
});

test("A4 answers 402 when verify throws", async () => {
  const { route, calls } = makeRoute({ verifyThrows: true });
  const response = await route(request({ [PAYMENT_HEADER]: encode(paidPayment()) }));

  assert.equal(response.status, 402);
  const body = (await response.json()) as Record<string, any>;
  assert.equal(typeof body.error, "string");
  assert.equal(calls.settle.length, 0);
});

test("A4 answers 502 with an error field when settle fails", async () => {
  const { route, calls } = makeRoute({ settleResult: { success: false, errorReason: "settlement_reverted" } });
  const response = await route(request({ [PAYMENT_HEADER]: encode(paidPayment()) }));

  assert.equal(response.status, 502);
  const body = (await response.json()) as Record<string, any>;
  assert.equal(body.error, "settlement_reverted");
  assert.equal(calls.verify.length, 1);
  assert.equal(calls.settle.length, 1);
  assert.equal(response.headers.get(PAYMENT_RESPONSE_HEADER), null);
});

test("A4 answers 502 when settle throws", async () => {
  const { route } = makeRoute({ settleThrows: true });
  const response = await route(request({ [PAYMENT_HEADER]: encode(paidPayment()) }));

  assert.equal(response.status, 502);
  const body = (await response.json()) as Record<string, any>;
  assert.equal(typeof body.error, "string");
});

test("A4 answers 200 with the handler result and an X-PAYMENT-RESPONSE receipt", async () => {
  const { route, settleResult } = makeRoute();
  const response = await route(request({ [PAYMENT_HEADER]: encode(paidPayment()) }));

  assert.equal(response.status, 200);
  const body = (await response.json()) as Record<string, any>;
  assert.equal(body.answer, 42);

  const receipt = response.headers.get(PAYMENT_RESPONSE_HEADER);
  assert.equal(typeof receipt, "string");
  const decoded = JSON.parse(Buffer.from(receipt as string, "base64").toString("utf8"));
  assert.deepEqual(decoded, settleResult);
});

test("A4 hands the facilitator the exact accepts entry from the challenge", async () => {
  const { route, calls } = makeRoute();
  const challengeResponse = await route(request());
  const challengeBody = (await challengeResponse.json()) as Record<string, any>;

  await route(request({ [PAYMENT_HEADER]: encode(paidPayment()) }));

  assert.equal(calls.verify.length, 1);
  assert.equal(calls.settle.length, 1);
  assert.deepEqual(calls.verify[0][1], challengeBody.accepts[0]);
  assert.deepEqual(calls.settle[0][1], challengeBody.accepts[0]);
});

test("A4 passes the decoded payment envelope to the facilitator", async () => {
  const { route, calls } = makeRoute();
  const payment = paidPayment();
  await route(request({ [PAYMENT_HEADER]: encode(payment) }));

  assert.deepEqual(calls.verify[0][0], payment);
  assert.deepEqual(calls.settle[0][0], payment);
});

test("A4 works without an explicit handler and answers 200", async () => {
  const facilitator = {
    async verify() {
      return { isValid: true };
    },
    async settle() {
      return { success: true, transaction: "0xtx" };
    },
  };
  const route = createPaidRoute({ price: PRICE, payTo: PAY_TO, network: NETWORK, facilitator });
  const response = await route(request({ [PAYMENT_HEADER]: encode(paidPayment()) }));

  assert.equal(response.status, 200);
  assert.equal(typeof response.headers.get(PAYMENT_RESPONSE_HEADER), "string");
  await response.json();
});
