"""Reset local demo data so a recording starts clean.

Run with the backend STOPPED:

    uv run python scripts/reset_demo.py --yes

Clears the local SQLite tables (events, invoices, customers) and the chat
checkpoints. PayPal sandbox invoices are left alone unless you also pass
--delete-paypal-drafts, which deletes only invoices still in DRAFT.
"""

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from paypal_agent.config import settings  # noqa: E402
from paypal_agent.services.paypal_invoice_service import PayPalInvoiceService  # noqa: E402


def local_db_path() -> Path:
    prefix = "sqlite+aiosqlite:///"
    url = settings.database_url

    if not url.startswith(prefix):
        sys.exit(f"Only SQLite is supported here, got: {url.split(':')[0]}")

    return (ROOT / url[len(prefix):]).resolve()


def reset_local() -> None:
    db = local_db_path()

    if db.exists():
        with sqlite3.connect(db) as connection:
            for table in ("events", "invoices", "customers"):
                try:
                    connection.execute(f"DELETE FROM {table}")
                except sqlite3.OperationalError:
                    pass  # table not created yet
        print(f"Cleared events, invoices, customers in {db.name}")

    checkpoints = ROOT / "paypal_agent_checkpoints.db"

    for path in (checkpoints, Path(f"{checkpoints}-shm"), Path(f"{checkpoints}-wal")):
        if path.exists():
            path.unlink()
            print(f"Removed {path.name}")


async def delete_paypal_drafts() -> None:
    service = PayPalInvoiceService()
    deleted = 0

    for item in await service.list_invoices(page_size=100):
        if item.get("status") == "DRAFT":
            await service._invoice_request("DELETE", f"/{item['id']}")
            deleted += 1

    print(f"Deleted {deleted} draft invoice(s) from the PayPal sandbox")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--yes", action="store_true", help="really do it")
    parser.add_argument("--delete-paypal-drafts", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        sys.exit("Nothing done. Re-run with --yes to reset the local demo data.")

    reset_local()

    if args.delete_paypal_drafts:
        asyncio.run(delete_paypal_drafts())


if __name__ == "__main__":
    main()
