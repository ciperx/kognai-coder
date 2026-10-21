#!/usr/bin/env python3
"""Kognai coder endpoint: x402 payment wall in front of /patch.

Unpaid calls get the x402 terms. Paid calls are verified and settled through a
facilitator, then answered by the deterministic patch generator in this file:
natural-language spec -> unified-diff-like text + rationale + suggested tests.
No LLM calls, no API keys, no third-party dependencies.
"""
import base64
import hashlib
import json
import os
import re
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAY_TO = os.environ.get("X402_PAY_TO", "")
NETWORK = os.environ.get("X402_NETWORK", "base")
ASSET = os.environ.get("X402_ASSET", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
PRICE = os.environ.get("X402_PRICE", "10000")
FACILITATOR = os.environ.get("X402_FACILITATOR", "https://x402.org/facilitator")
PORT = int(os.environ.get("PORT", "8795"))
RESOURCE = os.environ.get("X402_RESOURCE", "https://coder.ggez.my.id/patch")
ENGINE = "kognai-template-heuristics/1.0"


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


# --------------------------------------------------------------------------
# Deterministic patch generator (templates + heuristics, always returns work)
# --------------------------------------------------------------------------

IDENT = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*")
KEYWORDS = {
    "add", "a", "an", "the", "to", "for", "in", "on", "with", "and", "into",
    "function", "method", "endpoint", "handler", "please", "make", "it", "this",
    "that", "of", "when", "so", "also", "our", "we", "should", "need", "needs",
    "ms", "s", "sec", "second", "seconds", "response", "results", "result", "data",
    "spec", "request", "responses", "using", "via", "per", "all", "every", "its",
}

INTENT_RULES = [
    ("retry", ("retry", "retries", "backoff", "back-off", "resilien", "transient", "flaky")),
    ("ratelimit", ("rate limit", "rate-limit", "ratelimit", "throttl", "quota", "429")),
    ("cache", ("cache", "caching", "memoiz", "memoiz", "ttl", "dedupe", "deduplicat")),
    ("validate", ("validat", "sanitiz", "schema", "type guard", "input check", "must be")),
    ("timeout", ("timeout", "time-out", "deadline", "abort", "cancel", "hang")),
    ("auth", ("auth", "bearer", "token", "permission", "401", "403", "rbac", "scope")),
    ("paginate", ("paginat", "cursor", "page size", "next page", "limit+offset")),
    ("logging", ("log", "logging", "telemetry", "metric", "observab", "trace", "audit")),
    ("errors", ("error", "exception", "try/catch", "try catch", "crash", "panic", "unhandled")),
]


def _looks_python(spec, target):
    if target and target.lower().endswith((".py", ".pyi")):
        return True
    if target and target.lower().endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
        return False
    low = spec.lower()
    return any(k in low for k in ("python", "def ", "pytest", "asyncio", "aiohttp", "flask", "django", "fastapi"))


def _kebab(name):
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", name)
    return s.replace("_", "-").lower()


def _snake(name):
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    return re.sub(r"[^A-Za-z0-9_]", "_", s).lower()


def _pascal(name):
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\-\s]+", name) if p)


def _camel(name):
    p = _pascal(name)
    return p[:1].lower() + p[1:] if p else "handler"


def _function_name(spec, target):
    for quoted in re.findall(r"[`'\"]([A-Za-z_][A-Za-z0-9_]{2,})[`'\"]", spec):
        if quoted.lower() not in KEYWORDS:
            return quoted
    m = re.search(r"\b(?:to|for|in|on|inside)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[.,;]?\s*$", spec.strip())
    if m and m.group(1).lower() not in KEYWORDS:
        return m.group(1)
    for m in re.finditer(r"\b(?:function|def|method)\s+([A-Za-z_][A-Za-z0-9_]*)", spec):
        return m.group(1)
    found = [w for w in IDENT.findall(spec) if w.lower() not in KEYWORDS]
    if found:
        return found[-1]
    if target:
        stem = os.path.splitext(os.path.basename(target))[0]
        return _camel(stem)
    return "handleRequest"


def _numbers(spec, default_attempts, default_delay):
    am = re.search(r"(\d+)\s*(?:x\s*)?(?:attempts|tries|retries)", spec, re.I)
    dm = re.search(r"(\d+)\s*(ms|millisecond|milliseconds|s|sec|second|seconds)", spec, re.I)
    attempts = int(am.group(1)) if am else default_attempts
    delay = default_delay
    if dm:
        value = int(dm.group(1))
        unit = dm.group(2).lower()
        delay = value if unit.startswith("m") else value * 1000
    return max(2, min(attempts, 10)), max(50, min(delay, 30000))


def _intents(spec):
    low = spec.lower()
    hits = []
    for name, keys in INTENT_RULES:
        if any(k in low for k in keys):
            hits.append(name)
    if not hits:
        hits = ["errors"]
    return hits


def _hunk(old_start, old_len, new_start, new_len):
    return "@@ -%d,%d +%d,%d @@" % (old_start, old_len, new_start, new_len)


def _plus(lines):
    return ["+" + ln if ln else "+" for ln in lines]


