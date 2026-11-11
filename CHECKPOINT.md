# Checkpoint

Living progress log. Update it **when you finish (or change direction on) an item**.
Read this before picking up work. `HANDOVER.md` explains how to run the app;
this file explains what is done, what is left, and **why** we chose what we chose.

Source of truth for scope: `PayPal_AI_Hackathon_Working_Problem_Statement (1).docx`
(§ numbers below refer to it).

Branch: `dev` (merged into `main`). Effort: S < 1h, M = few hours, L = 1 day+.
Last updated: 2026-11-08 (items 1–15 done or as noted; subscriptions skipped; on `dev` and `main`).

## Updating to the latest code (since the PayPal MCP switch, D15)

1. `git checkout main && git pull`, then `uv sync` (new dependency: `mcp`).
2. Install **Node 20+**: the backend starts the PayPal MCP server with `npx`.
3. In your `.env` add `PAYPAL_TRANSPORT=mcp` and set
   `DATABASE_URL=sqlite+aiosqlite:///./paypal_agent.db` (an empty `DATABASE_URL=` crashes startup).
   Both are in `.env.example`.
4. PayPal developer dashboard → Apps & Credentials → your app → Features: tick **Transaction search** and
   **Customer disputes**, then Save. Transaction search can take hours to activate; until then earnings come from
   paid invoices. Shipment tracking isn't offered for our sandbox app.

## Status board

| # | Functionality | PS ref | Priority | Effort | Status |
|---|---|---|---|---|---|
| 1 | Agent plan shown in chat | §5.3, §12 | P0 | S | ✅ done |
| 2 | Proactive monitor updates in chat | §5.9, §11 | P0 | S | ✅ done (UI not eyeballed, see below) |
| 3 | Overdue demo path | §11, §13 | P0 | M | ✅ done |
| 4 | Outcome-first input (due date, customer lookup) | §4, §5.2 | P1 | M | ✅ done |
| 5 | Persist events in SQLite | §7 | P1 | S | ✅ done |
| 6 | Persist invoice/workflow state | §7 | P1 | M | ✅ done |
| 7 | Extra pain point: "Why haven't I been paid?" | §10, §13 | P1 | M | ✅ done |
| 8 | PayPal webhooks instead of polling | §7, §13 | P2 | M | 🟡 endpoint built + unit-tested; **not tried against real PayPal** (needs a public URL, see README) |
| 9 | Merge `dev` → `main` via PR, update README | n/a | P0 | S | 🟡 README done. **PR not opened/merged**: no `gh` here and merging to `main` is your call. Open: https://github.com/piyushkashyap07/agentic-paypal/compare/main...dev |
| 10 | Demo package (script, clean sandbox data, backup video) | §13 | P0 | M | 🟡 `docs/DEMO.md` + `scripts/reset_demo.py` done. **Backup video not recorded** (needs a human + sandbox buyer). |
| 11 | Hardening (error paths, raw PayPal bodies in logs, retries) | n/a | P2 | S–M | ✅ done |
| 12 | Tests for new work + frontend | n/a | P2 | S | ✅ backend: 62 pass; frontend: vitest + Testing Library (`npm test` in `frontend/`), 17 tests covering `lib/api.ts`, `lib/money.ts`, `Chat` (history skipped, "Update:" messages, no duplicates, errors, links) and `InvoiceList` (badges, per-status actions). Still not checked by eye in a real browser. |
| 13 | Cleanup stubs / leftovers | n/a | P3 | S | ✅ done |
| 14 | Orders/pay links, subscriptions, earnings insights | §8 | P3 | L | ✅ pay links + earnings done (D16); subscriptions still skipped |
| 15 | Disputes, cancel invoice, QR code, refund status, shipment tracking | §8 | P2 | M | ✅ done over MCP (D16); tracking needs the app permission |

## What was verified, and how

- `uv run pytest` → **62 passed**.
  Tests use fakes and a **temp SQLite file per test** (`tests/conftest.py`), so they never touch `paypal_agent.db`.
- `npx tsc --noEmit` and `npx eslint src` in `frontend/` → clean.
- **Live, real Ollama + PayPal sandbox** (thread `live-1`): chat created `INV2-QX8W-BY6P-P5RX-4KN8`
  ($300, "net 30" → due 2026-11-30, accepted by PayPal) → `send` → `why haven't I been paid?` →
  simulate-overdue sent a real PayPal reminder once; a second simulate did **not** re-remind.
