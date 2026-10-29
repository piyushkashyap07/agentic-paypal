from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Message submitted by the user."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The user's request to the PayPal AI agent.",
    )

    thread_id: str | None = Field(
        default=None,
        description="Conversation identifier for continuing a workflow.",
    )


class ChatResponse(BaseModel):
    """Response returned by the agent API."""

    message: str
    thread_id: str
    status: str = "success"
    
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field


class CreateInvoiceRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=100)
    customer_email: EmailStr
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    currency: str = Field(default="USD", pattern=r"^[A-Za-z]{3}$")
    description: str = Field(min_length=1, max_length=500)