TS_HELPERS = {
    "retry": """// --- added: retry with exponential backoff + jitter -------------------------
export interface RetryOptions {
  attempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
}

export class HttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "HttpError";
  }
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function isRetryable(error: unknown): boolean {
  if (error instanceof HttpError) return error.status === 429 || error.status >= 500;
  const code = (error as { code?: string } | null)?.code;
  return code === "ECONNRESET" || code === "ETIMEDOUT" || code === "ENOTFOUND";
}

export async function withRetry<T>(fn: () => Promise<T>, options: RetryOptions = {}): Promise<T> {
  const attempts = options.attempts ?? __ATTEMPTS__;
  const baseDelayMs = options.baseDelayMs ?? __DELAY__;
  const maxDelayMs = options.maxDelayMs ?? 4_000;
  let lastError: unknown;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      if (attempt === attempts || !isRetryable(error)) break;
      const backoff = Math.min(maxDelayMs, baseDelayMs * 2 ** (attempt - 1));
      await sleep(backoff + Math.floor(Math.random() * (backoff / 2)));
    }
  }
  throw lastError;
}""",
    "timeout": """// --- added: per-call timeout with AbortController --------------------------
export async function withTimeout<T>(run: (signal: AbortSignal) => Promise<T>, timeoutMs = __DELAY__): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await run(controller.signal);
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error(`__FUNC__ timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}""",
    "cache": """// --- added: TTL cache with in-flight de-duplication -------------------------
type CacheEntry<T> = { value: T; expiresAt: number };

const __CACHE__ = new Map<string, CacheEntry<unknown>>();
const __INFLIGHT__ = new Map<string, Promise<unknown>>();

export async function cached<T>(key: string, ttlMs: number, load: () => Promise<T>): Promise<T> {
  const hit = __CACHE__.get(key) as CacheEntry<T> | undefined;
  if (hit && hit.expiresAt > Date.now()) return hit.value;
  const pending = __INFLIGHT__.get(key) as Promise<T> | undefined;
  if (pending) return pending;
  const task = load()
    .then((value) => {
      __CACHE__.set(key, { value, expiresAt: Date.now() + ttlMs });
      return value;
    })
    .finally(() => __INFLIGHT__.delete(key));
  __INFLIGHT__.set(key, task);
  return task;
}""",
    "ratelimit": """// --- added: token-bucket rate limiter ---------------------------------------
export class TokenBucket {
  private tokens: number;
  private lastRefill = Date.now();

  constructor(private readonly capacity = __ATTEMPTS__, private readonly refillPerSecond = 1) {
    this.tokens = capacity;
  }

  tryTake(count = 1): boolean {
    const now = Date.now();
    const elapsed = (now - this.lastRefill) / 1000;
    this.tokens = Math.min(this.capacity, this.tokens + elapsed * this.refillPerSecond);
    this.lastRefill = now;
    if (this.tokens < count) return false;
    this.tokens -= count;
    return true;
  }
}

export const __BUCKET__ = new TokenBucket(__ATTEMPTS__, __ATTEMPTS__ / 60);

export async function withRateLimit<T>(fn: () => Promise<T>, bucket = __BUCKET__): Promise<T> {
  for (let i = 0; i < 50; i += 1) {
    if (bucket.tryTake()) return fn();
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("__FUNC__: rate limit wait exceeded");
}""",
    "validate": """// --- added: narrow runtime validation (no external schema library) ----------
export class ValidationError extends Error {
  constructor(message: string, readonly field?: string) {
    super(message);
    this.name = "ValidationError";
  }
}

export function assertIdentifier(value: unknown, field = "id"): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(value)) {
    throw new ValidationError(`${field} must be 1-64 chars of [A-Za-z0-9_-]`, field);
  }
  return value;
}

export function assertPlainObject(value: unknown, field = "payload"): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ValidationError(`${field} must be an object`, field);
  }
  return value as Record<string, unknown>;
}""",
    "auth": """// --- added: bearer-token check with structured 401/403 ----------------------
export class AuthError extends Error {
  constructor(message: string, readonly status: 401 | 403 = 401) {
    super(message);
    this.name = "AuthError";
  }
}

export function requireBearer(header: string | null | undefined, scopes: string[] = []): void {
  if (!header || !header.startsWith("Bearer ")) {
    throw new AuthError("missing bearer token", 401);
  }
  const token = header.slice("Bearer ".length).trim();
  if (token.length < 16) throw new AuthError("malformed bearer token", 401);
  const granted = token.split(".")[0].split(":")[1]?.split(",") ?? [];
  for (const scope of scopes) {
    if (!granted.includes(scope)) throw new AuthError(`missing scope ${scope}`, 403);
  }
}""",
    "paginate": """// --- added: cursor pagination helper ----------------------------------------
export interface Page<T> {
  items: T[];
  nextCursor: string | null;
}

export function encodeCursor(value: string): string {
  return Buffer.from(value, "utf8").toString("base64url");
}

export function decodeCursor(cursor: string | null | undefined): string | null {
  if (!cursor) return null;
  try {
    return Buffer.from(cursor, "base64url").toString("utf8");
  } catch {
    throw new Error("invalid cursor");
  }
}

export function paginate<T extends { id: string }>(rows: T[], limit = 50, cursor?: string | null): Page<T> {
  const after = decodeCursor(cursor);
  const size = Math.max(1, Math.min(limit, 200));
  const start = after ? rows.findIndex((r) => r.id === after) + 1 : 0;
  const slice = rows.slice(start, start + size);
  const next = start + size < rows.length ? encodeCursor(slice[slice.length - 1]?.id ?? "") : null;
  return { items: slice, nextCursor: next };
}""",
    "logging": """// --- added: structured logging with per-call correlation id ----------------
export interface LogFields {
  [key: string]: unknown;
}

export function logEvent(level: "info" | "warn" | "error", event: string, fields: LogFields = {}): void {
  const line = JSON.stringify({
    ts: new Date().toISOString(),
    level,
    service: "app",
    event,
    ...fields,
  });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}

export async function instrument<T>(event: string, fn: () => Promise<T>): Promise<T> {
  const startedAt = Date.now();
  try {
    const result = await fn();
    logEvent("info", event, { ok: true, durationMs: Date.now() - startedAt });
    return result;
  } catch (error) {
    logEvent("error", event, { ok: false, durationMs: Date.now() - startedAt, error: String(error) });
    throw error;
  }
}""",
    "errors": """// --- added: typed result + error normalisation ------------------------------
export class UpstreamError extends Error {
  constructor(message: string, readonly status = 502, readonly cause?: unknown) {
    super(message);
    this.name = "UpstreamError";
  }
}

export function toUpstreamError(error: unknown, context: string): UpstreamError {
  if (error instanceof UpstreamError) return error;
  const status = (error as { status?: number } | null)?.status ?? 502;
  const detail = error instanceof Error ? error.message : String(error);
  return new UpstreamError(`${context}: ${detail}`, status, error);
}""",
}

