export function formatMoney(value: string | number | null, currency: string | null = "USD") {
  const amount = Number(value ?? 0);

  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency ?? ""}`.trim();
  }
}