- **Not verified:** the chat actually rendering the "Update: …" message in a browser (code is typed and linted,
  the event feed it reads was confirmed via the API). Do a 30-second eyeball: simulate overdue from the dashboard and
  watch the chat.
- The live test left sandbox data: invoice `INV2-QX8W-…` (SENT, overdue-simulated) and a
  customer "Acme Studio". Clean it before recording the demo (item 10).

## How to use the new features (for the next developer)

| Want to… | Do this |
|---|---|
| See the plan | Ask for an invoice; the confirm message and each later reply show `[x] / [>] / [ ]` steps. |
| Give payment terms | "…net 30" or "due in two weeks". Otherwise the default (`DEFAULT_DUE_DAYS`, 14) is used and the reply says so. |
| Reuse a customer | After one invoice to "Acme", "Invoice Acme $70 for a banner" needs no email. |
| Demo an overdue invoice | Dashboard → invoice card → **Simulate overdue** (dev builds only), or `POST /api/demo/invoices/{id}/simulate-overdue`. |
| Force a monitor pass | `POST /api/monitor/run` (dev only). |
| Ask why unpaid | Chat: "Why haven't I been paid?" (also the `WHY` shortcut). Works in a fresh chat; it picks the latest unpaid invoice. |
| Read new events only | `GET /api/events?after=<last id>` |

Demo endpoints return 404 unless `APP_ENV=development`.

## Manual / API testing (Postman)

`postman/paypal-agent.postman_collection.json` + `postman/local.postman_environment.json` (import both, select the
environment). 57 requests in 9 folders: health, chat happy path (run in order), chat payload variations,
cancel/gate behaviour, request validation, REST invoices (valid + invalid payloads), monitor/events, demo helpers.
Scripts save `threadId` / `invoiceId` / `payLink` automatically. Set `buyerEmail` to a **US Personal** sandbox buyer.
Folders 1, 5 and 7 create or send real **sandbox** invoices. Folders 0, 4 and 6 are safe/read-only (verified with
`npx newman run … --folder "0. Health" --folder "4. Chat: request validation" --folder "6. Monitor + events"`: 9/9 assertions pass).
The create/send/refund folders were not run through newman (they spend sandbox data); the underlying flow was verified by hand (see above).

## Open team decisions (from the PS, §13)

- **Target user:** freelancer (assumed in all UX copy until decided otherwise).
- **MCP vs REST:** decided: PayPal calls go through the **PayPal MCP server** (D15). REST stays as a fallback.
- **Which extra pain point:** we picked "Why haven't I been paid?" (D7). Disputes remain the stronger story if
  sandbox disputes can be created. Team can still swap.

## Decision log

Newest first. Format: decision → why → rejected alternatives → how to change it.

### D19. Delete, cancel & delete, reopen; in-app pop-ups (2026-11-11)
- Browser `confirm()` pop-ups replaced by an in-app dialog (`components/Dialog.tsx`): ✕, Escape and clicking outside
  all close it without doing anything.
- Cancel asks: Keep it / Cancel invoice / Cancel & delete. Drafts get a red Delete. A red **Delete (n)** button by
  "Invoices" opens the cancelled invoices: Reopen or Delete each, or Delete all.
- **PayPal can't delete sent or cancelled invoices, or un-cancel them.** So: deleting a draft deletes it in PayPal
  (REST `DELETE`, MCP has no tool for it); deleting a cancelled invoice hides it from our dashboard
  (`hidden_invoices` table); Reopen creates a fresh draft copy and hides the cancelled one.
- Fixed: a paid invoice that had been "simulated overdue" kept showing "Overdue".

### D18. Google Gemini as a second AI model (2026-11-11)
- **Why:** Ollama Cloud's free credits ran out (HTTP 402) right before recording the demo.
- **How:** `services/gemini_client.py` calls Gemini's OpenAI-compatible endpoint with plain `httpx` (no new
  dependency) and returns the same shape as the Ollama client, so the agent code didn't change.
  `LLM_PROVIDER=gemini` + `GEMINI_API_KEY` switches; default stays `ollama`.