PY_HELPERS = {
    "retry": """# --- added: retry with exponential backoff + jitter -------------------------
import functools
import random
import time


class RetryableError(Exception):
    \"\"\"Raised when an upstream failure is worth retrying.\"\"\"

    def __init__(self, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.status = status


def retry(
    attempts: int = __ATTEMPTS__,
    base_delay: float = __DELAY_S__,
    max_delay: float = 4.0,
    retry_on: tuple = (RetryableError, TimeoutError, ConnectionError),
):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as exc:
                    last_error = exc
                    if attempt == attempts:
                        break
                    backoff = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    time.sleep(backoff + random.uniform(0, backoff / 2))
            raise last_error

        return wrapper

    return decorator""",
    "timeout": """# --- added: hard timeout around a blocking call -----------------------------
import concurrent.futures
from typing import Any, Callable


def with_timeout(fn: Callable[..., Any], *args, timeout: float = __DELAY_S__, **kwargs) -> Any:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError("__FUNC__ exceeded %.1fs" % timeout) from exc""",
    "cache": """# --- added: TTL cache with in-flight de-duplication -------------------------
import threading
import time

_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def cached(key: str, ttl: float, loader):
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and hit[1] > now:
            return hit[0]
    value = loader()
    with _CACHE_LOCK:
        _CACHE[key] = (value, now + ttl)
    return value""",
    "ratelimit": """# --- added: token-bucket rate limiter ---------------------------------------
import threading
import time


class TokenBucket:
    def __init__(self, capacity: int = __ATTEMPTS__, refill_per_second: float = 1.0) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def take(self, count: int = 1, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.refill_per_second)
                self._last = now
                if self._tokens >= count:
                    self._tokens -= count
                    return True
            time.sleep(0.05)
        return False""",
    "validate": """# --- added: narrow runtime validation ---------------------------------------
class ValidationError(ValueError):
    def __init__(self, message: str, field: str = "payload") -> None:
        super().__init__(message)
        self.field = field


def require_str(value, field: str = "id", max_len: int = 64) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= max_len):
        raise ValidationError(f"{field} must be a string of 1-{max_len} chars", field)
    return value


def require_dict(value, field: str = "payload") -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be an object", field)
    return value""",
    "auth": """# --- added: bearer-token check with structured 401/403 ----------------------
class AuthError(Exception):
    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


def require_bearer(header, scopes=()) -> None:
    if not header or not header.startswith("Bearer "):
        raise AuthError("missing bearer token", 401)
    token = header[len("Bearer "):].strip()
    if len(token) < 16:
        raise AuthError("malformed bearer token", 401)
    granted = set(token.split(".")[0].split(":")[1].split(",")) if ":" in token.split(".")[0] else set()
    missing = [s for s in scopes if s not in granted]
    if missing:
        raise AuthError("missing scope " + ",".join(missing), 403)""",
    "paginate": """# --- added: cursor pagination helper ----------------------------------------
import base64


def encode_cursor(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def decode_cursor(cursor) -> str | None:
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    return base64.urlsafe_b64decode(padded.encode()).decode()


def paginate(rows, limit: int = 50, cursor=None):
    size = max(1, min(int(limit), 200))
    after = decode_cursor(cursor)
    ids = [r["id"] for r in rows]
    start = ids.index(after) + 1 if after in ids else 0
    page = rows[start:start + size]
    has_more = start + size < len(rows)
    return {"items": page, "nextCursor": encode_cursor(page[-1]["id"]) if has_more and page else None}""",
    "logging": """# --- added: structured logging with duration + error capture ----------------
import json
import logging
import time

_LOG = logging.getLogger("app")


def log_event(level: str, event: str, **fields) -> None:
    _LOG.log(getattr(logging, level.upper(), logging.INFO), json.dumps({"event": event, **fields}, default=str))


def instrument(event: str, fn, *args, **kwargs):
    started = time.monotonic()
    try:
        result = fn(*args, **kwargs)
        log_event("info", event, ok=True, duration_ms=int((time.monotonic() - started) * 1000))
        return result
    except Exception as exc:  # noqa: BLE001 - re-raised after logging
        log_event("error", event, ok=False, duration_ms=int((time.monotonic() - started) * 1000), error=str(exc))
        raise""",
    "errors": """# --- added: error normalisation ---------------------------------------------
class UpstreamError(Exception):
    def __init__(self, message: str, status: int = 502, cause=None) -> None:
        super().__init__(message)
        self.status = status
        self.cause = cause


def to_upstream_error(exc: Exception, context: str) -> UpstreamError:
    if isinstance(exc, UpstreamError):
        return exc
    return UpstreamError(f"{context}: {exc}", getattr(exc, "status", 502), exc)""",
}

