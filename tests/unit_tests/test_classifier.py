import pytest

import agent.classifier as classifier_module
from agent.classifier import DEFAULT_PROMPT_NAME, RefundClassifier
from agent.models import Classification
from tests.fakes import make_ticket, make_user


class FakeStructuredPrompt:
    def __init__(self) -> None:
        self.values: dict[str, str] | None = None
        self.schema: type[Classification] | None = None

    def with_structured_output(
        self, schema: type[Classification]
    ) -> "FakeStructuredPrompt":
        self.schema = schema
        return self

    async def ainvoke(self, values: dict[str, str]) -> Classification:
        self.values = values
        return Classification(intent="refund", confidence=0.9)


class FakeClient:
    pulled_prompts: list[tuple[str, bool]] = []
    prompt = FakeStructuredPrompt()

    def pull_prompt(
        self, prompt_identifier: str, *, include_model: bool
    ) -> FakeStructuredPrompt:
        self.pulled_prompts.append((prompt_identifier, include_model))
        return self.prompt


def install_classifier_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classifier_module, "Client", FakeClient)


@pytest.mark.anyio
async def test_refund_classifier_uses_langsmith_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    install_classifier_fakes(monkeypatch)
    FakeClient.pulled_prompts.clear()
    FakeClient.prompt = FakeStructuredPrompt()

    ticket = make_ticket("Please refund this charge")
    user = make_user()

    classifier = RefundClassifier()
    result = await classifier.classify(ticket, user)

    assert result == Classification(intent="refund", confidence=0.9)
    assert FakeClient.pulled_prompts == [(DEFAULT_PROMPT_NAME, True)]
    assert FakeClient.prompt.schema is Classification
    assert FakeClient.prompt.values == {
        "ticket_subject": ticket.subject,
        "ticket_body": ticket.description,
        "user_email": ticket.email,
    }
