from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from agent.helpdesk import HelpScout
from agent.models import (
    Action,
    Classification,
    Context,
    Input,
    OutcomeReason,
    Output,
    State,
    Subscription,
    Ticket,
    User,
)
from agent.slack import Slack
from agent.sniffspot import Sniffspot

CONFIDENCE_THRESHOLD = 0.80
REFUND_POLICY_WINDOW = timedelta(days=7)


@dataclass
class Services:
    helpdesk: Any
    sniffspot: Any
    slack: Any
    classifier: Any


def _extract_user_id(text: str) -> int | None:
    match = re.search(r"User ID:\s*(\d+)", text)
    return int(match.group(1)) if match else None


def _is_partial_refund_request(ticket: Ticket, user: User) -> bool:
    # TODO: Implement partial refund detection when refund amount semantics are defined.
    return False


def _services(runtime: Runtime[Context]) -> Services:
    context = runtime.context
    if isinstance(context, dict):
        context = Context.model_validate(context)
    elif context is None:
        context = Context()

    if context.services is not None:
        return context.services

    from agent.classifier import RefundClassifier

    return Services(
        helpdesk=HelpScout(),
        sniffspot=Sniffspot(),
        slack=Slack(),
        classifier=RefundClassifier(),
    )


def _execution_mode(runtime: Runtime[Context]) -> str:
    context = runtime.context
    if isinstance(context, dict):
        return context.get("execution_mode", "automation")
    if context is None:
        return "automation"
    return context.execution_mode


def _terminal(
    state: State,
    *,
    intent: str,
    outcome: str,
    outcome_reason: OutcomeReason,
    summary: str,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "outcome": outcome,
        "outcome_reason": outcome_reason,
        "summary": summary,
        "terminal": True,
        "needs_review": False,
    }


def _action(
    action_type: str,
    status: str = "completed",
    external_id: str | None = None,
) -> Action:
    return Action(type=action_type, status=status, external_id=external_id)


def _latest_subscription(user: User) -> Subscription | None:
    if not user.subscriptions:
        return None
    return max(user.subscriptions, key=lambda subscription: subscription.created_at)


def _is_outside_policy(user: User, now: datetime | None = None) -> bool:
    subscription = _latest_subscription(user)
    if subscription is None:
        return True

    created_at = subscription.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    return (now or datetime.now(UTC)) - created_at > REFUND_POLICY_WINDOW


def _ticket_text(ticket: Ticket) -> str:
    return f"{ticket.subject}\n{ticket.description}"


