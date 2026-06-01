import pytest

import agent.classifier as classifier_module
from agent.classifier import DEFAULT_PROMPT_NAME, RefundClassifier
from agent.models import Classification
from tests.fakes import make_ticket, make_user

TEST_MODEL = "claude-3-5-haiku-20241022"


class FakePrompt:
    def __init__(self) -> None:
        self.values: dict[str, str] | None = None

    async def ainvoke(self, values: dict[str, str]) -> list[tuple[str, str]]:
        self.values = values
        return [("human", "rendered prompt")]


class FakeStructuredModel:
    def __init__(self) -> None:
        self.prompt: object | None = None

    async def ainvoke(self, prompt: object) -> Classification:
        self.prompt = prompt
        return Classification(intent="refund", confidence=0.9)


class FakeChatAnthropic:
    instances: list["FakeChatAnthropic"] = []

    def __init__(self, *, model_name: str, temperature: int) -> None:
        self.model_name = model_name
        self.temperature = temperature
        self.structured_model = FakeStructuredModel()
        FakeChatAnthropic.instances.append(self)

    def with_structured_output(self, schema: type[Classification]) -> FakeStructuredModel:
        self.schema = schema
        return self.structured_model


class FakeClient:
    pulled_prompt_names: list[str] = []
    prompt = FakePrompt()

    def pull_prompt(self, prompt_identifier: str) -> FakePrompt:
        self.pulled_prompt_names.append(prompt_identifier)
        return self.prompt


def install_classifier_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classifier_module, "ChatAnthropic", FakeChatAnthropic)
    monkeypatch.setattr(classifier_module, "Client", FakeClient)


@pytest.mark.anyio
async def test_refund_classifier_uses_langsmith_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL", TEST_MODEL)
    install_classifier_fakes(monkeypatch)
    FakeChatAnthropic.instances.clear()
    FakeClient.pulled_prompt_names.clear()
    FakeClient.prompt = FakePrompt()

    ticket = make_ticket("Please refund this charge")
    user = make_user()

    classifier = RefundClassifier()
    result = await classifier.classify(ticket, user)

    assert result == Classification(intent="refund", confidence=0.9)
    assert FakeClient.pulled_prompt_names == [DEFAULT_PROMPT_NAME]
    assert FakeClient.prompt.values == {
        "ticket_subject": ticket.subject,
        "ticket_body": ticket.description,
        "user_email": ticket.email,
    }
    model = FakeChatAnthropic.instances[0]
    assert model.model_name == TEST_MODEL
    assert model.temperature == 0
    assert model.schema is Classification
    assert model.structured_model.prompt == [("human", "rendered prompt")]


def test_refund_classifier_requires_model_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    install_classifier_fakes(monkeypatch)

    with pytest.raises(KeyError, match="ANTHROPIC_MODEL"):
        RefundClassifier()
