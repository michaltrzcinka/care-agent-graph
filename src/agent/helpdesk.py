import os
from typing import Protocol

from helpscout import HelpScout as HelpScoutClient

from agent.models import Ticket


class HelpDeskService(Protocol):
    def get_ticket(self, ticket_id: str) -> Ticket: ...

    def leave_private_note(self, ticket_id: str, message: str) -> None: ...

    def reply_to_ticket(
        self, ticket_id: str, message: str, close: bool = False
    ) -> None: ...


class HelpScout(HelpDeskService):
    def __init__(self):
        self._client = HelpScoutClient(
            app_id=os.getenv("HELP_SCOUT_APP_ID"),
            app_secret=os.getenv("HELP_SCOUT_APP_SECRET"),
        )

    def get_ticket(self, ticket_id: str) -> Ticket:
        conversation = self._client.conversations.get(resource_id=ticket_id)
        threads = self._client.conversations[int(ticket_id)].threads.get()
        first_thread = threads[-1]
        description = first_thread.body
        return Ticket(
            id=str(conversation.id),
            subject=conversation.subject,
            description=description,
            email=conversation.primaryCustomer["email"],
        )

    def leave_private_note(self, ticket_id: str, message: str) -> None:
        note_data = {
            "type": "note",
            "text": message,
        }
        self._client.conversations[int(ticket_id)].notes.post(data=note_data)

    def reply_to_ticket(
        self, ticket_id: str, message: str, close: bool = False
    ) -> None:
        pass
        # TODO: Implement

        # thread_data = {
        #     "type": "reply",
        #     "text": message,
        # }
        # self._client.conversations[int(ticket_id)].reply.post(data=thread_data)
        # if close:
        #     self._client.conversations.patch(
        #         resource_id=int(ticket_id),
        #         data={"op": "replace", "path": "/status", "value": "closed"},
        #     )


if __name__ == "__main__":
    helpdesk = HelpScout()
    ticket = helpdesk.get_ticket("3338393447")
    print(ticket)
