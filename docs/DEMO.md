# Demo script (2–3 minutes)

**One story:** a freelancer finishes a website and says "get me paid". The agent plans it,
creates and sends a real PayPal sandbox invoice, watches it, chases it when it goes overdue,
and explains why it hasn't been paid.

## Before you record (5 minutes)

1. Stop the backend, then reset local data: `uv run python scripts/reset_demo.py --yes`
   (add `--delete-paypal-drafts` to also remove draft invoices from the sandbox).
2. Start both services (see README). Open http://localhost:3000/dashboard (or 3001 if 3000 is taken).
3. Have a **US Personal sandbox buyer** email ready (PayPal blocks India buyers).
4. Check `APP_ENV=development` in `.env` (the Simulate overdue button only exists in dev).
5. Do one dry run end to end. Sandbox emails can be slow; if SEND fails, check the buyer account.

## Script

| Time | You say / do | What the audience sees |
|---|---|---|
| 0:00 | "I'm a freelancer. I just finished a website for Acme." | Dashboard: stats, empty invoice list |
| 0:15 | Type: *Get me paid $2,500 USD from Acme for a website, `<buyer email>`, net 30* | Agent replies with the details, due date **and its plan** (create → send → watch) |
| 0:35 | Type `CONFIRM` | Draft invoice created, plan step 1 ticked. Invoice appears in the list. |
| 0:50 | Type `SEND` | "Emailed to the customer" + payment link, step 2 ticked, step 3 "watching" |
| 1:10 | "The agent keeps watching. We can't wait 30 days, so I'll fast-forward." Click **Simulate overdue** | Overdue badge; the agent sends a **real** PayPal reminder; an "Update: …Reminder sent" message appears **in the chat** and in the activity feed |
| 1:40 | Type: *Why haven't I been paid?* | Plain-language explanation from PayPal data (not opened / overdue / reminder sent) and a next step |
| 2:10 | Open the payment link and pay as the sandbox buyer | Within ~60s the chat says "Acme paid invoice … (2500 USD)"; stats move to Collected |
| 2:40 | "Same flow also handles refunds, with a second confirmation." (optional: type `REFUND`) | Asks for `CONFIRM REFUND` |

Say out loud what's real: PayPal sandbox calls are real; only the clock is simulated.

## If something goes wrong

| Symptom | Fix |
|---|---|
| "I couldn't confirm that the invoice was sent" | Buyer must be a US Personal sandbox account; check the server log (it prints PayPal's error name/issue, never the raw body). |
| Chat says nothing after paying | The monitor polls every 60s. Run `POST /api/monitor/run`, or set up the webhook (README). |
| Simulate overdue button missing | Production build or `APP_ENV` isn't `development`. |
| LLM slow or down | Retry; status/send/remind/refund shortcuts (`STATUS`, `SEND`, …) skip the LLM. |

## Backup video

Record the table above once as a fallback (screen recording, 2–3 min). **Not recorded yet:** needs a human with
the sandbox buyer account.
