from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from agent.models import (
    Action,
    Context,
    Input,
    OutcomeReason,
    Output,
    State,
    Subscription,
    User,
)
from agent.services import build_services


def _terminal(
    intent: str,
    outcome: str,
    outcome_reason: OutcomeReason,
    summary: str,
) -> Command:
    return Command(
        update={
            "intent": intent,
            "outcome": outcome,
            "outcome_reason": outcome_reason,
            "summary": summary,
            "terminal": True,
            "needs_review": False,
        },
        goto="finalize",
    )


async def fetch_ticket(state: State, runtime: Runtime[Context]) -> Command:
    ticket = build_services(runtime).helpdesk.get_ticket(
        state.helpscout_conversation_id
    )

    return Command(update={"ticket": ticket}, goto="extract_user_id")


def extract_user_id(state: State) -> Command:
    if state.ticket is None:
        return Command(update={}, goto="finalize")

    match = re.search(r"User ID:\s*(\d+)", (state.ticket.description))
    user_id = int(match.group(1)) if match else None
    if user_id is None:
        return _terminal(
            intent="unknown",
            outcome="skipped",
            outcome_reason="no_user_data_in_ticket",
            summary=f"Skipped ticket {state.ticket.id}: no Sniffspot User ID found.",
        )

    return Command(update={"user_id": user_id}, goto="fetch_user")


async def fetch_user(state: State, runtime: Runtime[Context]) -> Command:
    if state.user_id is None:
        return Command(update={}, goto="finalize")

    user = await build_services(runtime).sniffspot.get_user(str(state.user_id))
    if user is None:
        return _terminal(
            intent="unknown",
            outcome="skipped",
            outcome_reason="no_user_data_in_admin",
            summary=f"Skipped ticket {state.helpscout_conversation_id}: user {state.user_id} not found in Sniffspot admin.",
        )

    return Command(update={"user": user}, goto="classify")


async def classify(state: State, runtime: Runtime[Context]) -> Command:
    classification = await build_services(runtime).classifier.classify(
        state.ticket, state.user
    )
    return Command(
        update={
            "intent": classification.intent,
            "confidence": classification.confidence,
        },
        goto="decide",
    )


def _is_partial_refund_request() -> bool:
    # TODO: Implement partial refund detection when refund amount semantics are defined.
    return False


def _latest_subscription(user: User) -> Subscription | None:
    if not user.subscriptions:
        return None
    return max(user.subscriptions, key=lambda subscription: subscription.created_at)


REFUND_POLICY_WINDOW = timedelta(days=7)


def _is_outside_policy(user: User, now: datetime | None = None) -> bool:
    subscription = _latest_subscription(user)
    if subscription is None:
        return True

    created_at = subscription.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    return (now or datetime.now(UTC)) - created_at > REFUND_POLICY_WINDOW


CONFIDENCE_THRESHOLD = 0.80


def decide(state: State, runtime: Runtime[Context]) -> Command:
    if state.ticket is None or state.user is None:
        return Command(update={}, goto="finalize")

    if state.intent == "other":
        return _terminal(
            intent="other",
            outcome="skipped",
            outcome_reason="not_a_refund",
            summary=f"Skipped ticket {state.ticket.id}: classified as other.",
        )

    if state.confidence is None or state.confidence < CONFIDENCE_THRESHOLD:
        return _terminal(
            intent="refund",
            outcome="routed_to_human",
            outcome_reason="low_confidence",
            summary=f"Routed ticket {state.ticket.id}: refund confidence was below {CONFIDENCE_THRESHOLD:.2f}.",
        )

    if _is_outside_policy(state.user):
        return _terminal(
            intent="refund",
            outcome="routed_to_human",
            outcome_reason="outside_policy",
            summary=f"Routed ticket {state.ticket.id}: latest payment is outside the 7-day refund window.",
        )

    if _is_partial_refund_request():
        return _terminal(
            intent="refund",
            outcome="routed_to_human",
            outcome_reason="partial_refund",
            summary=f"Routed ticket {state.ticket.id}: partial refund request.",
        )

    if runtime.context.execution_mode == "review":
        return Command(
            update={
                "needs_review": True,
                "summary": f"Ticket {state.ticket.id} is ready for refund approval.",
            },
            goto="notify_for_review",
        )

    return Command(update={"needs_review": False}, goto="execute_refund")


