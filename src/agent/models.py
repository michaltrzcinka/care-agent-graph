from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Ticket(BaseModel):
    id: str
    subject: str
    description: str
    email: str


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class User(CamelModel):
    id: str
    uuid: str
    first_name: str = Field(alias="firstname")
    last_name: str = Field(alias="lastname")
    active_sniffpass: bool
    has_canceled_sniffpass: bool
    memberships: list["Membership"] = Field(default_factory=list)
    subscriptions: list["Subscription"] = Field(default_factory=list)


class Spot(BaseModel):
    id: str
    title: str


class Membership(CamelModel):
    id: str
    status: str
    sniffpass_type: str
    sniffpass_type_full: str
    period: str
    active: bool
    price: float
    dogs: int
    hours: int
    remaining_credits: int
    remaining_hours: int
    renews_at: datetime | None = None
    ends_at: datetime | None = None
    trial_ends_at: datetime | None = None
    trial_status: str | None = None
    canceled_at: datetime | None = None
    user_canceled_at: datetime | None = None
    cancel_reason: str | None = None
    cancel_reason_predefined: str | None = None
    created_at: datetime
    created_from: str | None = None
    spot: Spot | None = None


class Subscription(BaseModel):
    id: int
    membership_id: int
    sniffpass: bool
    sniffpass_type: str
    hours: int | None = None
    dogs: int | None = None
    amount: float
    price: float
    net_to_host: float | None = None
    sniffspot_fee: float
    total_due: float
    notes: str | None = None
    cancel_reason_predefined: str | None = None
    stripe_subscription_id: str | None = None
    stripe_last_error: str | None = None
    status: str
    trial_status: str | None = None
    trial_ends_at: datetime | None = None
    canceled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    period: str
    trial_amount: float | None = None
    user_id: int
    user_canceled_at: datetime | None = None
    cancel_reason: str | None = None
    renews_at: datetime | None = None
    cancellation_satisfaction: str | None = None
    created_platform: str | None = None


class Customer(BaseModel):
    email: str
    name: str
    subscription_id: str
    last_payment_date: datetime


class Entitlement(BaseModel):
    credits_used: int


Intent = Literal["refund", "other", "unknown"]
Outcome = Literal["skipped", "routed_to_human", "handled"]
OutcomeReason = Literal[
    "no_user_data_in_ticket",
    "no_user_data_in_admin",
    "not_a_refund",
    "outside_policy",
    "partial_refund",
    "review_mode",
    "low_confidence",
    "ambiguous_request",
    "refunded",
    "no_action_needed",
]
ActionType = Literal[
    "refund",
    "helpscout_reply",
    "helpscout_close",
    "private_note",
    "slack_summary",
]
ActionStatus = Literal["completed", "failed"]


class Action(BaseModel):
    type: ActionType
    status: ActionStatus
    external_id: str | None = None


class Classification(BaseModel):
    intent: Literal["refund", "other"]
    confidence: float


class Context(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    execution_mode: Literal["review", "automation"] = "automation"
    services: Any | None = None


class Input(BaseModel):
    helpscout_conversation_id: str


class Output(BaseModel):
    intent: Intent = "unknown"
    outcome: Outcome | None = None
    outcome_reason: OutcomeReason | None = None
    summary: str = ""
    actions: list[Action] = Field(default_factory=list)


class State(Input, Output):
    ticket: Ticket | None = None
    user_id: int | None = None
    user: User | None = None
    confidence: float | None = None
    terminal: bool = False
    needs_review: bool = False
    approval_requested: bool = False
