"use client";

import { useState } from "react";

import CollapseToggle from "@/components/CollapseToggle";
import { AgentEvent } from "@/lib/api";

export default function ActivityFeed({ events }: { events: AgentEvent[] }) {
  const [open, setOpen] = useState(true);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Agent activity</h2>
        <div className="card-head-right">
          <span className="live-dot">Watching</span>
          <CollapseToggle
            open={open}
            onToggle={() => setOpen(!open)}
            label="agent activity"
          />
        </div>
      </div>

      {open && (
        <div className="events">
          {events.length === 0 ? (
            <div className="empty" style={{ padding: "16px 0" }}>
              Nothing new yet. The agent checks your invoices every minute and
              will note payments, refunds and reminders here.
            </div>
          ) : (
            [...events].reverse().map((event, index) => (
              <div className="event" key={event.id ?? index}>
                <div>
                  <div>{event.message}</div>
                  <div className="event-time">
                    <span className="mono">{event.invoice_id}</span> ·{" "}
                    {new Date(event.time).toLocaleTimeString()}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
