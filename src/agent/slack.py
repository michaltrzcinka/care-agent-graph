import os
from typing import Protocol

from slack_sdk.web.async_client import AsyncWebClient


class SlackError(RuntimeError):
    pass


class SlackService(Protocol):
    async def ask_for_approval(self, body: str) -> None: ...

    async def log_execution(self, body: str) -> None: ...


class Slack(SlackService):
    def __init__(self):
        self.approvals_channel = os.getenv("SLACK_APPROVALS_CHANNEL")
        self.log_channel = os.getenv("SLACK_LOG_CHANNEL")
        self._client = AsyncWebClient(token=os.getenv("SLACK_BOT_TOKEN"))

    async def ask_for_approval(self, body: str) -> None:
        await self._send_message(self.approvals_channel, body)

    async def log_execution(self, body: str) -> None:
        await self._send_message(self.log_channel, body)

    async def _send_message(self, channel: str, body: str) -> None:
        response = await self._client.chat_postMessage(channel=channel, text=body)

        if not response.get("ok"):
            raise SlackError(f"Slack API returned an error: {response}")


class DrySlack(Slack):
    async def ask_for_approval(self, body: str) -> None:
        print(
            "[dry-run] Slack approval request\n"
            f"channel: {self.approvals_channel}\n"
            f"body:\n{body}"
        )

    async def log_execution(self, body: str) -> None:
        print(
            "[dry-run] Slack execution log\n"
            f"channel: {self.log_channel}\n"
            f"body:\n{body}"
        )


if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        slack = Slack()
        await slack.ask_for_approval("Test approval")
        await slack.log_execution("Test execution")

    asyncio.run(main())