TS_BODY = {
    "retry": [
        '-  const response = await fetch(`${API_BASE}/users/${id}`);',
        "-  if (!response.ok) {",
        "-    throw new Error(`__FUNC__ failed with ${response.status}`);",
        "-  }",
        "-  return (await response.json()) as User;",
        "+  return withRetry(",
        "+    async () => {",
        '+      const response = await fetch(`${API_BASE}/users/${id}`);',
        "+      if (!response.ok) {",
        "+        throw new HttpError(`__FUNC__ failed with ${response.status}`, response.status);",
        "+      }",
        "+      return (await response.json()) as User;",
        "+    },",
        "+    { attempts: __ATTEMPTS__, baseDelayMs: __DELAY__, maxDelayMs: 4_000 },",
        "+  );",
    ],
    "timeout": [
        '-  const response = await fetch(`${API_BASE}/users/${id}`);',
        "-  return (await response.json()) as User;",
        "+  return withTimeout(async (signal) => {",
        '+    const response = await fetch(`${API_BASE}/users/${id}`, { signal });',
        "+    if (!response.ok) {",
        "+      throw new Error(`__FUNC__ failed with ${response.status}`);",
        "+    }",
        "+    return (await response.json()) as User;",
        "+  }, __DELAY__);",
    ],
    "cache": [
        '-  const response = await fetch(`${API_BASE}/users/${id}`);',
        "-  return (await response.json()) as User;",
        '+  const key = `__FUNC__:${id}`;',
        "+  return cached<User>(key, 30_000, async () => {",
        '+    const response = await fetch(`${API_BASE}/users/${id}`);',
        "+    if (!response.ok) {",
        "+      throw new Error(`__FUNC__ failed with ${response.status}`);",
        "+    }",
        "+    return (await response.json()) as User;",
        "+  });",
    ],
    "ratelimit": [
        '-  const response = await fetch(`${API_BASE}/users/${id}`);',
        "-  return (await response.json()) as User;",
        "+  return withRateLimit(async () => {",
        '+    const response = await fetch(`${API_BASE}/users/${id}`);',
        "+    if (!response.ok) {",
        "+      throw new Error(`__FUNC__ failed with ${response.status}`);",
        "+    }",
        "+    return (await response.json()) as User;",
        "+  });",
    ],
    "validate": [
        "-  const response = await fetch(`${API_BASE}/users/${id}`);",
        "-  return (await response.json()) as User;",
        '+  const safeId = assertIdentifier(id, "id");',
        '+  const response = await fetch(`${API_BASE}/users/${encodeURIComponent(safeId)}`);',
        "+  if (!response.ok) {",
        "+    throw new HttpError(`__FUNC__ failed with ${response.status}`, response.status);",
        "+  }",
        "+  return assertPlainObject(await response.json(), \"user\") as unknown as User;",
    ],
    "auth": [
        "-  const response = await fetch(`${API_BASE}/users/${id}`);",
        "-  return (await response.json()) as User;",
        '+  requireBearer(authorization, ["users:read"]);',
        "+  const response = await fetch(`${API_BASE}/users/${id}`, {",
        '+    headers: { authorization: authorization as string },',
        "+  });",
        "+  if (!response.ok) {",
        "+    throw new HttpError(`__FUNC__ failed with ${response.status}`, response.status);",
        "+  }",
        "+  return (await response.json()) as User;",
    ],
    "paginate": [
        '-  const response = await fetch(`${API_BASE}/users/${id}`);',
        "-  return (await response.json()) as User;",
        '+  const response = await fetch(`${API_BASE}/users?limit=${limit ?? 50}&cursor=${cursor ?? ""}`);',
        "+  if (!response.ok) {",
        "+    throw new HttpError(`__FUNC__ failed with ${response.status}`, response.status);",
        "+  }",
        '+  const rows = (await response.json()) as Array<{ id: string }>;',
        "+  return paginate(rows, limit, cursor);",
    ],
    "logging": [
        "-  const response = await fetch(`${API_BASE}/users/${id}`);",
        "-  return (await response.json()) as User;",
        '+  return instrument("__FUNC__", async () => {',
        '+    const response = await fetch(`${API_BASE}/users/${id}`);',
        "+    if (!response.ok) {",
        "+      throw new HttpError(`__FUNC__ failed with ${response.status}`, response.status);",
        "+    }",
        "+    return (await response.json()) as User;",
        "+  });",
    ],
    "errors": [
        "-  const response = await fetch(`${API_BASE}/users/${id}`);",
        "-  return (await response.json()) as User;",
        "+  try {",
        '+    const response = await fetch(`${API_BASE}/users/${id}`);',
        "+    if (!response.ok) {",
        "+      throw new HttpError(`__FUNC__ failed with ${response.status}`, response.status);",
        "+    }",
        "+    return (await response.json()) as User;",
        "+  } catch (error) {",
        '+    throw toUpstreamError(error, "__FUNC__");',
        "+  }",
    ],
}

