# Agentic PayPal: frontend

Next.js app for the PayPal payment agent. It talks to the FastAPI backend in the repo root.

## Run it

1. Start the backend (from the repo root):

   ```bash
   uv run uvicorn paypal_agent.main:app
   ```

2. Start the frontend (from this folder):

   ```bash
   npm install
   npm run dev
   ```

3. Open http://localhost:3000

Requests to `/api/*` are forwarded to the backend (see `next.config.ts`).
Set `BACKEND_URL` if the backend is not on `http://127.0.0.1:8000`.

## Pages

| Page | What it shows |
| --- | --- |
| `/` | Landing page |
| `/dashboard` | Money summary, chat with the agent, invoices with Send/Remind/Refund buttons, agent activity feed |
