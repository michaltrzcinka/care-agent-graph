import pytest

from agent import graph
from agent.models import Classification, Context, Ticket
from tests.fakes import make_services, make_user

pytestmark = pytest.mark.anyio


async def test_agent_simple_passthrough() -> None:
    inputs = {"helpscout_conversation_id": "3338393447"}
    services = make_services(
        ticket=Ticket(
            id="3338393447",
            subject="Refund request",
            description="User ID: 123",
            email="customer@example.com",
        ),
        user=make_user(),
        classification=Classification(intent="refund", confidence=0.95),
    )

    res = await graph.ainvoke(
        inputs,
        context=Context(execution_mode="automation", services=services),
    )

    assert res["outcome"] == "handled"
