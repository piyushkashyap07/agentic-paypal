import Link from "next/link";

import Header from "@/components/Header";

const steps = [
  {
    title: "Tell it the outcome",
    text: "Type “Invoice Acme $2,500 for the website.” The agent picks out the customer, amount and work, and asks before it creates anything.",
  },
  {
    title: "It sends and watches",
    text: "The invoice goes out through PayPal. The agent keeps checking the payment status in the background, so you don't have to.",
  },
  {
    title: "It follows up",
    text: "Paid? You hear about it. Overdue? It sends a polite reminder. Need to refund? It asks you to confirm, then does it.",
  },
];

const features = [
  { title: "Invoices in one sentence", text: "Create and send PayPal invoices from a chat message." },
  { title: "Payment monitoring", text: "Every open invoice is checked automatically, every minute." },
  { title: "Automatic reminders", text: "Overdue invoices get a reminder, at most once a day." },
  { title: "Safe refunds", text: "Money never moves back without an explicit CONFIRM REFUND." },
];

export default function Home() {
  return (
    <>
      <Header />

      <section className="hero">
        <div className="container hero-inner">
          <div>
            <h1>
              Get paid,
              <br />
              without the chasing
            </h1>
            <p>
              Tell the agent what you&apos;re owed. It creates the PayPal invoice, sends it,
              watches for payment and follows up until the money lands.
            </p>
            <div className="hero-cta">
              <Link href="/dashboard" className="pill pill-blue">
                Get started
              </Link>
            </div>
            <div className="hero-note">Runs on the PayPal Sandbox. No real money moves.</div>
          </div>

          <div className="hero-art" aria-hidden="true">
            <div className="coin" style={{ width: 72, height: 72, top: -24, right: 20, fontSize: 28 }}>
              $
            </div>
            <div className="coin" style={{ width: 48, height: 48, bottom: -10, left: 10, fontSize: 20 }}>
              $
            </div>
            <div className="hero-card">
              <div className="hero-card-row">
                <span>Invoice for Acme</span>
                <span className="badge PAID">PAID</span>
              </div>
              <div className="hero-card-amount">$2,500.00</div>
              <div className="hero-bubble user">Get me paid $2,500 by Acme for the website.</div>
              <div className="hero-bubble">Invoice sent ✓ I&apos;ll watch it for you.</div>
              <div className="hero-bubble">🎉 Acme just paid $2,500.00.</div>
            </div>
          </div>
        </div>
      </section>

      <section className="section" id="how-it-works">
        <div className="container">
          <h2 className="section-title">From “I&apos;m owed money” to paid, in three steps</h2>
          <div className="steps">
            {steps.map((step, index) => (
              <div className="step" key={step.title}>
                <div className="step-number">{index + 1}</div>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="features" style={{ paddingTop: 0 }}>
        <div className="container">
          <h2 className="section-title">An agent, not just a chatbot</h2>
          <div className="steps" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
            {features.map((feature) => (
              <div className="step" key={feature.title}>
                <h3>{feature.title}</h3>
                <p>{feature.text}</p>
              </div>
            ))}
          </div>
          <div style={{ textAlign: "center", marginTop: 40 }}>
            <Link href="/dashboard" className="pill pill-black">
              Open the dashboard
            </Link>
          </div>
        </div>
      </section>

      <footer className="footer">
        <div className="container">Built for the PayPal AI Hackathon · Sandbox only</div>
      </footer>
    </>
  );
}
