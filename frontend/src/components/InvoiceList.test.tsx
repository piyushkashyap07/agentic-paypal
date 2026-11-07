import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import InvoiceList from "./InvoiceList";
import { api, type Invoice } from "@/lib/api";

const invoice = (over: Partial<Invoice>): Invoice => ({
  invoice_id: "INV2-1",
  status: "SENT",
  customer_email: "a@b.test",
  amount: "300.00",
  currency: "USD",
  amount_due: "300.00",
  due_date: "2026-11-30",
  pay_link: "https://www.sandbox.paypal.com/invoice/p/#X",
  next_action: "wait",
  ...over,
});

afterEach(() => vi.restoreAllMocks());

describe("InvoiceList", () => {
  it("shows an empty state", () => {
    render(<InvoiceList invoices={[]} error={null} onChanged={() => {}} />);
    expect(screen.getByText(/No invoices yet/)).toBeInTheDocument();
  });

  it("shows the error instead of the empty state", () => {
    render(<InvoiceList invoices={null} error="PayPal could not list the invoices." onChanged={() => {}} />);
    expect(screen.getByText(/PayPal could not list/)).toBeInTheDocument();
  });

  it("badges a simulated-overdue invoice as Overdue", () => {
    render(<InvoiceList invoices={[invoice({ simulated_overdue: true })]} error={null} onChanged={() => {}} />);
    expect(screen.getByText("Overdue")).toBeInTheDocument();
  });

  it("offers Send only for drafts and Refund only for paid invoices", () => {
    render(
      <InvoiceList
        invoices={[
          invoice({ invoice_id: "D", status: "DRAFT" }),
          invoice({ invoice_id: "P", status: "PAID" }),
        ]}
        error={null}
        onChanged={() => {}}
      />,
    );
    expect(screen.getAllByRole("button", { name: "Send" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Refund" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Remind" })).not.toBeInTheDocument();
  });

  it("runs the action and refreshes", async () => {
    const action = vi.spyOn(api, "invoiceAction").mockResolvedValue({});
    const onChanged = vi.fn();
    render(<InvoiceList invoices={[invoice({ status: "DRAFT" })]} error={null} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(action).toHaveBeenCalledWith("INV2-1", "send");
  });
});