async def notify_for_review(state: State, runtime: Runtime[Context]) -> Command:
    if state.ticket is None or state.user is None:
        return Command(update={}, goto="finalize")

    await build_services(runtime).slack.ask_for_approval(state.summary)
    return Command(update={"approval_requested": True}, goto="wait_for_approval")


def wait_for_approval(state: State) -> Command:
    approval = interrupt(
        {
            "ticket_id": state.ticket.id if state.ticket else None,
            "user_id": state.user.id if state.user else None,
            "summary": state.summary,
        }
    )

    approved = approval.get("approved", False)
    if not approved:
        return _terminal(
            intent="refund",
            outcome="routed_to_human",
            outcome_reason="review_mode",
            summary=f"Routed ticket {state.ticket.id if state.ticket else state.helpscout_conversation_id}: approval was not granted.",
        )

    return Command(update={"needs_review": False}, goto="execute_refund")


async def execute_refund(state: State, runtime: Runtime[Context]) -> Command:
    if state.ticket is None or state.user is None:
        return Command(update={}, goto="finalize")

    services = build_services(runtime)
    actions = state.actions

    refund_id = await services.sniffspot.issue_refund(state.user, state.ticket.id)
    actions = actions + [
        Action(type="refund", status="completed", external_id=refund_id)
    ]

    services.helpdesk.reply_to_ticket(
        state.ticket.id,
        "Your refund has been processed.",
        close=True,
    )
    actions = actions + [
        Action(type="helpscout_reply", status="completed"),
        Action(type="helpscout_close", status="completed"),
    ]

    return Command(
        update={
            "intent": "refund",
            "outcome": "handled",
            "outcome_reason": "refunded",
            "summary": f"Handled ticket {state.ticket.id}: refund approved and recorded.",
            "actions": actions,
            "terminal": True,
        },
        goto="finalize",
    )


async def finalize(state: State, runtime: Runtime[Context]) -> Command:
    services = build_services(runtime)
    actions = state.actions

    if state.ticket is not None:
        services.helpdesk.leave_private_note(state.ticket.id, state.summary)
        actions = actions + [Action(type="private_note", status="completed")]

    await services.slack.log_execution(state.summary)
    return Command(
        update={
            "actions": actions + [Action(type="slack_summary", status="completed")]
        },
        goto=END,
    )


def build_graph(checkpointer: Any | None = None):
    builder = StateGraph(
        input_schema=Input,
        output_schema=Output,
        state_schema=State,
        context_schema=Context,
    )
    builder.add_node(
        "fetch_ticket",
        fetch_ticket,
        destinations=("extract_user_id", "finalize"),
    )
    builder.add_node(
        "extract_user_id",
        extract_user_id,
        destinations=("fetch_user", "finalize"),
    )
    builder.add_node("fetch_user", fetch_user, destinations=("classify", "finalize"))
    builder.add_node("classify", classify, destinations=("decide", "finalize"))
    builder.add_node(
        "decide",
        decide,
        destinations=("execute_refund", "finalize", "notify_for_review"),
    )
    builder.add_node(
        "notify_for_review",
        notify_for_review,
        destinations=("wait_for_approval", "finalize"),
    )
    builder.add_node(
        "wait_for_approval",
        wait_for_approval,
        destinations=("execute_refund", "finalize"),
    )
    builder.add_node("execute_refund", execute_refund, destinations=("finalize",))
    builder.add_node("finalize", finalize, destinations=(END,))

    builder.add_edge(START, "fetch_ticket")

    return builder.compile(checkpointer=checkpointer, name="Care Agent Graph")


graph = build_graph()
