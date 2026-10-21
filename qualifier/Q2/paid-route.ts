/**
 * Q2: an x402 paid route.
 *
 * createPaidRoute({ price, payTo, network, facilitator }) returns a fetch style
 * handler. An unpaid request is answered with HTTP 402 and a payment challenge,
 * a paid request is verified and settled through the injected facilitator, and
 * the wrapped handler result is returned with the settle receipt in the
 * X-PAYMENT-RESPONSE header.
 */

export const USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";

export const DEFAULT_MAX_TIMEOUT_SECONDS = 60;

export const PAYMENT_HEADER = "X-PAYMENT";

export const PAYMENT_RESPONSE_HEADER = "X-PAYMENT-RESPONSE";

export type PaymentRequirements = {
  scheme: "exact";
  network: string;
  maxAmountRequired: string;
  payTo: string;
  asset: string;
  resource: string;
  mimeType: string;
  maxTimeoutSeconds: number;
};

export type PaymentPayload = {
  x402Version?: number;
  scheme?: string;
  network?: string;
  payload?: unknown;
  [key: string]: unknown;
};

export type VerifyOutcome = unknown;

export type SettleOutcome = unknown;

export type Facilitator = {
  verify: (payment: PaymentPayload, requirements: PaymentRequirements) => unknown;
  settle: (payment: PaymentPayload, requirements: PaymentRequirements) => unknown;
};

export type PaidHandlerContext = {
  payment: PaymentPayload;
  requirements: PaymentRequirements;
  settlement: SettleOutcome;
};

export type PaidHandlerResult = Response | Record<string, unknown> | unknown[] | string | number | boolean | null | undefined;

export type PaidHandler = (request: Request, context: PaidHandlerContext) => PaidHandlerResult | Promise<PaidHandlerResult>;

export type PaidRouteOptions = {
  price: string | number | bigint;
  payTo: string;
  network: string;
  facilitator: Facilitator;
  handler?: PaidHandler;
  wrapped?: PaidHandler;
  next?: PaidHandler;
  asset?: string;
  resource?: string;
  mimeType?: string;
  maxTimeoutSeconds?: number;
  x402Version?: number;
};

const BASE64_PATTERN = /^[A-Za-z0-9+/=_-]+$/;

function base64Encode(value: string): string {
  return Buffer.from(value, "utf8").toString("base64");
}

function base64Decode(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  return Buffer.from(normalized, "base64").toString("utf8");
}

function toAmount(price: string | number | bigint): string {
  if (typeof price === "bigint") {
    if (price < 0n) throw new Error("price must not be negative");
    return price.toString();
  }
  if (typeof price === "number") {
    if (!Number.isFinite(price) || price < 0 || !Number.isInteger(price)) {
      throw new Error("price must be an integer amount in base units");
    }
    return price.toString();
  }
  if (typeof price !== "string" || !/^[0-9]+$/.test(price)) {
    throw new Error("price must be an integer amount in base units");
  }
  return price;
}

function reasonOf(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.length > 0) return value;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const key of ["error", "errorReason", "invalidReason", "reason", "message", "errorMessage"]) {
      const candidate = record[key];
      if (typeof candidate === "string" && candidate.length > 0) return candidate;
    }
  }
  return fallback;
}

function isFailure(value: unknown): boolean {
  if (value === false || value === null || value === undefined) return true;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (record.isValid === false) return true;
    if (record.valid === false) return true;
    if (record.success === false) return true;
    if (record.ok === false) return true;
  }
  return false;
}

function decodePaymentHeader(header: string): PaymentPayload | null {
  const trimmed = header.trim();
  if (trimmed.length === 0 || !BASE64_PATTERN.test(trimmed)) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(base64Decode(trimmed));
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const payment = parsed as PaymentPayload;
  if (!payment.payload || typeof payment.payload !== "object") return null;
  return payment;
}

