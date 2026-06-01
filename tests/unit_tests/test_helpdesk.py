from dataclasses import dataclass

import pytest
from helpscout.exceptions import HelpScoutException

from agent.helpdesk import HelpScout


@dataclass
class FakeConversations:
    error_message: str = ""

    def get(self, resource_id: str):
        raise HelpScoutException(self.error_message)


@dataclass
class FakeClient:
    conversations: FakeConversations


def test_helpscout_get_ticket_returns_none_for_not_found() -> None:
    helpdesk = HelpScout.__new__(HelpScout)
    helpdesk._client = FakeClient(conversations=FakeConversations())

    assert helpdesk.get_ticket("123") is None


def test_helpscout_get_ticket_reraises_non_blank_error() -> None:
    helpdesk = HelpScout.__new__(HelpScout)
    helpdesk._client = FakeClient(conversations=FakeConversations("boom"))

    with pytest.raises(HelpScoutException, match="boom"):
        helpdesk.get_ticket("123")