- **Model:** `gemini-flash-lite-latest` with `reasoning_effort: low`. `gemini-2.5-flash` is closed to new keys
  (404), and `gemini-flash-latest` thinks so long it hit our 60 s timeout. Lite answers in ~1.5 s and handled the
  whole demo flow correctly (extraction, "why unpaid", earnings, disputes, pay link).
- **Busy errors:** Google's free tier sometimes returns 503 "high demand" / 429. The client retries twice (1 s, 3 s);
  asking the model again has no side effects. After that the chat shows the clear "model unavailable" message.

### D17. Security and robustness pass (2026-11-11)
Found by reviewing the code and trying the attacks for real; each fix has a test in `tests/test_security.py`.

| Problem (verified) | Fix |
|---|---|
| Any website the user visits could POST to our API (refund, cancel, remind…): a "no-cors" request from `evil.example` got **200** | `api/security.py` middleware: state-changing `/api/*` calls with a foreign `Origin` get **403**. Our frontend (`ALLOWED_ORIGINS`) and non-browser tools (no Origin) still work. Webhooks are excluded (signature-checked). |
| `next dev` listened on the Wi-Fi address (`192.168.x.x:3000`): anyone at the venue could open the dashboard | `npm run dev` / `start` now bind to `127.0.0.1`. For a phone demo on purpose: `npx next dev --hostname 0.0.0.0`. |
| Model returning a JSON list crashed the chat (`AttributeError`) | Non-object JSON is treated as "couldn't understand, rephrase". |
| No timeout on the model call; a stall hung the chat | 60 s timeout on the Ollama client. |
| Whole chat history sent every time; long chats get slow and fail | Only the last 20 messages go to the model. |
| The PayPal MCP server (an npm package) got all our env vars, incl. client secret and Ollama key | It now gets only what npx needs plus the short-lived access token. |
| Ids from URLs / the model went straight into PayPal calls | Path params must match `^[A-Za-z0-9_-]{1,64}$` (422 otherwise); model-supplied dispute ids are checked too. |
| Model out of credits (Ollama 402) showed "Something went wrong" | 503 with a clear message and the shortcuts that still work. |

