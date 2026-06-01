from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.graph import build_graph
from agent.models import Classification, Context
from agent.services import Services
from tests.fakes import make_services, make_ticket, make_user

pytestmark = pytest.mark.anyio


async def invoke_graph(
    services: Services,
    execution_mode: str = "automation",
    graph: Any | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph = graph or build_graph()
    return await graph.ainvoke(
        {"helpscout_conversation_id": "456"},
        context=Context(execution_mode=execution_mode, services=services),
        config=config,
    )


async def test_missing_user_id_skips_with_note_and_slack() -> None:
    services = make_services(ticket=make_ticket(description="No user here"))

    result = await invoke_graph(services)

    assert result["intent"] == "unknown"
    assert result["outcome"] == "skipped"
    assert result["outcome_reason"] == "no_user_data_in_ticket"
    assert services.helpdesk.private_notes
    assert services.slack.summaries


async def test_missing_sniffspot_user_skips() -> None:
    services = make_services(user=None)

    result = await invoke_graph(services)

    assert result["intent"] == "unknown"
    assert result["outcome"] == "skipped"
    assert result["outcome_reason"] == "no_user_data_in_admin"


async def test_other_intent_skips() -> None:
    services = make_services(
        user=make_user(),
        classification=Classification(intent="other", confidence=0.99),
    )

    result = await invoke_graph(services)

    assert result["intent"] == "other"
    assert result["outcome"] == "skipped"
    assert result["outcome_reason"] == "not_a_refund"
    assert services.helpdesk.private_notes
    assert services.slack.summaries


async def test_low_confidence_refund_routes_to_human() -> None:
    services = make_services(
        user=make_user(),
        classification=Classification(intent="refund", confidence=0.42),
    )

    result = await invoke_graph(services)

    assert result["intent"] == "refund"
    assert result["outcome"] == "routed_to_human"
    assert result["outcome_reason"] == "low_confidence"


async def test_refund_outside_policy_routes_to_human() -> None:
    services = make_services(
        user=make_user(datetime.now(UTC) - timedelta(days=8)),
        classification=Classification(intent="refund", confidence=0.95),
    )

    result = await invoke_graph(services)

    assert result["intent"] == "refund"
    assert result["outcome"] == "routed_to_human"
    assert result["outcome_reason"] == "outside_policy"


async def test_automation_happy_path_records_noop_actions() -> None:
    services = make_services(
        user=make_user(),
        classification=Classification(intent="refund", confidence=0.95),
    )

    result = await invoke_graph(services)

    assert result["intent"] == "refund"
    assert result["outcome"] == "handled"
    assert result["outcome_reason"] == "refunded"
    assert [action.type for action in result["actions"]] == [
        "refund",
        "helpscout_reply",
        "helpscout_close",
        "private_note",
        "slack_summary",
    ]
    assert services.sniffspot.refunds == [("123", "456")]
    assert services.helpdesk.replies == [
        ("456", "Your refund has been processed.", True)
    ]


async def test_review_mode_interrupts_and_resumes_with_approval() -> None:
    graph = build_graph(checkpointer=InMemorySaver())
    services = make_services(
        user=make_user(),
        classification=Classification(intent="refund", confidence=0.95),
    )
    config = {"configurable": {"thread_id": "review-test"}}

    interrupted = await invoke_graph(
        services,
        execution_mode="review",
        graph=graph,
        config=config,
    )

    assert "__interrupt__" in interrupted
    assert services.slack.approvals == [
        "Ticket 456 is ready for refund approval."
    ]
    assert services.sniffspot.refunds == []

    result = await graph.ainvoke(
        Command(resume={"approved": True}),
        context=Context(execution_mode="review", services=services),
        config=config,
    )

    assert result["outcome"] == "handled"
    assert result["outcome_reason"] == "refunded"
    assert services.sniffspot.refunds == [("123", "456")]


async def test_classifier_error_propagates() -> None:
    services = make_services(user=make_user(), classifier_error=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await invoke_graph(services)


async def test_helpscout_read_error_propagates() -> None:
    services = make_services(helpscout_error=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await invoke_graph(services)


async def test_sniffspot_error_propagates() -> None:
    services = make_services(
        user=None,
        sniffspot_error=RuntimeError("boom"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        await invoke_graph(services)


async def test_slack_summary_error_propagates() -> None:
    services = make_services(
        user=make_user(),
        classification=Classification(intent="other", confidence=0.99),
        slack_summary_error=RuntimeError("boom"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        await invoke_graph(services)
