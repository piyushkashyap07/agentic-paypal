import { Invoice } from "@/lib/api";
import { formatMoney } from "@/lib/money";

const OPEN = ["SENT", "UNPAID", "PARTIALLY_PAID"];
const NOT_BILLED = ["DRAFT", "CANCELLED"];

export default function Stats({ invoices }: { invoices: Invoice[] }) {
  const billed = invoices.filter((invoice) => !NOT_BILLED.includes(invoice.status));
  const open = invoices.filter((invoice) => OPEN.includes(invoice.status));
  const currency = billed[0]?.currency ?? "USD";

  const total = billed.reduce((sum, invoice) => sum + Number(invoice.amount ?? 0), 0);
  const outstanding = open.reduce((sum, invoice) => sum + Number(invoice.amount_due ?? 0), 0);
  const collected = billed
    .filter((invoice) => !OPEN.includes(invoice.status))
    .reduce((sum, invoice) => sum + Number(invoice.amount ?? 0) - Number(invoice.amount_due ?? 0), 0);

  const items = [
    { label: "Collected", value: formatMoney(collected, currency), featured: true },
    { label: "Outstanding", value: formatMoney(outstanding, currency) },
    { label: "Total invoiced", value: formatMoney(total, currency) },
    { label: "Awaiting payment", value: String(open.length) },
  ];

  return (
    <div className="stats">
      {items.map((item) => (
        <div key={item.label} className={`stat ${item.featured ? "featured" : ""}`}>
          <div className="stat-label">{item.label}</div>
          <div className="stat-value">{item.value}</div>
        </div>
      ))}
    </div>
  );
}
