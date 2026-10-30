"use client";

import { AgentEvent } from "@/lib/api";

export default function ActivityFeed({ events }: { events: AgentEvent[] }) {
  return (
    <div className="card">
      <div className="card-head">
        <h2>Agent activity</h2>
        <span className="live-dot">Watching</span>
      </div>

      <div className="events">
        {events.length === 0 ? (
          <div className="empty" style={{ padding: "16px 0" }}>
            Nothing new yet. The agent checks your invoices every minute and will note payments, refunds and
            reminders here.
          </div>
        ) : (
          [...events].reverse().map((event, index) => (
            <div className="event" key={`${event.time}-${index}`}>
              <div>
                <div>{event.message}</div>
                <div className="event-time">
                  <span className="mono">{event.invoice_id}</span> · {new Date(event.time).toLocaleTimeString()}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
