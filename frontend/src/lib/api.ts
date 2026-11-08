// Small typed wrapper around the FastAPI backend (see next.config.ts).

export type Invoice = {
  invoice_id: string;
  status: string;
  customer_email: string | null;
  amount: string | null;
  currency: string | null;
  amount_due: string | null;
  due_date: string | null;
  pay_link: string | null;
  next_action: string;
  simulated_overdue?: boolean;
};

export type AgentEvent = {
  id: number;
  time: string;
  invoice_id: string;
  message: string;
};

export type ChatReply = {
  message: string;
  thread_id: string;
  status: string;
};

export type InvoiceAction = "send" | "remind" | "refund" | "cancel" | "simulate-overdue";

export type Earnings = {
  days: number;
  from: string;
  to: string;
  received: string;
  refunded: string;
  net: string;
  payments: number;
  currency: string;
  source: "transactions" | "invoices";
};

export type Dispute = {
  dispute_id: string;
  reason: string | null;
  status: string | null;
  amount: string | null;
  currency: string | null;
  respond_by: string | null;
  needs_action: boolean;
};

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail ?? "The request failed. Is the backend running?");
  }

  return data as T;
}

export const api = {
  chat: (message: string, threadId: string | null) =>
    request<ChatReply>("POST", "/api/chat", { message, thread_id: threadId }),

  listInvoices: () => request<Invoice[]>("GET", "/api/invoices"),

  listEvents: () => request<AgentEvent[]>("GET", "/api/events"),

  earnings: (days = 30) => request<Earnings>("GET", `/api/earnings?days=${days}`),

  listDisputes: () => request<Dispute[]>("GET", "/api/disputes"),

  invoiceAction: (invoiceId: string, action: InvoiceAction) =>
    request<unknown>(
      "POST",
      // Demo-only endpoint lives outside /invoices (see CHECKPOINT.md #3).
      action === "simulate-overdue"
        ? `/api/demo/invoices/${invoiceId}/simulate-overdue`
        : `/api/invoices/${invoiceId}/${action}`,
      action === "refund" ? {} : undefined,
    ),
};
