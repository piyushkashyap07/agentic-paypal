"use client";

import { useState } from "react";

import CollapseToggle from "@/components/CollapseToggle";
import Dialog, { DialogAction } from "@/components/Dialog";
import { api, Invoice, InvoiceAction } from "@/lib/api";
import { formatMoney } from "@/lib/money";

const OPEN_STATUSES = ["SENT", "UNPAID", "PARTIALLY_PAID"];

const ACTIONS: { action: InvoiceAction; label: string; statuses: string[] }[] =
  [
    { action: "send", label: "Send", statuses: ["DRAFT"] },
    { action: "remind", label: "Remind", statuses: OPEN_STATUSES },
    {
      action: "refund",
      label: "Refund",
      statuses: ["PAID", "PARTIALLY_REFUNDED"],
    },
    { action: "cancel", label: "Cancel", statuses: ["SENT", "UNPAID"] },
    { action: "delete", label: "Delete", statuses: ["DRAFT"] },
    // Demo helper: we can't wait days for a real due date. Hidden in production builds.
    ...(process.env.NODE_ENV !== "production"
      ? [
          {
            action: "simulate-overdue" as InvoiceAction,
            label: "Simulate overdue",
            statuses: OPEN_STATUSES,
          },
        ]
      : []),
  ];

// Actions that need a yes/no first, shown in our own pop-up.
const NEEDS_CONFIRMATION: InvoiceAction[] = ["refund", "cancel", "delete"];

const DONE: Record<InvoiceAction, string> = {
  send: "Sent",
  remind: "Reminder sent for",
  refund: "Refunded",
  cancel: "Cancelled",
  "cancel-delete": "Cancelled and deleted",
  delete: "Deleted",
  reopen: "Reopened as a new draft:",
  "simulate-overdue": "Marked overdue and chased",
};

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

function badgeText(invoice: Invoice): string {
  // "Overdue" only while money is still owed; a paid invoice is just Paid.
  const overdue =
    OPEN_STATUSES.includes(invoice.status) &&
    (invoice.simulated_overdue || invoice.next_action === "send_reminder");

  return overdue ? "Overdue" : (STATUS_LABELS[invoice.status] ?? invoice.status);
}

type Props = {
  invoices: Invoice[] | null;
  error: string | null;
  onChanged: () => void;
};

type Confirming = { invoice: Invoice; action: InvoiceAction } | null;

