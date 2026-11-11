from datetime import date

from sqlalchemy import func, select

from paypal_agent.database.models import (
    CustomerRecord,
    EventRecord,
    HiddenInvoiceRecord,
    InvoiceRecord,
)
from paypal_agent.database.session import get_factory, init_db


async def _session():
    await init_db()
    return get_factory()()


# --- deleted (hidden) invoices -----------------------------------------------

async def hide_invoices(invoice_ids: list[str]) -> None:
    async with await _session() as session:
        for invoice_id in invoice_ids:
            await session.merge(HiddenInvoiceRecord(invoice_id=invoice_id))
        await session.commit()


async def hidden_invoice_ids() -> set[str]:
    async with await _session() as session:
        rows = await session.execute(select(HiddenInvoiceRecord.invoice_id))
        return set(rows.scalars())


# --- events -----------------------------------------------------------------

async def add_event(invoice_id: str, message: str) -> dict:
    async with await _session() as session:
        record = EventRecord(invoice_id=invoice_id, message=message)
        session.add(record)
        await session.commit()
        return event_to_dict(record)


async def list_events(after: int = 0, limit: int = 100) -> list[dict]:
    """Events with id > after, oldest first (the newest `limit` of them)."""

    async with await _session() as session:
        rows = (
            await session.scalars(
                select(EventRecord)
                .where(EventRecord.id > after)
                .order_by(EventRecord.id.desc())
                .limit(limit)
            )
        ).all()

    return [event_to_dict(row) for row in reversed(rows)]


def event_to_dict(record: EventRecord) -> dict:
    return {
        "id": record.id,
        "time": record.time.isoformat(timespec="seconds"),
        "invoice_id": record.invoice_id,
        "message": record.message,
    }


# --- invoices (workflow state) ------------------------------------------------

async def upsert_invoice(invoice_id: str, **fields) -> InvoiceRecord:
    """Create the record or update only the fields that are passed."""

    async with await _session() as session:
        record = await session.get(InvoiceRecord, invoice_id)

        if record is None:
            record = InvoiceRecord(invoice_id=invoice_id)
            session.add(record)

        for key, value in fields.items():
            setattr(record, key, value)

        await session.commit()
        return record


async def get_invoice_record(invoice_id: str) -> InvoiceRecord | None:
    async with await _session() as session:
        return await session.get(InvoiceRecord, invoice_id)


async def latest_open_invoice(thread_id: str | None = None) -> InvoiceRecord | None:
    """Most recently created invoice that is still waiting for money."""

    async with await _session() as session:
        query = select(InvoiceRecord).where(
            InvoiceRecord.status.in_(["SENT", "UNPAID", "PARTIALLY_PAID"])
        )

        if thread_id:
            query = query.where(InvoiceRecord.thread_id == thread_id)

        query = query.order_by(InvoiceRecord.created_at.desc()).limit(1)
        return await session.scalar(query)


async def mark_reminded(invoice_id: str, on: date) -> None:
    async with await _session() as session:
        record = await session.get(InvoiceRecord, invoice_id)

        if record is not None:
            record.last_reminder_on = on
            record.reminder_count = (record.reminder_count or 0) + 1
            await session.commit()


# --- customers ------------------------------------------------------------------

def _key(name: str) -> str:
    return " ".join(name.casefold().split())


async def remember_customer(name: str, email: str) -> None:
    async with await _session() as session:
        record = await session.get(CustomerRecord, _key(name))

        if record is None:
            session.add(
                CustomerRecord(name_key=_key(name), name=name.strip(), email=email)
            )
        else:
            record.email = email

        await session.commit()


async def find_customer_email(name: str) -> str | None:
    async with await _session() as session:
        record = await session.get(CustomerRecord, _key(name))
        return record.email if record else None


async def count_events() -> int:
    async with await _session() as session:
        return await session.scalar(select(func.count(EventRecord.id))) or 0


async def simulated_overdue_ids() -> set[str]:
    async with await _session() as session:
        rows = await session.scalars(
            select(InvoiceRecord.invoice_id).where(
                InvoiceRecord.simulate_overdue.is_(True)
            )
        )
        return set(rows.all())