async def fetch_ticket(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    try:
        ticket = _services(runtime).helpdesk.get_ticket(state.helpscout_conversation_id)
    except Exception:
        return _terminal(
            state,
            intent="unknown",
            outcome="failed",
            outcome_reason="helpscout_api_error",
            summary="Failed to fetch HelpScout ticket.",
        )

    return {"ticket": ticket}


def extract_user_id(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    if state.ticket is None:
        return {}

    user_id = _extract_user_id(_ticket_text(state.ticket))
    if user_id is None:
        return _terminal(
            state,
            intent="unknown",
            outcome="skipped",
            outcome_reason="no_user_data_in_ticket",
            summary=f"Skipped ticket {state.ticket.id}: no Sniffspot User ID found.",
        )

    return {"user_id": user_id}


async def fetch_user(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    if state.user_id is None:
        return {}

    try:
        user = await _services(runtime).sniffspot.get_user(str(state.user_id))
    except Exception:
        return _terminal(
            state,
            intent="unknown",
            outcome="failed",
            outcome_reason="admin_api_error",
            summary=f"Failed to fetch Sniffspot user {state.user_id}.",
        )

    if user is None:
        return _terminal(
            state,
            intent="unknown",
            outcome="skipped",
            outcome_reason="no_user_data_in_admin",
            summary=f"Skipped ticket {state.helpscout_conversation_id}: user {state.user_id} not found in Sniffspot admin.",
        )

    return {"user": user}


async def classify(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    if state.ticket is None or state.user is None:
        return {}

    try:
        classification = await _services(runtime).classifier.classify(
            state.ticket, state.user
        )
    except Exception:
        return _terminal(
            state,
            intent="unknown",
            outcome="failed",
            outcome_reason="llm_error",
            summary=f"Failed to classify ticket {state.ticket.id}.",
        )

    if not isinstance(classification, Classification):
        classification = Classification.model_validate(classification)

    return {
        "intent": classification.intent,
        "confidence": classification.confidence,
    }


def decide(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    if state.ticket is None or state.user is None:
        return {}

    if state.intent == "other":
        return _terminal(
            state,
            intent="other",
            outcome="skipped",
            outcome_reason="not_a_refund",
            summary=f"Skipped ticket {state.ticket.id}: classified as other.",
        )

    if state.confidence is None or state.confidence < CONFIDENCE_THRESHOLD:
        return _terminal(
            state,
            intent="refund",
            outcome="routed_to_human",
            outcome_reason="low_confidence",
            summary=f"Routed ticket {state.ticket.id}: refund confidence was below {CONFIDENCE_THRESHOLD:.2f}.",
        )

    if _is_outside_policy(state.user):
        return _terminal(
            state,
            intent="refund",
            outcome="routed_to_human",
            outcome_reason="outside_policy",
            summary=f"Routed ticket {state.ticket.id}: latest payment is outside the 7-day refund window.",
        )

    if _is_partial_refund_request(state.ticket, state.user):
        return _terminal(
            state,
            intent="refund",
            outcome="routed_to_human",
            outcome_reason="partial_refund",
            summary=f"Routed ticket {state.ticket.id}: partial refund request.",
        )

    if _execution_mode(runtime) == "review":
        return {
            "needs_review": True,
            "summary": f"Ticket {state.ticket.id} is ready for refund approval.",
        }

    return {"needs_review": False}


async def notify_for_review(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    if state.ticket is None or state.user is None:
        return {}

    try:
        await _services(runtime).slack.ask_for_approval(state.summary)
    except Exception:
        return _terminal(
            state,
            intent="refund",
            outcome="failed",
            outcome_reason="unknown_error",
            summary=f"Failed to send approval request for ticket {state.ticket.id}.",
        )

    return {"approval_requested": True}


def wait_for_approval(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    approval = interrupt(
        {
            "ticket_id": state.ticket.id if state.ticket else None,
            "user_id": state.user.id if state.user else None,
            "summary": state.summary,
        }
    )

    approved = (
        approval.get("approved") if isinstance(approval, dict) else bool(approval)
    )
    if not approved:
        return _terminal(
            state,
            intent="refund",
            outcome="routed_to_human",
            outcome_reason="review_mode",
            summary=f"Routed ticket {state.ticket.id if state.ticket else state.helpscout_conversation_id}: approval was not granted.",
        )

    return {"needs_review": False}


async def execute_refund(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    if state.ticket is None or state.user is None:
        return {}

    services = _services(runtime)
    actions = state.actions

    try:
        refund_id = await services.sniffspot.issue_refund(state.user, state.ticket.id)
    except Exception:
        return _terminal(
            state,
            intent="refund",
            outcome="failed",
            outcome_reason="admin_api_error",
            summary=f"Failed to issue refund for ticket {state.ticket.id}.",
        )
    actions = [*actions, _action("refund", external_id=refund_id)]

    try:
        services.helpdesk.reply_to_ticket(
            state.ticket.id,
            "Your refund has been processed.",
            close=True,
        )
    except Exception:
        return {
            **_terminal(
                state,
                intent="refund",
                outcome="failed",
                outcome_reason="helpscout_api_error",
                summary=f"Failed to record HelpScout reply/close for ticket {state.ticket.id}.",
            ),
            "actions": actions,
        }

    actions = [
        *actions,
        _action("helpscout_reply"),
        _action("helpscout_close"),
    ]

    return {
        "intent": "refund",
        "outcome": "handled",
        "outcome_reason": "refunded",
        "summary": f"Handled ticket {state.ticket.id}: refund approved and recorded.",
        "actions": actions,
        "terminal": True,
    }


async def finalize(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    services = _services(runtime)
    actions = state.actions

    if state.ticket is not None and state.outcome_reason != "helpscout_api_error":
        try:
            services.helpdesk.leave_private_note(state.ticket.id, state.summary)
        except Exception:
            return {
                "outcome": "failed",
                "outcome_reason": "helpscout_api_error",
                "summary": f"Failed to leave private note for ticket {state.ticket.id}.",
                "actions": [
                    *actions,
                    _action("private_note", "failed"),
                ],
                "terminal": True,
            }
        actions = [*actions, _action("private_note")]

    try:
        await services.slack.log_execution(state.summary)
    except Exception:
        return {
            "outcome": "failed",
            "outcome_reason": "unknown_error",
            "summary": "Failed to send Slack execution summary.",
            "actions": [*actions, _action("slack_summary", "failed")],
            "terminal": True,
        }

    return {"actions": [*actions, _action("slack_summary")]}


def route_after_fetch_ticket(state: State) -> str:
    return "finalize" if state.terminal else "extract_user_id"


def route_after_extract_user_id(state: State) -> str:
    return "finalize" if state.terminal else "fetch_user"


def route_after_fetch_user(state: State) -> str:
    return "finalize" if state.terminal else "classify"


def route_after_classify(state: State) -> str:
    return "finalize" if state.terminal else "decide"


def route_after_decide(state: State) -> str:
    if state.terminal:
        return "finalize"
    if state.needs_review:
        return "notify_for_review"
    return "execute_refund"


def route_after_notify_for_review(state: State) -> str:
    return "finalize" if state.terminal else "wait_for_approval"


def route_after_wait_for_approval(state: State) -> str:
    return "finalize" if state.terminal else "execute_refund"


def build_graph(checkpointer: Any | None = None):
    builder = StateGraph(
        input_schema=Input,
        output_schema=Output,
        state_schema=State,
        context_schema=Context,
    )
    builder.add_node("fetch_ticket", fetch_ticket)
    builder.add_node("extract_user_id", extract_user_id)
    builder.add_node("fetch_user", fetch_user)
    builder.add_node("classify", classify)
    builder.add_node("decide", decide)
    builder.add_node("notify_for_review", notify_for_review)
    builder.add_node("wait_for_approval", wait_for_approval)
    builder.add_node("execute_refund", execute_refund)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "fetch_ticket")
    builder.add_conditional_edges(
        "fetch_ticket",
        route_after_fetch_ticket,
        {"extract_user_id": "extract_user_id", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "extract_user_id",
        route_after_extract_user_id,
        {"fetch_user": "fetch_user", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "fetch_user",
        route_after_fetch_user,
        {"classify": "classify", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "classify",
        route_after_classify,
        {"decide": "decide", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "decide",
        route_after_decide,
        {
            "execute_refund": "execute_refund",
            "finalize": "finalize",
            "notify_for_review": "notify_for_review",
        },
    )
    builder.add_conditional_edges(
        "notify_for_review",
        route_after_notify_for_review,
        {"wait_for_approval": "wait_for_approval", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "wait_for_approval",
        route_after_wait_for_approval,
        {"execute_refund": "execute_refund", "finalize": "finalize"},
    )
    builder.add_edge("execute_refund", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer, name="Care Agent Graph")


graph = build_graph()
