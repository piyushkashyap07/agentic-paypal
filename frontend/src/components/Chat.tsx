"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";

import { AgentEvent, api } from "@/lib/api";

type Message = {
  role: "user" | "agent" | "error";
  text: string;
};

const SUGGESTIONS = [
  "Invoice Acme $2,500 USD for website work",
  "Has it been paid?",
  "Why haven't I been paid?",
  "Send a reminder",
  "Refund the payment",
];

const WELCOME: Message = {
  role: "agent",
  text:
    "Hi! Tell me who owes you money and I'll take care of the PayPal side.\n" +
    "Include the customer's name, email, amount, currency and what the work was (and when it's due, e.g. \"net 30\").\n" +
    "I'll post here when something changes.",
};

// Show payment links as clickable links.
function linkify(text: string): ReactNode[] {
  return text.split(/(https:\/\/\S+)/g).map((part, index) =>
    part.startsWith("https://") ? (
      <a key={index} href={part} target="_blank" rel="noopener noreferrer">
        {part}
      </a>
    ) : (
      part
    ),
  );
}

export default function Chat({
  onAgentReply,
  events,
}: {
  onAgentReply: () => void;
  events: AgentEvent[] | null;
}) {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Id of the newest monitor event already handled. null until the first load.
  const lastEventId = useRef<number | null>(null);

  useEffect(() => {
    try {
      setThreadId(sessionStorage.getItem("thread_id"));
    } catch {
      // Storage can be blocked; the chat still works without it.
    }
  }, []);

  // Monitor events ("Acme paid!") show up in the chat as agent messages.
  // History from before this page opened is skipped, so the chat starts clean.
  useEffect(() => {
    if (events === null) return;

    if (lastEventId.current === null) {
      lastEventId.current = events.at(-1)?.id ?? 0;
      return;
    }

    const fresh = events.filter((event) => event.id > (lastEventId.current ?? 0));
    if (fresh.length === 0) return;

    lastEventId.current = fresh[fresh.length - 1].id;
    setMessages((current) => [
      ...current,
      ...fresh.map((event) => ({ role: "agent" as const, text: `Update: ${event.message}` })),
    ]);
    onAgentReply();
  }, [events, onAgentReply]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;

    setMessages((current) => [...current, { role: "user", text: message }]);
    setInput("");
    setBusy(true);

    try {
      const reply = await api.chat(message, threadId);
      setThreadId(reply.thread_id);
      try {
        sessionStorage.setItem("thread_id", reply.thread_id);
      } catch {}
      setMessages((current) => [...current, { role: "agent", text: reply.message }]);
      onAgentReply();
    } catch (error) {
      setMessages((current) => [
        ...current,
        { role: "error", text: `Something went wrong: ${(error as Error).message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    send(input);
  }

  function newConversation() {
    setThreadId(null);
    setMessages([WELCOME]);
    try {
      sessionStorage.removeItem("thread_id");
    } catch {}
  }

  return (
    <div className="card chat">
      <div className="card-head">
        <div>
          <h2>Payment agent</h2>
          <div className="card-sub">Shortcuts: CONFIRM · SEND · STATUS · REMIND · REFUND · WHY</div>
        </div>
        <button className="pill pill-outline pill-small" onClick={newConversation}>
          New chat
        </button>
      </div>

      <div className="messages" aria-live="polite">
        {messages.map((message, index) => (
          <div key={index} className={`msg ${message.role === "user" ? "user" : "agent"} ${message.role === "error" ? "error" : ""}`}>
            {linkify(message.text)}
          </div>
        ))}
        {busy && (
          <div className="msg agent" aria-label="Agent is typing">
            <div className="typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="suggestions">
        {SUGGESTIONS.map((suggestion) => (
          <button key={suggestion} className="chip" onClick={() => setInput(suggestion)} disabled={busy}>
            {suggestion}
          </button>
        ))}
      </div>

      <form className="composer" onSubmit={onSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="e.g. Invoice Acme $2,500 USD for website work, billing@acme.com"
          aria-label="Message the payment agent"
        />
        <button className="pill pill-blue" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
