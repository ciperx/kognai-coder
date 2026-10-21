const ARABIC_INDIC = "٠١٢٣٤٥٦٧٨٩";

function toLatinDigits(input: string): string {
  let out = "";
  for (const ch of input) {
    const idx = ARABIC_INDIC.indexOf(ch);
    out += idx >= 0 ? String(idx) : ch;
  }
  return out;
}

export function plainAmount(value: string, decimals: number, symbol: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error("value must be a non empty string");
  }
  if (!Number.isInteger(decimals) || decimals < 2) {
    throw new Error("decimals must be an integer of at least 2");
  }
  if (typeof symbol !== "string" || symbol.trim().length === 0) {
    throw new Error("symbol must be a non empty string");
  }

  let body = toLatinDigits(value.trim());
  let negative = false;
  if (body.startsWith("-")) {
    negative = true;
    body = body.slice(1);
  }
  if (!/^[0-9]+$/.test(body)) {
    throw new Error("value must be an integer in base units");
  }

  const units = BigInt(body);
  const factor = 10n ** BigInt(decimals);
  const whole = units / factor;
  const remainder = units % factor;

  let fraction = remainder.toString().padStart(decimals, "0");
  while (fraction.length > 2 && fraction.endsWith("0")) {
    fraction = fraction.slice(0, -1);
  }

  const grouped = whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const amount = `${grouped}.${fraction}`;
  return `${negative ? "minus " : ""}${amount} ${symbol}`;
}
