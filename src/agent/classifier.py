import os

from agent.models import Classification, Ticket, User

DEFAULT_MODEL = "claude-3-5-haiku-20241022"


class RefundClassifier:
    def __init__(self, model: str | None = None):
        from langchain_anthropic import ChatAnthropic

        self._model = ChatAnthropic(
            model=model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL),
            temperature=0,
        ).with_structured_output(Classification)

    async def classify(self, ticket: Ticket, user: User) -> Classification:
        result = await self._model.ainvoke(
            [
                (
                    "system",
                    "Classify the support ticket intent. Return refund only when "
                    "the customer is asking for a refund. Otherwise return other.",
                ),
                (
                    "human",
                    "\n".join(
                        [
                            f"Ticket subject: {ticket.subject}",
                            f"Ticket body: {ticket.description}",
                            f"Customer email: {ticket.email}",
                            f"Sniffspot user id: {user.id}",
                        ]
                    ),
                ),
            ]
        )

        if isinstance(result, Classification):
            return result

        return Classification.model_validate(result)
