import asyncio
import json
import os
import pprint
import sys
import urllib.parse
import urllib.request
from typing import Any, Protocol

from agent.models import User

ADMIN_PATH = "jfKtZFYdKdv3"
BASE_URL = "https://www.sniffspot.com"

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


class SniffspotError(RuntimeError):
    pass


class SniffspotService(Protocol):
    async def get_user(self, user_id: str) -> User | None: ...

    async def issue_refund(self, user: User, ticket_id: str) -> str | None: ...


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
        return await asyncio.to_thread(self._get_user, user_id)

    async def issue_refund(self, user: User, ticket_id: str) -> str | None:
        # TODO: Replace with the Sniffspot admin refund endpoint.
        return None

    def _get_user(self, user_id: str) -> User | None:
        auth_headers = self._auth_headers()

        memberships = self._request_json(
            f"{self.base_url}/graphql",
            auth_headers,
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

        query = urllib.parse.urlencode(
            {
                "f[user][1][v]": user_id,
                "f[user][1][o]": "is",
            }
        )
        subscriptions = self._request_json(
            f"{self.base_url}/{self.admin_path}/membership~subscription.json?{query}",
            auth_headers,
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

    def _request_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json", **headers}

        request = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")

        return json.loads(body)


class DrySniffspot(Sniffspot):
    async def issue_refund(self, user: User, ticket_id: str) -> str | None:
        print(
            "[dry-run] Sniffspot refund\n"
            f"user_id: {user.id}\n"
            f"ticket_id: {ticket_id}"
        )
        return None


if __name__ == "__main__":
    sniffspot = Sniffspot()
    user = asyncio.run(sniffspot.get_user(sys.argv[1]))
    pprint.pprint(user.model_dump(mode="json"), indent=2)
