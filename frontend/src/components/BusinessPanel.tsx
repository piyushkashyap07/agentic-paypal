"use client";

import { useEffect, useState } from "react";

import { api, Dispute, Earnings } from "@/lib/api";
import { formatMoney } from "@/lib/money";

// Earnings for the last 30 days and open disputes, both from PayPal.
export default function BusinessPanel() {
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  const [disputes, setDisputes] = useState<Dispute[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [earned, open] = await Promise.all([api.earnings(30), api.listDisputes()]);
        setEarnings(earned);
        setDisputes(open);
        setError(null);
      } catch (loadError) {
        setError((loadError as Error).message);
      }
    }

    const firstLoad = setTimeout(load, 0);
    const timer = setInterval(load, 60000);

    return () => {
      clearTimeout(firstLoad);
      clearInterval(timer);
    };
  }, []);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Last 30 days</h2>
        <span className="card-sub">{earnings ? `${earnings.payments} payment(s)` : ""}</span>
      </div>

      {error && <div className="empty">{error}</div>}
      {!error && earnings === null && <div className="empty">Loading from PayPal…</div>}

      {earnings && (
        <div className="business-row">
          <div>
            <div className="stat-label">Received</div>
            <div className="business-value">{formatMoney(earnings.received, earnings.currency)}</div>
          </div>
          <div>
            <div className="stat-label">Refunded</div>
            <div className="business-value">{formatMoney(earnings.refunded, earnings.currency)}</div>
          </div>
          <div>
            <div className="stat-label">Kept</div>
            <div className="business-value">{formatMoney(earnings.net, earnings.currency)}</div>
          </div>
        </div>
      )}

      {disputes && (
        <div className="business-disputes">
          <div className="stat-label">Disputes</div>
          {disputes.length === 0 ? (
            <div className="business-ok">No disputes ✓</div>
          ) : (
            disputes.map((dispute) => (
              <div className="business-dispute" key={dispute.dispute_id}>
                <span className="mono">{dispute.dispute_id}</span>
                <span>{formatMoney(dispute.amount, dispute.currency)}</span>
                <span className={`badge ${dispute.needs_action ? "SENT" : "REFUNDED"}`}>
                  {dispute.needs_action ? "Needs reply" : dispute.status}
                </span>
              </div>
            ))
          )}
          {disputes.length > 0 && (
            <div className="event-time">Ask the agent: &ldquo;explain dispute {disputes[0].dispute_id}&rdquo;</div>
          )}
        </div>
      )}
    </div>
  );
}
