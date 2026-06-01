from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent.models import Classification, Ticket, User
from agent.services import Services

DEFAULT_TICKET = object()


@dataclass
class FakeHelpScout:
    ticket: Ticket | None = None
    error: Exception | None = None
    note_error: Exception | None = None
    reply_error: Exception | None = None
    private_notes: list[tuple[str, str]] = field(default_factory=list)
    replies: list[tuple[str, str, bool]] = field(default_factory=list)

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        if self.error:
            raise self.error
        return self.ticket

    def leave_private_note(self, ticket_id: str, message: str) -> None:
        if self.note_error:
            raise self.note_error
        self.private_notes.append((ticket_id, message))

    def reply_to_ticket(
        self, ticket_id: str, message: str, close: bool = False
    ) -> None:
        if self.reply_error:
            raise self.reply_error
        self.replies.append((ticket_id, message, close))


@dataclass
class FakeSniffspot:
    user: User | None = None
    error: Exception | None = None
    refunds: list[tuple[str, str]] = field(default_factory=list)

    async def get_user(self, user_id: str) -> User | None:
        if self.error:
            raise self.error
        return self.user

    async def issue_refund(self, user: User, ticket_id: str) -> str | None:
        self.refunds.append((user.id, ticket_id))
        return None


@dataclass
class FakeSlack:
    approval_error: Exception | None = None
    summary_error: Exception | None = None
    approvals: list[str] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)

    async def ask_for_approval(self, body: str) -> None:
        if self.approval_error:
            raise self.approval_error
        self.approvals.append(body)

    async def log_execution(self, body: str) -> None:
        if self.summary_error:
            raise self.summary_error
        self.summaries.append(body)


@dataclass
class FakeClassifier:
    result: Classification | None = None
    error: Exception | None = None

    async def classify(self, ticket: Ticket, user: User) -> Classification:
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


def make_ticket(description: str = "User ID: 123") -> Ticket:
    return Ticket(
        id="456",
        subject="Refund request",
        description=description,
        email="customer@example.com",
    )


def make_user(created_at: datetime | None = None) -> User:
    created_at = created_at or datetime.now(UTC)
    return User.model_validate(
        {
            "id": "123",
            "uuid": "user-uuid",
            "firstname": "Jane",
            "lastname": "Customer",
            "activeSniffpass": True,
            "hasCanceledSniffpass": False,
            "memberships": [],
            "subscriptions": [
                {
                    "id": 789,
                    "membership_id": 101,
                    "sniffpass": True,
                    "sniffpass_type": "monthly",
                    "hours": 1,
                    "dogs": 1,
                    "amount": 10.0,
                    "price": 10.0,
                    "net_to_host": None,
                    "sniffspot_fee": 0.0,
                    "total_due": 10.0,
                    "notes": None,
                    "cancel_reason_predefined": None,
                    "stripe_subscription_id": None,
                    "stripe_last_error": None,
                    "status": "active",
                    "trial_status": None,
                    "trial_ends_at": None,
                    "canceled_at": None,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "period": "monthly",
                    "trial_amount": None,
                    "user_id": 123,
                    "user_canceled_at": None,
                    "cancel_reason": None,
                    "renews_at": None,
                    "cancellation_satisfaction": None,
                    "created_platform": None,
                }
            ],
        }
    )


def make_services(
    *,
    ticket: Ticket | None | object = DEFAULT_TICKET,
    user: User | None = None,
    classification: Classification | None = None,
    classifier_error: Exception | None = None,
    sniffspot_error: Exception | None = None,
    helpscout_error: Exception | None = None,
    slack_summary_error: Exception | None = None,
) -> Services:
    return Services(
        helpdesk=FakeHelpScout(
            ticket=make_ticket() if ticket is DEFAULT_TICKET else ticket,
            error=helpscout_error,
        ),
        sniffspot=FakeSniffspot(user=user, error=sniffspot_error),
        slack=FakeSlack(summary_error=slack_summary_error),
        classifier=FakeClassifier(
            result=classification or Classification(intent="refund", confidence=0.95),
            error=classifier_error,
        ),
    )