Also checked, no issue: no secrets or DB files in git history; `npm audit` and `pip-audit` report 0 known
vulnerabilities; money moves only after deterministic CONFIRM words (prompt injection can't skip them); webhook
signatures are verified; PayPal error bodies aren't logged.
**Not done (fine for a local demo):** no login/API key and no rate limiting. Add both before any public deployment.

### D16. Extra PayPal tools from PS §8, all through MCP
- **What:** disputes (list / explain with advice / accept), earnings, cancel sent invoice, QR code, refund status,
  pay links (orders), shipment tracking. Chat intents + `api/commerce_routes.py` + dashboard (Cancel / QR code buttons,
  "Last 30 days" panel with earnings and disputes, QR image in chat).
- **Safety:** accepting a dispute refunds the buyer → needs `CONFIRM ACCEPT`; cancelling emails the customer → needs
  `CONFIRM CANCEL`. A pay link's money is collected (`pay_order`) only after PayPal reports the buyer APPROVED it.
- **Dispute advice is fixed text per reason**, not LLM: a wrong suggestion about money is worse than a plain one.
- **Sandbox findings:** `list_transactions` and shipment tracking return **403** for our app (missing "Transaction
  Search" / tracking features in the developer dashboard). Earnings fall back to paid invoices; tracking shows a clear
  "turn the feature on" message. `cancel_sent_invoice` refuses drafts (PayPal rule). `generate_invoice_qr_code` returns
  multipart text; we extract the PNG. Refund ids are under `refunds.transactions[].recipient_transaction_id`.
  `create_order` is USD-only in PayPal MCP and its reply has no amount.
- **Not verified live:** accepting a real dispute (sandbox has none; needs a buyer to open one), collecting a paid
  pay link (needs a buyer to approve), adding tracking (needs the permission).

### D15. PayPal calls go through the official PayPal MCP server
- **Why:** the problem statement's architecture is "AI Agent → PayPal MCP/Agent Tools → PayPal". Using PayPal's
  own MCP server makes that true instead of a slide claim.
- **How:** `services/paypal_mcp_client.py` starts `npx @paypal/mcp@1.8.1 --tools=all` once, keeps one stdio
  connection (owned by a background task, as the MCP SDK requires), and restarts it before the 9-hour token expires.
  `PayPalInvoiceService` keeps the same methods, so nodes/routes/monitor didn't change. `PAYPAL_TRANSPORT=rest`
  switches back to direct REST.
- **Gaps in MCP, and what we did:** `create_invoice` has no payment-term field → due date goes in the invoice note +
  our DB, and `get_invoice`/`list_invoices` fill it back in. `create_invoice` returns only a link → we read the id
  and call `get_invoice`. Errors come back as `{"ok": false}` in a normal result → the client checks for it.
  No tool for webhook verification → stays REST.
- **Verified live (sandbox):** chat create → send → status → "why unpaid" (due date shown), remind, list. A refund
  over MCP reached PayPal and returned PayPal's real error (that invoice was already fully refunded); a successful
  MCP refund still needs a newly paid invoice.

### D14. Item 14 (orders/pay links, subscriptions, earnings insights) skipped on purpose
- **Why:** it's the L-sized "only if time is left" item, none of it is on the demo story, and each part needs its own
  sandbox testing. Shipping it half-tested would add risk to a demo that now works end to end.
- **If you want it later:** earnings insights is the cheapest (aggregate the `invoices` table; the dashboard Stats already
  does a version of this in the browser). Subscriptions/orders need new PayPal permissions to be verified first.

### D13. Cleanup: deleted empty stubs, moved stray scripts, fixed packaging
- Deleted empty `tools/*`, `services/approval_service.py`, `services/workflow_service.py`, `agent/routing.py`
  (nothing imported them; recreate when there's real code). `test.py` / `test_paypal_invoice.py` were manual
  diagnostics, not tests, so they moved to `scripts/check_ollama.py` / `scripts/check_paypal_invoice.py`.
- `src/paypal_ai_agent/` had been deleted from the working tree, but `pyproject.toml` still pointed at it
  (`[project.scripts]`, and `uv_build` derives the module name from the project name), so a **fresh `uv sync` would have
  failed to build**. Fixed with `[tool.uv.build-backend] module-name = "paypal_agent"` and removing the dead script entry.
  Verified with `uv sync --reinstall-package paypal-ai-agent`.

### D12. Retries only where repeating a call can't do harm; PayPal errors logged by field, not by body
- **Why:** a retried "create invoice" or "refund" after a timeout could happen twice, i.e. a duplicate invoice or a
  double refund. So `send_with_retry` (in `services/paypal_invoice_service.py`) retries: connection failures always
  (the request never left), and timeouts / 429 / 502–504 **only for GET and the token request**, 3 attempts with backoff.
  POSTs are never retried after the request may have been processed.
- Raw PayPal error bodies can contain customer emails, so logs now show only status, `name`, `issue` and `debug_id`
  (`_log_paypal_error`). The `debug_id` is what PayPal support asks for.
- OAuth tokens are cached until a minute before expiry (the monitor was fetching a new one per call).
- Monitor: one failing invoice no longer stops the pass; `check_all_invoices` returns the failed ids, and
  `simulate-overdue` returns 502 if *its* invoice failed (so the demo never claims a reminder that wasn't sent).
- Replies are normalised (`normalize_reply`): "Confirm!" / "CONFIRM." now work. Still exact-match otherwise, so
  "yes please" does **not** confirm. That is intentional (money-moving steps need an unambiguous word).

### D11. Webhooks: verify with PayPal, then re-read the invoice; polling stays on
- **Why:** a webhook body is attacker-controlled. We (1) verify the signature through PayPal's
  `verify-webhook-signature` using `PAYPAL_WEBHOOK_ID`, and (2) ignore the body's claims and **re-fetch the invoice**, then
  run the same `sync_invoice` the poller uses, so events, friendly messages and "at most one reminder a day" behave
  identically and duplicate deliveries add nothing.
- Without `PAYPAL_WEBHOOK_ID` the endpoint answers 503, unless `WEBHOOK_ALLOW_UNVERIFIED=true` (local testing only).
  Errors during sync return 502 so PayPal retries the delivery.
- Polling is **not** removed: it's the safety net if a webhook is missed or the tunnel is down.
- **Not verified:** a real delivery from PayPal. Unit tests cover verified / bad signature / forged body / duplicate /
  other event types / bad JSON. Setup steps are in the README.

### D9. Keep calling PayPal's REST API (not MCP) for now
- **Why:** it already works and is tested live; items 1–7 didn't need anything MCP adds.
- **Rejected:** rewriting the tool layer onto MCP now (no demo benefit, real risk).
- **Revisit if:** judges expect MCP tools. `services/paypal_invoice_service.py` is the single seam to swap.

### D8. One SQLite file for events, invoices and customers (SQLAlchemy async)
- **Why:** `DATABASE_URL` and `sqlalchemy`/`aiosqlite` were already in the project, and the empty `database/*` stubs
  were meant for this. One DB file keeps setup at zero. Tables are created automatically on startup
  (`init_db`, `create_all`), so there are **no migrations yet**: if you change a column, delete `paypal_agent.db`
  (it is gitignored).
- **Dependency change:** `sqlalchemy` → `sqlalchemy[asyncio]` (adds `greenlet`; async mode fails without it).
- **Rejected:** raw `aiosqlite` queries (more boilerplate per query), Postgres (overkill for a hackathon).
- Persistence calls from the chat agent are **best-effort** (`best_effort()` in `agent/nodes.py`): a DB problem
  is logged and must never break the conversation. PayPal remains the source of truth for money state.

### D7. Pain point = "Why haven't I been paid?", with facts decided in Python and the LLM only phrasing them
- **Why:** easiest of the three options and works with plain sandbox invoices. The invoice object from PayPal already
  has what we need (status, due date, payments, and `viewed_by_recipient`), so `/v1/reporting/transactions` was
  **not needed**. `services/payment_explainer.py` computes reasons and one suggested action; the LLM gets only that JSON
  and is told not to invent anything. If the LLM fails we return the deterministic text, which is equally correct.
- **Why not let the LLM reason freely:** the PS stresses the agent must not claim things it can't verify
  (also rule 4 in `agent/prompts.py`).
- **Behaviour to know:** works without an invoice in the chat by picking the latest open invoice from the DB, and then
  adopts it so `REMIND` works next. `viewed_by_recipient` can be missing in PayPal's response; then we say nothing about it.
- **Rejected:** disputes (sandbox disputes hard to create, untested), shipment tracking (weak for freelancers).
- **How to change:** add a reason in `_diagnose()`; add an intent the same way `explain_unpaid` was added
  (prompt in `_understand_message`, node in `graph.py`).

### D6. Persisted reminder date + status, so a restart can't double-remind or lose changes
- **Why:** previously `_last_status` / `_last_reminder` were in-memory dicts, so a restart forgot everything.
  The monitor now compares against the `invoices` table and stores `last_reminder_on` / `reminder_count`.
- **Behaviour to know:** an invoice the monitor has never seen (e.g. created directly in PayPal) is learned
  silently, with no "status changed" event. Only changes after we know about it produce events.

### D5. Overdue demo = a per-invoice `simulate_overdue` flag, not fake dates
- **Why:** waiting days isn't possible live, and back-dating a due date is unverified against PayPal (not tried). The flag makes
  the monitor *and* the explainer treat the invoice as overdue, and the monitor then performs the **real** PayPal reminder
  call, so what the judges see is the real action, only the clock is faked.
- **Rejected:** (a) creating invoices with past due dates (PayPal behaviour unverified and it still only works at
  creation), (b) mocking the reminder (would be a fake demo).
- **Safety:** endpoints return 404 unless `APP_ENV=development`; the UI button is hidden in production builds.
  The one-reminder-per-day rule still applies, so you can't spam a customer by clicking twice.
- **To undo the flag for an invoice:** `UPDATE invoices SET simulate_overdue=0 WHERE invoice_id=…;`
  (no endpoint yet).

### D4. Due date: "due in N days" extracted by the LLM, date computed in Python; default 14 days
- **Why:** LLMs are unreliable at calendar math. The model returns an integer and Python adds it to today.
  If the user says nothing we **don't ask** (keeps the "get me paid" flow to one message) and instead use
  `DEFAULT_DUE_DAYS`, and **show the date and that it's a default** in the confirm step so it's never silent.
- **Rejected:** asking every time (friction), leaving PayPal's default (no due date → the overdue logic never fires).
- **How to change:** `default_due_days` in `config.py` (env `DEFAULT_DUE_DAYS`).

### D3. Customer lookup = remembered name → email from our own invoices
- **Why:** the PS example is "Get me paid $2,500 by Acme" with no email. We can't invent an email (hard rule in the
  system prompt), so we reuse one the user gave us before, and say "(remembered from a previous invoice)" in the confirm step.
  A first-time customer is still asked for the email.
- **Limits:** exact match on the casefolded name ("Acme" ≠ "Acme Studio"). No fuzzy matching, no import of
  customers that exist only in PayPal. Both are easy follow-ups in `database/repositories.py`.

### D2. Monitor events reach the chat by polling the events feed (no websocket/SSE)
- **Why:** the dashboard already polled `/api/events` every 5s, so the chat just reads the same list.
  Events now have an `id`; the chat remembers the newest id it showed and skips history that existed before the page
  opened (so a fresh page doesn't dump old events).
- **Behaviour to know:** updates only show on the dashboard page while it's open. Proactive push (webhooks) is item 8.
- **Rejected:** SSE/websocket (more moving parts for a 5-second gain).

### D1. The plan is deterministic text, not LLM output
- **Why:** the plan (create → send → watch) is the same for every invoice, and a hard-coded list can't hallucinate
  steps or skip the CONFIRM gate. It is rendered by `plan_text()` in `agent/nodes.py` and shows progress.
- **Trade-off:** it won't adapt to unusual goals. If we later add multi-workflow planning (refund, dispute), make the
  planner choose among fixed plans rather than free-form generation.

## Code map of what changed (items 1–7)

| Area | Files |
|---|---|
| Persistence | `database/models.py`, `session.py`, `repositories.py`; `main.py` (init/close on startup) |
| Monitor | `workers/payment_monitor.py` (async `record_event`, DB-backed change/reminder tracking, friendly messages) |
| Agent | `agent/nodes.py` (plan, due date, customer lookup, persistence, `explain_unpaid_node`), `agent/graph.py`, `agent/state.py` |
| Explainer | `services/payment_explainer.py` |
| PayPal | `services/paypal_invoice_service.py` (`due_date` → `payment_term`) |
| API | `api/routes.py` (`/events?after=`, `/monitor/run`, `/demo/…/simulate-overdue`, `simulated_overdue` in invoice list) |
| Frontend | `lib/api.ts`, `components/Chat.tsx`, `InvoiceList.tsx`, `ActivityFeed.tsx`, `app/dashboard/page.tsx` |
| Tests | `tests/conftest.py`, `tests/test_lifecycle_features.py`, `tests/test_hardening_webhooks.py` |
| Items 8–13 | `api/webhooks.py`, `services/paypal_invoice_service.py` (retry, token cache, `verify_webhook`), `workers/payment_monitor.py` (`sync_invoice`), `scripts/`, `docs/DEMO.md`, `README.md`, `pyproject.toml` |

## Gotchas

- Several files use **CRLF** line endings (`nodes.py` is mixed). Keep them as they are or the diff becomes unreadable.
- Run the backend with `PYTHONPATH=src uv run uvicorn paypal_agent.main:app --port 8000` (the package isn't installed;
  the pinned `uv_build` version is newer than some local `uv` releases).
- Port 3000 may be taken by another Next.js server; Next then uses 3001.
- `uvicorn` isn't started with `--reload`: restart it after backend changes.
- Existing sandbox rule from HANDOVER: buyers must be a **US Personal** sandbox account.

## Late fixes (found by running the whole flow live)

- **Token cache used `time.monotonic()`**, which stops while a Mac sleeps, so after wake-up an expired token was served and `/api/invoices` returned 502. Now wall-clock time, plus one retry with a fresh token on a 401 (safe: a 401 means PayPal did not process the call).
- **"$450" asked for the currency.** A `$`/`€`/`£` next to a number now implies USD/EUR/GBP (Python, not the LLM).
- **Stray CONFIRM/CANCEL with nothing pending** restarted the create flow, so a second CONFIRM could have made a duplicate invoice. They now get "Nothing is waiting for your confirmation".
