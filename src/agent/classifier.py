from typing import Protocol

from langsmith import Client

from agent.models import Classification, Ticket, User

DEFAULT_PROMPT_NAME = "classify_intent"


class ClassifierService(Protocol):
    async def classify(self, ticket: Ticket, user: User) -> Classification: ...


class RefundClassifier(ClassifierService):
    def __init__(self):
        self._prompt = (
            Client()
            .pull_prompt(DEFAULT_PROMPT_NAME, include_model=True)
            .with_structured_output(Classification)
        )

    async def classify(self, ticket: Ticket, user: User) -> Classification:
        return await self._prompt.ainvoke(
            {
                "ticket_subject": ticket.subject,
                "ticket_body": ticket.description,
                "user_email": ticket.email,
            }
        )
