# agentic-paypal

An AI agent that understands a payment goal ("get me paid $2,500 by Acme") and manages the PayPal
payment lifecycle: create and send an invoice, watch it, chase it when overdue, explain why it hasn't been
paid, and refund on request. Built on PayPal's **Sandbox** REST API, LangGraph and an Ollama Cloud model.

| Doc | What's in it |
|---|---|
| [CHECKPOINT.md](CHECKPOINT.md) | Progress, what's left, and **why** each decision was made |
| [HANDOVER.md](HANDOVER.md) | Original handover notes |
| [docs/DEMO.md](docs/DEMO.md) | 2–3 minute demo script and recovery table |
| [postman/](postman/) | Postman collection + local environment for end-to-end API testing |

## Run it

Needs `.env` (copy `.env.example`): `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_INVOICER_EMAIL`,
`OLLAMA_API_KEY`. Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
# backend
uv sync
PYTHONPATH=src uv run uvicorn paypal_agent.main:app --port 8000   # docs at /docs

# frontend (second terminal)
cd frontend && npm install && npm run dev      # http://localhost:3000/dashboard
```

Tests (no keys needed, they use fakes and a temp database): `uv run pytest`

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `APP_ENV` | `development` | Demo endpoints and the "Simulate overdue" button only work in `development` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./paypal_agent.db` | Events, invoice state, remembered customers |
| `MONITOR_ENABLED` / `MONITOR_INTERVAL_SECONDS` | `true` / `60` | Background polling of invoices |
| `MONITOR_AUTO_REMIND` | `true` | Auto-remind overdue invoices (max once a day each) |
| `DEFAULT_DUE_DAYS` | `14` | Due date when the user gives no terms |
| `PAYPAL_WEBHOOK_ID` | empty | Enables verified PayPal webhooks (below) |
| `WEBHOOK_ALLOW_UNVERIFIED` | `false` | Local testing only: accept webhooks without verifying |

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
