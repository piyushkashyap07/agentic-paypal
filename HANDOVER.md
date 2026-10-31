# Handover: where things stand

Branch to start from: **`feature/frontend`**. It contains everything below, including the work from `feature/send-and-monitor`.

## Run it

```bash
# backend (repo root). Needs .env with PayPal + OLLAMA_API_KEY
uv sync
uv run uvicorn paypal_agent.main:app --port 8000

# frontend (second terminal)
cd frontend && npm install && npm run dev
# open http://localhost:3000 and http://localhost:3000/dashboard
```

Tests: `uv run pytest` (21 passing). They use fakes, so no keys are needed.

Sandbox note: the seller account can be in India, but the **buyer must be a US Personal sandbox account**. PayPal blocks invoices sent to India buyers.

## Done ✅ (tested on the sandbox with the real AI)

| Feature | Where |
|---|---|
| Chat → AI understands the request → asks CONFIRM → creates draft invoice | `agent/nodes.py`, `agent/graph.py` |
| SEND / status / remind / refund from chat (refund needs `CONFIRM REFUND`) | `agent/nodes.py` |
| REST endpoints: send, get, list, remind, refund, events | `api/routes.py` |
| Background monitor: checks every 60s, logs status changes, auto-reminds overdue invoices at most once a day | `workers/payment_monitor.py` |
| Next.js frontend: landing page `/` and `/dashboard` (stats, chat, invoice list with buttons, activity feed) | `frontend/` |

Last live test: chat created and sent `INV2-748T-FQDD-W9ZP-PNWC` ($300), then answered a status question correctly.

## Left to do

### Must do (core demo)
| # | Task | Hint |
|---|---|---|
| 1 | Show the agent's **plan** in the chat ("create → send → watch") | Add it to the reply in `understand_request` / the confirm message |
| 2 | Push monitor updates **into the chat** ("Acme paid!") | Events already exist (`GET /api/events`); Chat.tsx could poll them and add them as agent messages |
| 3 | **Overdue demo**: we can't wait days in a live demo | Try an invoice with a past due date, or add a "demo mode" button |
| 4 | Save events in SQLite (they're in memory now and lost on restart) | `workers/payment_monitor.py` → `events` list |
| 5 | Merge `feature/frontend` → `main` via a PR | |

### Pick ONE extra pain point (team decision)
| Option | PayPal API | Note |
|---|---|---|
| Disputes: explain a dispute and suggest an action | `/v1/customer/disputes` | Strongest story, but sandbox disputes are hard to create, so test that first |
| "Why haven't I been paid?" explainer | invoice + `/v1/reporting/transactions` | Easiest |
| Shipment tracking | `/v1/shipping/trackers` | Weak for freelancers |

### Only if time is left
Earnings insights, orders/pay links, subscriptions.

### Demo
Demo script (one story, 2–3 min), clean sandbox data, backup video, README.

## Open team decisions
Target user (freelancer?), which extra pain point, demo story, overdue demo method.