PY_BODY = {
    "retry": [
        "-    response = urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10)",
        "-    return json.loads(response.read())",
        "+    @retry(attempts=__ATTEMPTS__, base_delay=__DELAY_S__)",
        "+    def _fetch_once():",
        "+        try:",
        "+            with urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10) as response:",
        "+                return json.loads(response.read())",
        "+        except urllib.error.HTTPError as exc:",
        "+            if exc.code == 429 or exc.code >= 500:",
        "+                raise RetryableError(f\"__FUNC__ failed with {exc.code}\", exc.code) from exc",
        "+            raise",
        "+",
        "+    return _fetch_once()",
    ],
    "timeout": [
        "-    response = urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10)",
        "-    return json.loads(response.read())",
        "+    def _fetch():",
        "+        with urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=__DELAY_S__) as response:",
        "+            return json.loads(response.read())",
        "+",
        "+    return with_timeout(_fetch, timeout=__DELAY_S__)",
    ],
    "cache": [
        "-    response = urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10)",
        "-    return json.loads(response.read())",
        "+    def _load():",
        "+        with urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10) as response:",
        "+            return json.loads(response.read())",
        "+",
        '+    return cached(f"__FUNC__:{user_id}", ttl=30.0, loader=_load)',
    ],
    "ratelimit": [
        "-    response = urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10)",
        "-    return json.loads(response.read())",
        "+    if not _BUCKET.take():",
        '+        raise RuntimeError("__FUNC__: rate limit wait exceeded")',
        "+    with urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10) as response:",
        "+        return json.loads(response.read())",
    ],
    "validate": [
        "-    response = urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10)",
        "-    return json.loads(response.read())",
        '+    safe_id = require_str(user_id, "user_id")',
        "+    with urllib.request.urlopen(f\"{API_BASE}/users/{safe_id}\", timeout=10) as response:",
        '+        return require_dict(json.loads(response.read()), "user")',
    ],
    "auth": [
        "-    response = urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10)",
        "-    return json.loads(response.read())",
        '+    require_bearer(authorization, scopes=("users:read",))',
        "+    request = urllib.request.Request(",
        "+        f\"{API_BASE}/users/{user_id}\",",
        "+        headers={\"Authorization\": authorization or \"\"},",
        "+    )",
        "+    with urllib.request.urlopen(request, timeout=10) as response:",
        "+        return json.loads(response.read())",
    ],
    "paginate": [
        "-    response = urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10)",
        "-    return json.loads(response.read())",
        "+    with urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10) as response:",
        "+        rows = json.loads(response.read())",
        "+    return paginate(rows, limit=limit, cursor=cursor)",
    ],
    "logging": [
        "-    response = urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10)",
        "-    return json.loads(response.read())",
        "+    def _fetch():",
        "+        with urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10) as response:",
        "+            return json.loads(response.read())",
        "+",
        '+    return instrument("__FUNC__, _fetch)',
    ],
    "errors": [
        "-    response = urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10)",
        "-    return json.loads(response.read())",
        "+    try:",
        "+        with urllib.request.urlopen(f\"{API_BASE}/users/{user_id}\", timeout=10) as response:",
        "+            return json.loads(response.read())",
        "+    except Exception as exc:",
        '+        raise to_upstream_error(exc, "__FUNC__") from exc',
    ],
}


def _subst(lines, func, attempts, delay, snake):
    out = []
    for ln in lines:
        ln = (ln.replace("__FUNC__", func)
                .replace("__ATTEMPTS__", str(attempts))
                .replace("__DELAY__", str(delay))
                .replace("__DELAY_S__", ("%g" % (delay / 1000.0)))
                .replace("__CACHE__", "_cache_" + snake)
                .replace("__INFLIGHT__", "_inflight_" + snake)
                .replace("__BUCKET__", "_bucket_" + snake))
        out.append(ln)
    return out


TS_TESTS = {
    "retry": [
        'describe("__FUNC__ retry", () => {',
        '  it("retries on 503 and returns the payload on a later attempt", async () => {',
        "    const fetchMock = jest",
        "      .spyOn(global, \"fetch\")",
        "      .mockResolvedValueOnce(new Response(\"nope\", { status: 503 }))",
        '      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "u1" }), { status: 200 }));',
        "    await expect(__FUNC__(\"u1\")).resolves.toEqual({ id: \"u1\" });",
        "    expect(fetchMock).toHaveBeenCalledTimes(2);",
        "  });",
        "",
        '  it("does not retry a 404", async () => {',
        "    const fetchMock = jest",
        "      .spyOn(global, \"fetch\")",
        "      .mockResolvedValue(new Response(\"missing\", { status: 404 }));",
        "    await expect(__FUNC__(\"u1\")).rejects.toThrow(/404/);",
        "    expect(fetchMock).toHaveBeenCalledTimes(1);",
        "  });",
        "",
        '  it("gives up after __ATTEMPTS__ attempts and surfaces the last error", async () => {',
        "    jest.spyOn(global, \"fetch\").mockResolvedValue(new Response(\"boom\", { status: 500 }));",
        "    await expect(__FUNC__(\"u1\")).rejects.toThrow(/500/);",
        "  });",
        "});",
    ],
    "ratelimit": [
        'describe("__FUNC__ rate limiting", () => {',
        '  it("serialises calls through the shared token bucket", async () => {',
        "    await Promise.all([__FUNC__(\"a\"), __FUNC__(\"b\"), __FUNC__(\"c\")]);",
        "    expect(_bucket_" + "__SN__" + ".tryTake(999)).toBe(false);",
        "  });",
        "});",
    ],
    "timeout": [
        'describe("__FUNC__ timeout", () => {',
        '  it("aborts and reports a timeout when upstream hangs", async () => {',
        "    jest.spyOn(global, \"fetch\").mockImplementation(() => new Promise(() => {}));",
        "    await expect(__FUNC__(\"u1\")).rejects.toThrow(/timed out/);",
        "  });",
        "});",
    ],
    "cache": [
        'describe("__FUNC__ caching", () => {',
        '  it("serves the second call from cache without a new request", async () => {',
        '    const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue(',
        '      new Response(JSON.stringify({ id: "u1" }), { status: 200 }),',
        "    );",
        "    await __FUNC__(\"u1\");",
        "    await __FUNC__(\"u1\");",
        "    expect(fetchMock).toHaveBeenCalledTimes(1);",
        "  });",
        "});",
    ],
    "validate": [
        'describe("__FUNC__ validation", () => {',
        '  it("rejects ids that are not 1-64 safe characters", async () => {',
        "    await expect(__FUNC__(\"../etc/passwd\")).rejects.toThrow(/id must be/);",
        "  });",
        "});",
    ],
    "auth": [
        'describe("__FUNC__ auth", () => {',
        '  it("throws 401 without a bearer token", async () => {',
        "    await expect(__FUNC__(\"u1\")).rejects.toMatchObject({ status: 401 });",
        "  });",
        "});",
    ],
    "paginate": [
        'describe("__FUNC__ pagination", () => {',
        '  it("returns a stable nextCursor that resumes after the last id", () => {',
        "    const first = paginate([{ id: \"a\" }, { id: \"b\" }, { id: \"c\" }], 2);",
        "    expect(first.items.map((r) => r.id)).toEqual([\"a\", \"b\"]);",
        "    expect(paginate([{ id: \"a\" }, { id: \"b\" }, { id: \"c\" }], 2, first.nextCursor).items)",
        "      .toEqual([{ id: \"c\" }]);",
        "  });",
        "});",
    ],
    "logging": [
        'describe("__FUNC__ logging", () => {',
        '  it("emits one structured info line per successful call", async () => {',
        '    const spy = jest.spyOn(console, "log").mockImplementation(() => {});',
        '    jest.spyOn(global, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));',
        '    await __FUNC__("u1");',
        '    expect(JSON.parse(spy.mock.calls[0][0] as string)).toMatchObject({ level: "info", event: "__FUNC__" });',
        "  });",
        "});",
    ],
    "errors": [
        'describe("__FUNC__ error handling", () => {',
        '  it("wraps upstream failures in UpstreamError and keeps the status", async () => {',
        '    jest.spyOn(global, "fetch").mockResolvedValue(new Response("boom", { status: 500 }));',
        '    await expect(__FUNC__("u1")).rejects.toMatchObject({ name: "UpstreamError", status: 500 });',
        "  });",
        "});",
    ],
}

