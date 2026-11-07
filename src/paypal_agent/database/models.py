from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class EventRecord(Base):
    """Something the monitor noticed or did. Shown in the UI and the chat."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    invoice_id: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)


class InvoiceRecord(Base):
    """Our own record of an invoice's lifecycle (PayPal stays the source of truth)."""

    __tablename__ = "invoices"

    invoice_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_reminder_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    # Demo only: makes the monitor treat the invoice as overdue (see CHECKPOINT.md #3).
    simulate_overdue: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CustomerRecord(Base):
    """Name -> email memory so "invoice Acme" works without retyping the email."""

    __tablename__ = "customers"

    name_key: Mapped[str] = mapped_column(String(100), primary_key=True)  # casefolded
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
