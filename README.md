# agentic-paypal

An AI agent that understands a payment goal ("get me paid $2,500 by Acme") and manages the PayPal
payment lifecycle: create and send an invoice, watch it, chase it when overdue, explain why it hasn't been
paid, and refund on request. Talks to PayPal through the official **PayPal MCP server** (`@paypal/mcp`, Sandbox), with LangGraph and an Ollama Cloud model.

| Doc | What's in it |
|---|---|
| [CHECKPOINT.md](CHECKPOINT.md) | Progress, what's left, and **why** each decision was made |
| [HANDOVER.md](HANDOVER.md) | Original handover notes |
| [docs/DEMO.md](docs/DEMO.md) | 2–3 minute demo script and recovery table |
| [postman/](postman/) | Postman collection + local environment for end-to-end API testing |

## Run it

Needs `.env` (copy `.env.example`): `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_INVOICER_EMAIL`,
`OLLAMA_API_KEY`. Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+ (the backend starts the PayPal MCP server with `npx`).

```bash
# backend
uv sync
PYTHONPATH=src uv run uvicorn paypal_agent.main:app --port 8000   # docs at /docs

# frontend (second terminal)
cd frontend && npm install && npm run dev      # http://localhost:3000/dashboard
```

Tests (no keys needed, they use fakes and a temp database): `uv run pytest`  
Frontend tests: `cd frontend && npm test` (vitest, no backend needed).

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `APP_ENV` | `development` | Demo endpoints and the "Simulate overdue" button only work in `development` |
| `PAYPAL_TRANSPORT` | `mcp` | `mcp` = PayPal calls go through the PayPal MCP server; `rest` = direct REST API (fallback) |
| `LLM_PROVIDER` | `ollama` | AI model: `ollama` (Ollama Cloud, `OLLAMA_API_KEY`) or `gemini` (Google, free key from aistudio.google.com, `GEMINI_API_KEY`) |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Lightest Gemini model, low thinking: ~1.5 s replies, easy on the free quota |
| `ALLOWED_ORIGINS` | `http://localhost:3000,…:3001` | Browser origins allowed to make changes; other websites get 403 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./paypal_agent.db` | Events, invoice state, remembered customers |
| `MONITOR_ENABLED` / `MONITOR_INTERVAL_SECONDS` | `true` / `60` | Background polling of invoices |
| `MONITOR_AUTO_REMIND` | `true` | Auto-remind overdue invoices (max once a day each) |
| `DEFAULT_DUE_DAYS` | `14` | Due date when the user gives no terms |
| `PAYPAL_WEBHOOK_ID` | empty | Enables verified PayPal webhooks (below) |
| `WEBHOOK_ALLOW_UNVERIFIED` | `false` | Local testing only: accept webhooks without verifying |

## How PayPal is called (MCP)

The backend starts `npx @paypal/mcp --tools=all` once, keeps one MCP connection open, and restarts it
before the access token expires (`services/paypal_mcp_client.py`).

| Our action | MCP tool |
|---|---|
| Create draft | `create_invoice` (then `get_invoice` for the full invoice) |
| Send / remind | `send_invoice` / `send_invoice_reminder` |
| Status / list | `get_invoice` / `list_invoices` |
| Refund | `get_invoice` (find capture id) → `create_refund` |
| Cancel a sent invoice | `cancel_sent_invoice` |
| QR code to pay | `generate_invoice_qr_code` |
| Refund status | `get_invoice` (refund ids) → `get_refund` |
| Earnings | `list_transactions` (falls back to paid invoices if the app lacks Transaction Search) |
| Disputes | `list_disputes`, `get_dispute`, `accept_dispute_claim` |
| Pay links (no invoice) | `create_order` → `get_order` → `pay_order` once the buyer approved |
| Shipment tracking | `create_shipment_tracking`, `get_shipment_tracking` (needs the app's tracking permission) |

These extra features (`services/paypal_commerce_service.py`) only exist on the MCP route.
In chat: "how much did I earn this month?", "any disputes?", "explain dispute PP-D-…",
"accept dispute PP-D-…" (then **CONFIRM ACCEPT**), "cancel this invoice" (then **CONFIRM CANCEL**), "QR",
"refund status", "add tracking 1Z… UPS", "payment link for $50 for a consultation", "was the payment link paid?".

MCP's `create_invoice` has no due-date field, so the due date is written in the invoice note and stored in
our database; `get_invoice` / `list_invoices` fill it back in so the monitor and "why unpaid" still work.
Webhook signature checks use REST, because PayPal MCP has no tool for them.

## Webhooks (optional, instant updates instead of waiting up to 60s)

1. Expose the backend, e.g. `ngrok http 8000`.
2. In the PayPal developer dashboard (sandbox app) add a webhook to `https://<tunnel>/api/webhooks/paypal` for the
   `INVOICING.INVOICE.*` events, and copy its **Webhook ID** into `PAYPAL_WEBHOOK_ID`.
3. Restart the backend. Events are verified with PayPal, and the invoice is re-read from PayPal before anything
   changes, so a forged request can't fake a payment. Polling stays on as a safety net.

## Chat shortcuts

`CONFIRM` · `SEND` · `STATUS` · `REMIND` · `REFUND` (then `CONFIRM REFUND`) · `WHY` · `CANCEL`.
Replies are forgiving about case and punctuation ("Confirm!").

## Layout

```
src/paypal_agent/
  agent/      LangGraph conversation (nodes, graph, state, prompts)
  api/        REST routes + PayPal webhook
  services/   PayPal client (retries, token cache), "why unpaid" explainer
  workers/    background payment monitor
  database/   SQLAlchemy models + repositories (SQLite)
frontend/     Next.js dashboard (landing page + /dashboard)
scripts/      check_ollama.py, check_paypal_invoice.py, reset_demo.py
```

Sandbox rule: the seller account can be anywhere, but the **buyer must be a US Personal sandbox account**.