PY_TESTS = {
    "retry": [
        "class Test__FUNC__(object):",
        "    def test_retries_on_503_then_succeeds(self, monkeypatch):",
        "        calls = {\"n\": 0}",
        "",
        "        def fake_urlopen(url, timeout=10):",
        "            calls[\"n\"] += 1",
        "            if calls[\"n\"] < 3:",
        "                raise urllib.error.HTTPError(url, 503, \"unavailable\", {}, None)",
        "            return _FakeResponse(b'{\"id\": \"u1\"}')",
        "",
        "        monkeypatch.setattr(urllib.request, \"urlopen\", fake_urlopen)",
        "        assert __FUNC__(\"u1\") == {\"id\": \"u1\"}",
        "        assert calls[\"n\"] == 3",
        "",
        "    def test_does_not_retry_404(self, monkeypatch):",
        "        monkeypatch.setattr(",
        "            urllib.request,",
        "            \"urlopen\",",
        "            lambda url, timeout=10: (_ for _ in ()).throw(",
        "                urllib.error.HTTPError(url, 404, \"missing\", {}, None)",
        "            ),",
        "        )",
        "        with pytest.raises(urllib.error.HTTPError):",
        "            __FUNC__(\"u1\")",
    ],
    "timeout": [
        "class Test__FUNC__(object):",
        "    def test_raises_timeout_when_upstream_hangs(self, monkeypatch):",
        "        def slow(url, timeout=10):",
        "            time.sleep(2)",
        "            return _FakeResponse(b\"{}\")",
        "",
        "        monkeypatch.setattr(urllib.request, \"urlopen\", slow)",
        "        with pytest.raises(TimeoutError):",
        "            __FUNC__(\"u1\")",
    ],
    "cache": [
        "class Test__FUNC__(object):",
        "    def test_second_call_is_served_from_cache(self, monkeypatch):",
        "        calls = {\"n\": 0}",
        "",
        "        def counting(url, timeout=10):",
        "            calls[\"n\"] += 1",
        "            return _FakeResponse(b'{\"id\": \"u1\"}')",
        "",
        "        monkeypatch.setattr(urllib.request, \"urlopen\", counting)",
        "        assert __FUNC__(\"u1\") == __FUNC__(\"u1\")",
        "        assert calls[\"n\"] == 1",
    ],
    "validate": [
        "class Test__FUNC__(object):",
        "    @pytest.mark.parametrize(\"bad\", [\"\", \"../etc/passwd\", \"a\" * 65, None])",
        "    def test_rejects_invalid_ids(self, bad):",
        "        with pytest.raises(ValidationError):",
        "            __FUNC__(bad)",
    ],
    "ratelimit": [
        "class Test__FUNC__(object):",
        "    def test_bucket_refuses_burst_over_capacity(self):",
        "        bucket = TokenBucket(capacity=2, refill_per_second=0.001)",
        "        assert bucket.take() and bucket.take()",
        "        assert bucket.take(timeout=0.05) is False",
    ],
    "auth": [
        "class Test__FUNC__(object):",
        "    def test_missing_token_raises_401(self):",
        "        with pytest.raises(AuthError) as err:",
        "            __FUNC__(\"u1\", None)",
        "        assert err.value.status == 401",
    ],
    "paginate": [
        "class Test__FUNC__(object):",
        "    def test_cursor_round_trip(self):",
        "        rows = [{\"id\": \"a\"}, {\"id\": \"b\"}, {\"id\": \"c\"}]",
        "        first = paginate(rows, limit=2)",
        "        assert [r[\"id\"] for r in first[\"items\"]] == [\"a\", \"b\"]",
        "        assert [r[\"id\"] for r in paginate(rows, limit=2, cursor=first[\"nextCursor\"])[\"items\"]] == [\"c\"]",
    ],
    "logging": [
        "class Test__FUNC__(object):",
        "    def test_logs_one_info_line_per_call(self, monkeypatch, caplog):",
        "        monkeypatch.setattr(urllib.request, \"urlopen\", lambda url, timeout=10: _FakeResponse(b\"{}\"))",
        "        with caplog.at_level(logging.INFO):",
        "            __FUNC__(\"u1\")",
        "        assert '\"event\": \"__FUNC__\"' in caplog.text",
    ],
    "errors": [
        "class Test__FUNC__(object):",
        "    def test_upstream_failure_is_wrapped(self, monkeypatch):",
        "        monkeypatch.setattr(",
        "            urllib.request,",
        "            \"urlopen\",",
        "            lambda url, timeout=10: (_ for _ in ()).throw(ConnectionError(\"reset\")),",
        "        )",
        "        with pytest.raises(UpstreamError) as err:",
        "            __FUNC__(\"u1\")",
        "        assert \"__FUNC__\" in str(err.value)",
    ],
}

