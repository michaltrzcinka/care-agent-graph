import os

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient


class SlackError(RuntimeError):
    pass


class Slack:
    def __init__(self):
        self.approvals_channel = os.getenv("SLACK_APPROVALS_CHANNEL")
        self.log_channel = os.getenv("SLACK_LOG_CHANNEL")
        self._client = AsyncWebClient(token=os.getenv("SLACK_BOT_TOKEN"))

    async def ask_for_approval(self, body: str) -> None:
        await self._send_message(self.approvals_channel, body)

    async def log_execution(self, body: str) -> None:
        await self._send_message(self.log_channel, body)

    async def _send_message(self, channel: str | None, body: str) -> None:
        if not channel:
            raise SlackError("Slack channel is required.")

        try:
            response = await self._client.chat_postMessage(channel=channel, text=body)
        except SlackApiError as error:
            raise SlackError(
                f"Slack API error for channel {channel}: {error.response['error']}"
            ) from error

        if not response.get("ok"):
            raise SlackError(f"Slack API returned an error: {response}")


if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        slack = Slack()
        await slack.ask_for_approval("Test approval")
        await slack.log_execution("Test execution")

    asyncio.run(main())
