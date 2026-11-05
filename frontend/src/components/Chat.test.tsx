import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Chat from "./Chat";
import { api, type AgentEvent } from "@/lib/api";

const event = (id: number, message: string): AgentEvent => ({
  id,
  time: "2026-11-06T00:00:00",
  invoice_id: "INV2-1",
  message,
});

afterEach(() => vi.restoreAllMocks());

describe("Chat monitor updates", () => {
  it("skips history, then shows only new events as Update messages", () => {
    const onAgentReply = vi.fn();
    const history = [event(1, "old news")];
    const { rerender } = render(<Chat events={null} onAgentReply={onAgentReply} />);

    rerender(<Chat events={history} onAgentReply={onAgentReply} />);
    expect(screen.queryByText(/old news/)).not.toBeInTheDocument();
    expect(onAgentReply).not.toHaveBeenCalled();

    rerender(<Chat events={[...history, event(2, "Acme paid!")]} onAgentReply={onAgentReply} />);
    expect(screen.getByText("Update: Acme paid!")).toBeInTheDocument();
    expect(onAgentReply).toHaveBeenCalledTimes(1);

    // The same events arriving again (next poll) must not duplicate the message.
    rerender(<Chat events={[...history, event(2, "Acme paid!")]} onAgentReply={onAgentReply} />);
    expect(screen.getAllByText("Update: Acme paid!")).toHaveLength(1);
  });
});

describe("Chat conversation", () => {
  it("sends a message and shows the reply, keeping the thread id", async () => {
    const chat = vi
      .spyOn(api, "chat")
      .mockResolvedValue({ message: "Reply CONFIRM to continue", thread_id: "t-9", status: "ok" });

    render(<Chat events={[]} onAgentReply={() => {}} />);
    fireEvent.change(screen.getByLabelText("Message the payment agent"), {
      target: { value: "Invoice Acme $100" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Reply CONFIRM to continue")).toBeInTheDocument();
    expect(chat).toHaveBeenCalledWith("Invoice Acme $100", null);
  });

  it("shows an error message when the backend fails", async () => {
    vi.spyOn(api, "chat").mockRejectedValue(new Error("PayPal could not list the invoices."));

    render(<Chat events={[]} onAgentReply={() => {}} />);
    fireEvent.change(screen.getByLabelText("Message the payment agent"), { target: { value: "hi" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(screen.getByText(/Something went wrong: PayPal could not list/)).toBeInTheDocument(),
    );
  });

  it("turns payment links into real links", async () => {
    vi.spyOn(api, "chat").mockResolvedValue({
      message: "Pay here: https://www.sandbox.paypal.com/invoice/p/#ABC",
      thread_id: "t",
      status: "ok",
    });

    render(<Chat events={[]} onAgentReply={() => {}} />);
    fireEvent.change(screen.getByLabelText("Message the payment agent"), { target: { value: "send" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    const link = await screen.findByRole("link");
    expect(link).toHaveAttribute("href", "https://www.sandbox.paypal.com/invoice/p/#ABC");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
