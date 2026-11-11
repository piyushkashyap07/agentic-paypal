"use client";

import { useCallback, useEffect, useState } from "react";

import ActivityFeed from "@/components/ActivityFeed";
import BusinessPanel from "@/components/BusinessPanel";
import Chat from "@/components/Chat";
import Header from "@/components/Header";
import InvoiceList from "@/components/InvoiceList";
import Stats from "@/components/Stats";
import { AgentEvent, api, Invoice } from "@/lib/api";

export default function Dashboard() {
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentEvent[] | null>(null);

  const loadInvoices = useCallback(async () => {
    try {
      setInvoices(await api.listInvoices());
      setInvoiceError(null);
    } catch (error) {
      setInvoiceError((error as Error).message);
    }
  }, []);

  const loadEvents = useCallback(async () => {
    try {
      setEvents(await api.listEvents());
    } catch {
      // The invoice list already shows when the backend is down.
    }
  }, []);

  useEffect(() => {
    const firstLoad = setTimeout(() => {
      loadInvoices();
      loadEvents();
    }, 0);

    const invoiceTimer = setInterval(loadInvoices, 15000);
    const eventTimer = setInterval(loadEvents, 5000);

    return () => {
      clearTimeout(firstLoad);
      clearInterval(invoiceTimer);
      clearInterval(eventTimer);
    };
  }, [loadInvoices, loadEvents]);

  return (
    <>
      <Header />
      <main className="dash">
        {/* Chat on the left stays put at full height; the right column scrolls on its own. */}
        <div className="container dash-grid">
          <Chat onAgentReply={loadInvoices} events={events} />
          <div className="side-col">
            <div className="dash-title">
              <div>
                <h1>Your payments</h1>
                <p>Live from your PayPal Sandbox account.</p>
              </div>
            </div>
            <Stats invoices={invoices ?? []} />
            <InvoiceList invoices={invoices} error={invoiceError} onChanged={loadInvoices} />
            <BusinessPanel />
            <ActivityFeed events={events ?? []} />
          </div>
        </div>
      </main>
    </>
  );
}
