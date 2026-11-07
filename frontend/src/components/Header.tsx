import Link from "next/link";

export function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
        <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" />
      </svg>
    </span>
  );
}

export default function Header() {
  return (
    <header className="header">
      <div className="container header-inner">
        <Link href="/" className="brand">
          <BrandMark />
          Agentic PayPal
        </Link>

        <nav className="nav" aria-label="Main">
          <Link href="/#how-it-works">How it works</Link>
          <Link href="/#features">Features</Link>
          <Link href="/dashboard">Dashboard</Link>
        </nav>

        <div className="header-actions">
          <Link href="/#how-it-works" className="pill pill-grey">
            Learn more
          </Link>
          <Link href="/dashboard" className="pill pill-black">
            Open dashboard
          </Link>
        </div>
      </div>
    </header>
  );
}