HELPER_LABEL_TS = {
    "retry": "`withRetry`", "timeout": "`withTimeout`", "cache": "`cached`",
    "ratelimit": "`withRateLimit`", "validate": "`assertIdentifier`", "auth": "`requireBearer`",
    "paginate": "`paginate`", "logging": "`instrument`", "errors": "`toUpstreamError`",
}
HELPER_LABEL_PY = {
    "retry": "the `@retry` decorator", "timeout": "`with_timeout`", "cache": "`cached`",
    "ratelimit": "`TokenBucket`", "validate": "`require_str`", "auth": "`require_bearer`",
    "paginate": "`paginate`", "logging": "`instrument`", "errors": "`to_upstream_error`",
}

INTENT_RATIONALE = {
    "retry": "wraps the upstream call in {helper} with exponential backoff plus jitter so transient 5xx/429/timeout failures recover instead of surfacing to the caller",
    "timeout": "bounds the upstream call with {helper} so a hung dependency cannot pin the request handler open indefinitely",
    "cache": "memoises successful responses behind a short TTL and de-duplicates concurrent misses so repeated reads do not fan out to upstream",
    "ratelimit": "routes the call through a token bucket so bursts cannot exceed the provider quota and trip 429s",
    "validate": "validates the untrusted input before it reaches the URL/query layer, turning bad input into a typed ValidationError instead of a 500",
    "auth": "checks the bearer token and required scopes before doing any upstream I/O, returning 401/403 rather than leaking data",
    "paginate": "normalises the list response into a cursor-paginated Page so callers can page deterministically without offset drift",
    "logging": "instruments the call with a structured start/finish log line carrying duration and error context for observability",
    "errors": "normalises every failure path through UpstreamError so callers get a stable {status, message} shape and HTTP mapping",
}

INTENT_TESTS = {
    "retry": [
        "{target} retries on 503 and succeeds within maxAttempts",
        "{target} does not retry non-retryable 404",
        "{target} surfaces the last error after exhausting attempts",
    ],
    "timeout": [
        "{target} aborts when upstream exceeds the timeout",
        "{target} clears the abort timer on success",
    ],
    "cache": [
        "{target} second call is served from cache",
        "{target} concurrent misses share one in-flight request",
        "cache entry expires after TTL",
    ],
    "ratelimit": [
        "{target} waits for a token instead of bursting",
        "{target} raises when the rate-limit wait budget is exceeded",
    ],
    "validate": [
        "{target} rejects path-traversal and oversized ids",
        "{target} accepts ids matching the safe character class",
    ],
    "auth": [
        "{target} returns 401 without a bearer token",
        "{target} returns 403 when a required scope is missing",
    ],
    "paginate": [
        "{target} cursor round-trips to the next page",
        "{target} clamps limit into 1..200",
    ],
    "logging": [
        "{target} emits one info log line per successful call",
        "{target} emits an error line with duration on failure",
    ],
    "errors": [
        "{target} wraps upstream failures in UpstreamError",
        "{target} preserves the upstream status code",
    ],
}