function jsonResponse(status: number, body: unknown, headers?: HeadersInit): Response {
  const out = new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
  if (headers) {
    new Headers(headers).forEach((value, key) => {
      out.headers.set(key, value);
    });
  }
  return out;
}

export function createPaidRoute(options: PaidRouteOptions, handlerArg?: PaidHandler) {
  if (!options || typeof options !== "object") {
    throw new Error("options are required");
  }
  const { payTo, network, facilitator } = options;
  if (typeof payTo !== "string" || payTo.trim().length === 0) {
    throw new Error("payTo must be a non empty string");
  }
  if (typeof network !== "string" || network.trim().length === 0) {
    throw new Error("network must be a non empty string");
  }
  if (!facilitator || typeof facilitator.verify !== "function" || typeof facilitator.settle !== "function") {
    throw new Error("facilitator must provide verify and settle");
  }

  const amount = toAmount(options.price);
  const asset = options.asset ?? USDC_BASE;
  const mimeType = options.mimeType ?? "application/json";
  const maxTimeoutSeconds = options.maxTimeoutSeconds ?? DEFAULT_MAX_TIMEOUT_SECONDS;
  const x402Version = options.x402Version ?? 1;
  const resourceOverride = options.resource;
  const handler: PaidHandler =
    handlerArg ?? options.handler ?? options.wrapped ?? options.next ?? (() => ({ ok: true, paid: true }));

  function requirementsFor(request: Request): PaymentRequirements {
    let resource = resourceOverride;
    if (!resource) {
      try {
        const url = new URL(request.url);
        resource = `${url.origin}${url.pathname}`;
      } catch {
        resource = request.url;
      }
    }
    return {
      scheme: "exact",
      network,
      maxAmountRequired: amount,
      payTo,
      asset,
      resource,
      mimeType,
      maxTimeoutSeconds,
    };
  }

  function challenge(requirements: PaymentRequirements, error: string): Response {
    return jsonResponse(402, {
      x402Version,
      error,
      accepts: [requirements],
    });
  }

  async function route(request: Request): Promise<Response> {
    const requirements = requirementsFor(request);
    const header = request.headers.get(PAYMENT_HEADER);

    if (!header || header.trim().length === 0) {
      return challenge(requirements, "X-PAYMENT header is required");
    }

    const payment = decodePaymentHeader(header);
    if (!payment) {
      return challenge(requirements, "invalid X-PAYMENT header");
    }
    if (typeof payment.scheme === "string" && payment.scheme !== requirements.scheme) {
      return challenge(requirements, "unsupported payment scheme");
    }
    if (typeof payment.network === "string" && payment.network !== requirements.network) {
      return challenge(requirements, "payment network does not match this route");
    }

    let verdict: VerifyOutcome;
    try {
      verdict = await facilitator.verify(payment, requirements);
    } catch (error) {
      return challenge(requirements, reasonOf(error, "payment verification failed"));
    }
    if (isFailure(verdict)) {
      return challenge(requirements, reasonOf(verdict, "payment verification failed"));
    }

    let settlement: SettleOutcome;
    try {
      settlement = await facilitator.settle(payment, requirements);
    } catch (error) {
      return jsonResponse(502, { error: reasonOf(error, "payment settlement failed") });
    }
    if (isFailure(settlement)) {
      return jsonResponse(502, { error: reasonOf(settlement, "payment settlement failed") });
    }

    const produced = await handler(request, { payment, requirements, settlement });
    let response: Response;
    if (produced instanceof Response) {
      response = new Response(await produced.text(), {
        status: produced.status,
        statusText: produced.statusText,
        headers: produced.headers,
      });
    } else if (produced === undefined) {
      response = jsonResponse(200, null);
    } else if (typeof produced === "string") {
      response = new Response(produced, { status: 200, headers: { "content-type": mimeType } });
    } else {
      response = jsonResponse(200, produced);
    }

    response.headers.set(PAYMENT_RESPONSE_HEADER, base64Encode(JSON.stringify(settlement ?? {})));
    return response;
  }

  return route;
}
