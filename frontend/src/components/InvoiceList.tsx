"use client";

import { useState } from "react";

import { api, Invoice, InvoiceAction } from "@/lib/api";
import { formatMoney } from "@/lib/money";

const ACTIONS: { action: InvoiceAction; label: string; statuses: string[] }[] = [
  { action: "send", label: "Send", statuses: ["DRAFT"] },
  { action: "remind", label: "Remind", statuses: ["SENT", "UNPAID", "PARTIALLY_PAID"] },
  { action: "refund", label: "Refund", statuses: ["PAID", "PARTIALLY_REFUNDED"] },
];

const STATUS_LABELS: Record<string, string> = {
  DRAFT: "Draft",
  SENT: "Awaiting payment",
  UNPAID: "Awaiting payment",
  PARTIALLY_PAID: "Partly paid",
  PAID: "Paid",
  MARKED_AS_PAID: "Paid",
  CANCELLED: "Cancelled",
  REFUNDED: "Refunded",
  PARTIALLY_REFUNDED: "Partly refunded",
};

type Props = {
  invoices: Invoice[] | null;
  error: string | null;
  onChanged: () => void;
};

export default function InvoiceList({ invoices, error, onChanged }: Props) {
  const [working, setWorking] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run(invoice: Invoice, action: InvoiceAction) {
    if (
      action === "refund" &&
      !window.confirm(`Refund ${formatMoney(invoice.amount, invoice.currency)} to ${invoice.customer_email}?`)
    ) {
      return;
    }

    setWorking(invoice.invoice_id + action);
    setNotice(null);

    try {
      await api.invoiceAction(invoice.invoice_id, action);
      setNotice(`${action === "send" ? "Sent" : action === "remind" ? "Reminder sent for" : "Refunded"} ${invoice.invoice_id}.`);
      onChanged();
    } catch (actionError) {
      setNotice((actionError as Error).message);
    } finally {
      setWorking(null);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>Invoices</h2>
        <span className="card-sub">{invoices ? `${invoices.length} total` : ""}</span>
      </div>

      {notice && <div className="empty" style={{ paddingBottom: 0 }}>{notice}</div>}

      <div className="invoice-list">
        {error && <div className="empty">{error}</div>}
        {!error && invoices === null && <div className="empty">Loading invoices from PayPal…</div>}
        {!error && invoices?.length === 0 && <div className="empty">No invoices yet. Ask the agent to create one.</div>}

        {invoices?.map((invoice) => (
          <div className="invoice" key={invoice.invoice_id}>
            <div className="invoice-top">
              <span className="invoice-amount">{formatMoney(invoice.amount, invoice.currency)}</span>
              <span className={`badge ${invoice.status}`}>{STATUS_LABELS[invoice.status] ?? invoice.status}</span>
            </div>
            <div className="invoice-meta">
              <span>{invoice.customer_email}</span>
              <span className="mono">{invoice.invoice_id}</span>
            </div>
            {invoice.due_date && <div className="invoice-meta">Due {invoice.due_date}</div>}

            <div className="invoice-actions">
              {ACTIONS.filter(({ statuses }) => statuses.includes(invoice.status)).map(({ action, label }) => (
                <button
                  key={action}
                  className={`pill pill-small ${action === "refund" ? "pill-outline" : "pill-blue"}`}
                  disabled={working !== null}
                  onClick={() => run(invoice, action)}
                >
                  {working === invoice.invoice_id + action ? "Working…" : label}
                </button>
              ))}
              {invoice.pay_link && invoice.status !== "DRAFT" && (
                <a className="pill pill-small pill-grey" href={invoice.pay_link} target="_blank" rel="noopener noreferrer">
                  Payment page
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