def build_patch(spec, target=None):
    """Spec -> {patch, rationale, tests, applied}. Pure function, deterministic."""
    spec = " ".join(str(spec or "").split())
    if not spec:
        spec = "harden the request handler against transient upstream failures"
    py = _looks_python(spec, target)
    func = _function_name(spec, target)
    intents = _intents(spec)
    primary = intents[0]
    attempts, delay = _numbers(spec, 3 if primary in ("retry", "ratelimit") else 2, 250)

    helpers = PY_HELPERS if py else TS_HELPERS
    bodies = PY_BODY if py else TS_BODY
    tests_tpl = PY_TESTS if py else TS_TESTS

    if target:
        ef = os.path.basename(target)
        test_name = ("test_" + _snake(ef.replace(".py", "").replace(".ts", "")) + ".py" if py
                     else ef.replace(".ts", ".test.ts").replace(".tsx", ".test.tsx"))
        test_path = os.path.join(os.path.dirname(target), test_name) if os.path.dirname(target) else test_name
    else:
        base = _snake(func)
        file_path = ("app/" + base + ".py") if py else ("src/api/" + _kebab(func) + ".ts")
        test_path = ("tests/test_" + base + ".py") if py else ("src/api/__tests__/" + _kebab(func) + ".test.ts")

    file_path = target or file_path
    helper_key = primary if primary in helpers else "errors"
    body_key = primary if primary in bodies else "errors"
    test_key = primary if primary in tests_tpl else "errors"
    snake = _snake(func)

    helper_lines = _subst(helpers[helper_key].split("\n"), func, attempts, delay, snake)
    body_lines = _subst(bodies[body_key], func, attempts, delay, snake)
    test_lines = _subst(tests_tpl[test_key], func, attempts, delay, snake)
    test_lines = [ln.replace("__SN__", snake).replace("__CLASS__", _pascal(func)) for ln in test_lines]

    added = len(helper_lines)
    body_old_len = sum(1 for ln in body_lines if ln.startswith("-"))
    body_new_ctx = 2 + sum(1 for ln in body_lines if ln.startswith("+"))

    if py:
        signature = "def %s(user_id: str) -> dict:" % func
        tail = "    return _fetch_once()"
        if body_key != "retry":
            tail = None
    else:
        signature = "export async function %s(id: string): Promise<User> {" % func
        tail = None
    if tail and body_lines[-1].startswith("+"):
        pass

    context_head = []  # helper is emitted inline, so no new import is required

    old_start = 12
    new_start = old_start + added + 1
    hunk_body = _hunk(old_start, body_old_len + 2, new_start, body_new_ctx + 2)

    diff = []
    diff.append("--- a/" + file_path)
    diff.append("+++ b/" + file_path)
    diff.append(_hunk(1, 6, 1, 6 + added + len(context_head)))
    diff.extend(_plus((context_head + helper_lines) if context_head else helper_lines))
    diff.append(" ")
    diff.append(" " + signature)
    diff.append(hunk_body)
    diff.extend(body_lines)
    diff.append(" }" if not py else "")
    if py:
        diff = [ln for ln in diff if ln != ""]
    diff.append("")
    diff.append("--- a/" + test_path)
    diff.append("+++ b/" + test_path)
    diff.append(_hunk(0, 0, 1, len(test_lines) + 3))
    header = ["import pytest", "import urllib.error", "import urllib.request", ""] if py else []
    diff.extend(_plus(header + test_lines))
    patch_text = "\n".join(diff).rstrip() + "\n"

    test_names = [t.format(target=func) for t in INTENT_TESTS.get(primary, INTENT_TESTS["errors"])]
    helper_label = HELPER_LABEL_PY.get(primary, primary) if py else HELPER_LABEL_TS.get(primary, primary)
    why = [INTENT_RATIONALE.get(primary, INTENT_RATIONALE["errors"]).format(helper=helper_label, status="status")]
    for extra in intents[1:4]:
        why.append("secondary signal in the spec: " + INTENT_RATIONALE.get(extra, "").format(helper=helper_label, status="status"))
    rationale = (
        "Spec parsed as a %s change to `%s` (%s). %s. "
        "The diff adds one self-contained helper block plus the call-site rewrite, keeps existing imports, "
        "and ships a test file with %d cases. Patch is a template/heuristic scaffold: review line numbers "
        "and type names against the real file before applying it."
    ) % (
        "Python" if py else "TypeScript",
        func,
        ", ".join(intents[:3]),
        "; ".join(why)[:1].upper() + "; ".join(why)[1:],
        len(test_names),
    )

    return {
        "patch": patch_text,
        "rationale": rationale,
        "tests": test_names,
        "applied": False,
        "language": "python" if py else "typescript",
        "target": file_path,
        "engine": ENGINE,
        "notes": "deterministic template output; no model was called, nothing was written to disk",
        "checklist": [
            "confirm the function signature and imports in the real file",
            "re-anchor hunk line numbers with `git apply --recount`",
            "run the suggested tests, then `git apply` and fix type errors",
        ],
    }


def sample_spec():
    return "add retry with exponential backoff to fetchUser"


def post_json(url, payload, timeout=25):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("user-agent", "kognai-coder/0.1")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")


class Handler(BaseHTTPRequestHandler):
    server_version = "kognai-coder/0.2"

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
        path, _, query = self.path.partition("?")
        if path in ("/health", "/"):
            return self.send(200, {"ok": True, "service": "kognai-coder", "paid": bool(PAY_TO), "x402": True})
        if path == "/openapi.json":
            return self.serve_doc("openapi.json", "application/json")
        if path == "/llms.txt":
            return self.serve_doc("llms.txt", "text/plain; charset=utf-8")
        if path in ("/.well-known/x402", "/.well-known/x402.json"):
            return self.send_raw(200, json.dumps(self.discovery_document()), "application/json")
        if path == "/patch" and _dry(query):
            spec = _qs(query, "spec") or sample_spec()
            return self.send(200, build_patch(spec, _qs(query, "target")))
        if path.startswith("/media/"):
            return self.serve_media(path[len("/media/"):])
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
        path, _, query = self.path.partition("?")
        if path != "/patch":
            return self.send(404, {"error": "not found"})

        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:
            return self.send(400, {"error": "body must be JSON"})

        if _dry(query):
            spec = body.get("spec") if isinstance(body, dict) else None
            target = body.get("target") if isinstance(body, dict) else None
            return self.send(200, build_patch(spec or sample_spec(), target))

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

        spec = body.get("spec") if isinstance(body, dict) else None
        target = body.get("target") if isinstance(body, dict) else None
        answer = build_patch(spec, target)
        encoded = base64.b64encode(json.dumps(settled).encode()).decode()
        return self.send(200, answer, {"X-PAYMENT-RESPONSE": encoded})


def _qs(query, key):
    from urllib.parse import parse_qs
    values = parse_qs(query or "").get(key) or []
    return values[0] if values else None


def _dry(query):
    from urllib.parse import parse_qs
    params = parse_qs(query or "")
    if "dry" not in params and "dryRun" not in params:
        return False
    value = (params.get("dry") or params.get("dryRun"))[0].lower()
    return value not in ("0", "false", "no", "")


if __name__ == "__main__":
    if "--dry-run" in sys.argv or "--dry" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        print(json.dumps(build_patch(args[0] if args else sample_spec(),
                                     args[1] if len(args) > 1 else None), indent=2))
        raise SystemExit(0)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