export default function InvoiceList({ invoices, error, onChanged }: Props) {
  const [working, setWorking] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState(true);
  const [confirming, setConfirming] = useState<Confirming>(null);
  const [binOpen, setBinOpen] = useState(false);

  // Cancelled invoices live in the bin (red Delete button), not the main list.
  const active = invoices?.filter((invoice) => invoice.status !== "CANCELLED") ?? null;
  const cancelled = invoices?.filter((invoice) => invoice.status === "CANCELLED") ?? [];

  async function run(invoice: Invoice, action: InvoiceAction) {
    setConfirming(null);
    setWorking(invoice.invoice_id + action);
    setNotice(null);

    try {
      const result = (await api.invoiceAction(invoice.invoice_id, action)) as {
        invoice_id?: string;
      };
      const subject = action === "reopen" ? result?.invoice_id : invoice.invoice_id;
      setNotice(`${DONE[action]} ${subject}.`);
      onChanged();
    } catch (actionError) {
      setNotice((actionError as Error).message);
    } finally {
      setWorking(null);
    }
  }

  async function deleteAllCancelled() {
    setBinOpen(false);
    setWorking("bin");
    setNotice(null);

    try {
      const { count } = await api.deleteCancelled();
      setNotice(`Deleted ${count} cancelled invoice(s).`);
      onChanged();
    } catch (deleteError) {
      setNotice((deleteError as Error).message);
    } finally {
      setWorking(null);
    }
  }

  function onAction(invoice: Invoice, action: InvoiceAction) {
    if (NEEDS_CONFIRMATION.includes(action)) {
      setConfirming({ invoice, action });
    } else {
      run(invoice, action);
    }
  }

  function confirmDialog() {
    if (!confirming) return null;

    const { invoice } = confirming;
    const money = formatMoney(invoice.amount, invoice.currency);
    const close = () => setConfirming(null);
    const keep: DialogAction = { label: "Keep it", variant: "plain", onClick: close };

    const content: Record<string, { title: string; text: string; actions: DialogAction[] }> = {
      cancel: {
        title: "Cancel this invoice?",
        text: `${money} to ${invoice.customer_email}. The customer will be told no payment is needed. "Cancel & delete" also removes it from your dashboard.`,
        actions: [
          keep,
          { label: "Cancel invoice", onClick: () => run(invoice, "cancel") },
          { label: "Cancel & delete", variant: "danger", onClick: () => run(invoice, "cancel-delete") },
        ],
      },
      refund: {
        title: "Refund this payment?",
        text: `${money} goes back to ${invoice.customer_email}. This can't be undone.`,
        actions: [keep, { label: "Refund", variant: "danger", onClick: () => run(invoice, "refund") }],
      },
      delete: {
        title: "Delete this draft?",
        text: `The ${money} draft for ${invoice.customer_email} is deleted from PayPal. It was never sent.`,
        actions: [keep, { label: "Delete", variant: "danger", onClick: () => run(invoice, "delete") }],
      },
    };

    const { title, text, actions } = content[confirming.action];

    return (
      <Dialog title={title} actions={actions} onClose={close}>
        <p>{text}</p>
        <p className="mono dialog-sub">{invoice.invoice_id}</p>
      </Dialog>
    );
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>Invoices</h2>
        <div className="card-head-right">
          <span className="card-sub">{active ? `${active.length} total` : ""}</span>
          <button
            type="button"
            className="pill pill-small pill-danger"
            onClick={() => setBinOpen(true)}
            disabled={working !== null}
            title="Cancelled invoices"
          >
            Delete{cancelled.length ? ` (${cancelled.length})` : ""}
          </button>
          <CollapseToggle open={open} onToggle={() => setOpen(!open)} label="invoices" />
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
          {!error && active === null && <div className="empty">Loading invoices from PayPal…</div>}
          {!error && active?.length === 0 && (
            <div className="empty">No invoices yet. Ask the agent to create one.</div>
          )}

          {active?.map((invoice) => (
            <div className="invoice" key={invoice.invoice_id}>
              <div className="invoice-top">
                <span className="invoice-amount">{formatMoney(invoice.amount, invoice.currency)}</span>
                <span className={`badge ${invoice.status}`}>{badgeText(invoice)}</span>
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
                    className={`pill pill-small ${
                      action === "send" || action === "remind"
                        ? "pill-blue"
                        : action === "delete"
                          ? "pill-danger"
                          : "pill-outline"
                    }`}
                    disabled={working !== null}
                    onClick={() => onAction(invoice, action)}
                  >
                    {working === invoice.invoice_id + action ? "Working…" : label}
                  </button>
                ))}
                {invoice.pay_link && invoice.status !== "DRAFT" && (
                  <a className="pill pill-small pill-grey" href={invoice.pay_link} target="_blank" rel="noopener noreferrer">
                    Payment page
                  </a>
                )}
                {OPEN_STATUSES.includes(invoice.status) && (
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

      {confirmDialog()}

      {binOpen && (
        <Dialog
          title="Cancelled invoices"
          onClose={() => setBinOpen(false)}
          actions={[
            { label: "Close", variant: "plain", onClick: () => setBinOpen(false) },
            ...(cancelled.length
              ? [{ label: "Delete all", variant: "danger" as const, onClick: deleteAllCancelled }]
              : []),
          ]}
        >
          {cancelled.length === 0 ? (
            <p>No cancelled invoices.</p>
          ) : (
            <>
              <p className="dialog-sub">
                Delete removes them from your dashboard. Reopen makes a fresh copy you can send again.
              </p>
              <div className="bin-list">
                {cancelled.map((invoice) => (
                  <div className="bin-row" key={invoice.invoice_id}>
                    <div>
                      <strong>{formatMoney(invoice.amount, invoice.currency)}</strong>
                      <div className="invoice-meta">{invoice.customer_email}</div>
                      <div className="mono invoice-meta">{invoice.invoice_id}</div>
                    </div>
                    <div className="bin-actions">
                      <button
                        type="button"
                        className="pill pill-small pill-outline"
                        onClick={() => {
                          setBinOpen(false);
                          run(invoice, "reopen");
                        }}
                      >
                        Reopen
                      </button>
                      <button
                        type="button"
                        className="pill pill-small pill-danger"
                        onClick={() => {
                          setBinOpen(false);
                          run(invoice, "delete");
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </Dialog>
      )}
    </div>
  );
}
