"use client";

import { useState } from "react";

import CollapseToggle from "@/components/CollapseToggle";
import { api, Invoice, InvoiceAction } from "@/lib/api";
import { formatMoney } from "@/lib/money";

const ACTIONS: { action: InvoiceAction; label: string; statuses: string[] }[] =
  [
    { action: "send", label: "Send", statuses: ["DRAFT"] },
    {
      action: "remind",
      label: "Remind",
      statuses: ["SENT", "UNPAID", "PARTIALLY_PAID"],
    },
    {
      action: "refund",
      label: "Refund",
      statuses: ["PAID", "PARTIALLY_REFUNDED"],
    },
    { action: "cancel", label: "Cancel", statuses: ["SENT", "UNPAID"] },
    // Demo helper: we can't wait days for a real due date. Hidden in production builds.
    ...(process.env.NODE_ENV !== "production"
      ? [
          {
            action: "simulate-overdue" as InvoiceAction,
            label: "Simulate overdue",
            statuses: ["SENT", "UNPAID", "PARTIALLY_PAID"],
          },
        ]
      : []),
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
  const [open, setOpen] = useState(true);

  async function run(invoice: Invoice, action: InvoiceAction) {
    if (
      action === "refund" &&
      !window.confirm(
        `Refund ${formatMoney(invoice.amount, invoice.currency)} to ${invoice.customer_email}?`,
      )
    ) {
      return;
    }

    if (
      action === "cancel" &&
      !window.confirm(
        `Cancel invoice ${invoice.invoice_id}? The customer will be told no payment is needed.`,
      )
    ) {
      return;
    }

    setWorking(invoice.invoice_id + action);
    setNotice(null);

    try {
      await api.invoiceAction(invoice.invoice_id, action);
      const done = {
        send: "Sent",
        remind: "Reminder sent for",
        refund: "Refunded",
        cancel: "Cancelled",
        "simulate-overdue": "Marked overdue and chased",
      }[action];
      setNotice(`${done} ${invoice.invoice_id}.`);
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
        <div className="card-head-right">
          <span className="card-sub">
            {invoices ? `${invoices.length} total` : ""}
          </span>
          <CollapseToggle
            open={open}
            onToggle={() => setOpen(!open)}
            label="invoices"
          />
        </div>
      </div>

      {open && notice && (
        <div className="empty" style={{ paddingBottom: 0 }}>
          {notice}
        </div>
      )}

      {open && (
        <div className="invoice-list">
          {error && <div className="empty">{error}</div>}
          {!error && invoices === null && (
            <div className="empty">Loading invoices from PayPal…</div>
          )}
          {!error && invoices?.length === 0 && (
            <div className="empty">
              No invoices yet. Ask the agent to create one.
            </div>
          )}

          {invoices?.map((invoice) => (
            <div className="invoice" key={invoice.invoice_id}>
              <div className="invoice-top">
                <span className="invoice-amount">
                  {formatMoney(invoice.amount, invoice.currency)}
                </span>
                <span className={`badge ${invoice.status}`}>
                  {invoice.simulated_overdue ||
                  invoice.next_action === "send_reminder"
                    ? "Overdue"
                    : (STATUS_LABELS[invoice.status] ?? invoice.status)}
                </span>
              </div>
              <div className="invoice-meta">
                <span>{invoice.customer_email}</span>
                <span className="mono">{invoice.invoice_id}</span>
              </div>
              {invoice.due_date && (
                <div className="invoice-meta">Due {invoice.due_date}</div>
              )}

              <div className="invoice-actions">
                {ACTIONS.filter(({ statuses }) =>
                  statuses.includes(invoice.status),
                ).map(({ action, label }) => (
                  <button
                    key={action}
                    className={`pill pill-small ${action === "send" || action === "remind" ? "pill-blue" : "pill-outline"}`}
                    disabled={working !== null}
                    onClick={() => run(invoice, action)}
                  >
                    {working === invoice.invoice_id + action
                      ? "Working…"
                      : label}
                  </button>
                ))}
                {invoice.pay_link && invoice.status !== "DRAFT" && (
                  <a
                    className="pill pill-small pill-grey"
                    href={invoice.pay_link}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Payment page
                  </a>
                )}
                {["SENT", "UNPAID", "PARTIALLY_PAID"].includes(
                  invoice.status,
                ) && (
                  <a
                    className="pill pill-small pill-grey"
                    href={`/api/invoices/${invoice.invoice_id}/qr.png`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    QR code
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
