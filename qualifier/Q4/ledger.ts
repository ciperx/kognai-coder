type Entry = { id: string; account: string; amount: bigint };

export function createLedger({ cap }: { cap: string }) {
  if (typeof cap !== "string" || !/^[0-9]+$/.test(cap)) {
    throw new Error("cap must be a positive integer string");
  }
  const limit = BigInt(cap);
  const byKey = new Map<string, Entry>();
  const balances = new Map<string, bigint>();
  let counter = 0;

  function balance(account: string): string {
    return (balances.get(account) ?? 0n).toString();
  }

  function post({ key, account, amount }: { key: string; account: string; amount: string }) {
    if (typeof key !== "string" || key.length === 0) throw new Error("key is required");
    if (typeof account !== "string" || account.length === 0) throw new Error("account is required");
    if (typeof amount !== "string" || !/^[0-9]+$/.test(amount)) {
      throw new Error("amount must be a positive integer string");
    }

    const existing = byKey.get(key);
    if (existing) {
      if (existing.account === account && existing.amount === BigInt(amount)) {
        return { id: existing.id, duplicate: true };
      }
      throw new Error("key reused with a different payload");
    }

    const value = BigInt(amount);
    const current = balances.get(account) ?? 0n;
    if (current + value > limit) {
      throw new Error("cap exceeded");
    }

    counter += 1;
    const entry: Entry = { id: `post_${String(counter).padStart(6, "0")}`, account, amount: value };
    byKey.set(key, entry);
    balances.set(account, current + value);
    return { id: entry.id, duplicate: false };
  }

  return { post, balance };
}
