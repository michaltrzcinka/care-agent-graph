import asyncio
import json
import os
import pprint
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal, Protocol

import aiohttp

from agent.models import User

ADMIN_PATH = "jfKtZFYdKdv3"
BASE_URL = "https://www.sniffspot.com"

RefundReason = Literal[
    "Not using enough",
    "Too expensive or not worth the cost",
    "Bad experience with spot or host",
    "No nearby or suitable spots",
    "Moving or life change",
    "Pet-related reason",
    "Don\u2019t like the subscription model",
    "Accidental sign up",
    "App, billing, or policy issues",
    "Seasonal or temporary pause",
    "Other",
]

QUERY = """
query($id:ID!){
  user(id:$id){
    id
    uuid
    firstname
    lastname
    activeSniffpass
    hasCanceledSniffpass
    memberships {
      id
      status
      sniffpassType
      sniffpassTypeFull
      period
      active
      price
      dogs
      hours
      remainingCredits
      remainingHours
      renewsAt
      endsAt
      trialEndsAt
      trialStatus
      canceledAt
      userCanceledAt
      cancelReason
      cancelReasonPredefined
      createdAt
      createdFrom
      spot {
        id
        title
      }
    }
  }
}
""".strip()


@dataclass(frozen=True)
class SniffspotTextResponse:
    status: int | None
    location: str | None
    body: str
    transport_error: str | None = None


class SniffspotError(RuntimeError):
    def __init__(
        self,
        message: str,
        subscription_id: int | None = None,
        response: SniffspotTextResponse | None = None,
        **extra: str,
    ) -> None:
        self.details: dict[str, str | int] = {}
        if subscription_id is not None:
            self.details["subscription_id"] = subscription_id

        if response is not None:
            self.details["status"] = response.status or "transport_error"
            if response.transport_error:
                self.details["transport_error"] = response.transport_error
            if response.location:
                self.details["location"] = response.location
            if response.body:
                self.details["body_excerpt"] = self._body_excerpt(response.body)

        self.details.update(extra)

        if self.details:
            super().__init__(f"{message}: {self.details}")
        else:
            super().__init__(message)

    @staticmethod
    def _body_excerpt(body: str, max_length: int = 500) -> str:
        excerpt = " ".join(body.split())
        if len(excerpt) > max_length:
            return excerpt[:max_length] + "..."
        return excerpt


class RefundDueParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refund_due: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_input(tag, attrs)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._handle_input(tag, attrs)

    def _handle_input(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return

        attributes = dict(attrs)
        if attributes.get("name") == "cancel[refund_due]":
            self.refund_due = attributes.get("value")


class SniffspotService(Protocol):
    async def get_user(self, user_id: str) -> User | None: ...

    async def issue_refund(
        self,
        subscription_id: int,
        reason_predefined: RefundReason,
        notes: str | None = None,
        refund_due_override: str | None = None,
        custom_reason: str | None = None,
    ) -> None: ...


class Sniffspot(SniffspotService):
    def __init__(
        self,
        admin_email: str | None = None,
        admin_token: str | None = None,
        base_url: str = BASE_URL,
        admin_path: str = ADMIN_PATH,
    ):
        self.admin_email = admin_email or os.getenv("SNIFFSPOT_ADMIN_EMAIL")
        self.admin_token = admin_token or os.getenv("SNIFFSPOT_ADMIN_TOKEN")
        self.base_url = base_url.rstrip("/")
        self.admin_path = admin_path.strip("/")

    async def get_user(self, user_id: str) -> User | None:
        return await self._get_user(user_id)

    async def issue_refund(
        self,
        subscription_id: int,
        reason_predefined: RefundReason,
        notes: str | None = None,
        refund_due_override: str | None = None,
        custom_reason: str | None = None,
    ) -> None:
        if reason_predefined == "Other" and not custom_reason:
            raise SniffspotError(
                "custom_reason is required when reason_predefined is Other"
            )

        url = (
            f"{self.base_url}/{self.admin_path}/membership~subscription/"
            f"{subscription_id}/cancel_subscription"
        )

        async with aiohttp.ClientSession(headers=self._auth_headers()) as session:
            get_response = await self._request_text(session, url)
            if get_response.status != 200:
                raise SniffspotError(
                    "failed to load Rails Admin cancel page",
                    subscription_id=subscription_id,
                    response=get_response,
                )

            rails_admin_prefill_refund_due = self._scrape_refund_due(
                get_response.body
            )
            if not rails_admin_prefill_refund_due:
                raise SniffspotError(
                    "could not scrape cancel[refund_due] from Rails Admin cancel page",
                    subscription_id=subscription_id,
                    response=get_response,
                )

            refund_due = (
                refund_due_override
                if refund_due_override is not None
                else rails_admin_prefill_refund_due
            )
            refund_due_source = (
                "override" if refund_due_override is not None else "rails_admin_prefill"
            )

            post_data = {
                "cancel[option]": "cancel_and_refund",
                "cancel[refund_due]": refund_due,
                "cancel[reason_predefined]": reason_predefined,
            }
            if custom_reason is not None:
                post_data["cancel[custom_reason]"] = custom_reason
            if notes is not None:
                post_data["cancel[notes]"] = notes

            post_response = await self._request_text(
                session,
                url,
                data=post_data,
                follow_redirects=False,
            )

        if post_response.status == 302:
            return

        if post_response.status == 200:
            raise SniffspotError(
                "Rails Admin re-rendered the cancel page; cancellation/refund likely failed validation",
                subscription_id=subscription_id,
                response=post_response,
                refund_due=refund_due,
                refund_due_source=refund_due_source,
            )

        raise SniffspotError(
            "Rails Admin cancel and refund request failed",
            subscription_id=subscription_id,
            response=post_response,
            refund_due=refund_due,
            refund_due_source=refund_due_source,
        )

    async def _get_user(self, user_id: str) -> User | None:
        auth_headers = self._auth_headers()

        async with aiohttp.ClientSession(headers=auth_headers) as session:
            memberships = await self._request_json(
                session,
                f"{self.base_url}/graphql",
                {
                    "query": QUERY,
                    "variables": {
                        "id": user_id,
                    },
                },
            )

            errors = memberships.get("errors")
            if errors:
                raise SniffspotError(f"GraphQL returned errors: {errors}")

            user = memberships.get("data", {}).get("user")
            if user is None:
                return None

            subscriptions = await self._request_json(
                session,
                f"{self.base_url}/{self.admin_path}/membership~subscription.json",
                params={
                    "f[user][1][v]": user_id,
                    "f[user][1][o]": "is",
                },
            )

        user["subscriptions"] = subscriptions
        return User.model_validate(user)

    def _auth_headers(self) -> dict[str, str]:
        if not self.admin_email or not self.admin_token:
            raise SniffspotError(
                "Sniffspot credentials are required. Set SNIFFSPOT_ADMIN_EMAIL "
                "and SNIFFSPOT_ADMIN_TOKEN, or pass admin_email/admin_token."
            )

        return {
            "User-Agent": "curl/8.7.1",
            "X-USER-EMAIL": self.admin_email,
            "X-USER-TOKEN": self.admin_token,
        }

    async def _request_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        if payload is None:
            response_context = session.get(url, params=params)
        else:
            response_context = session.post(url, json=payload, params=params)

        async with response_context as response:
            response.raise_for_status()
            body = await response.text()

        return json.loads(body)

    async def _request_text(
        self,
        session: aiohttp.ClientSession,
        url: str,
        data: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> SniffspotTextResponse:
        try:
            if data is None:
                response_context = session.get(url, allow_redirects=follow_redirects)
            else:
                response_context = session.post(
                    url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    allow_redirects=follow_redirects,
                )

            async with response_context as response:
                body = await response.text(errors="replace")
                return SniffspotTextResponse(
                    status=response.status,
                    location=response.headers.get("Location"),
                    body=body,
                )
        except (aiohttp.ClientError, TimeoutError, OSError) as error:
            return SniffspotTextResponse(
                status=None,
                location=None,
                body="",
                transport_error=str(error),
            )

    def _scrape_refund_due(self, body: str) -> str | None:
        parser = RefundDueParser()
        parser.feed(body)
        return parser.refund_due


class DrySniffspot(Sniffspot):
    async def issue_refund(
        self,
        subscription_id: int,
        reason_predefined: RefundReason,
        notes: str | None = None,
        refund_due_override: str | None = None,
        custom_reason: str | None = None,
    ) -> None:
        print(
            "[dry-run] Sniffspot refund\n"
            f"subscription_id: {subscription_id}\n"
            f"reason_predefined: {reason_predefined}\n"
            f"notes: {notes}\n"
            f"refund_due_override: {refund_due_override}\n"
            f"custom_reason: {custom_reason}"
        )


if __name__ == "__main__":
    sniffspot = Sniffspot()
    user = asyncio.run(sniffspot.get_user(sys.argv[1]))
    pprint.pprint(user.model_dump(mode="json"), indent=2)
