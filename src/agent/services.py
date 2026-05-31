from dataclasses import dataclass

from langgraph.runtime import Runtime

from agent.classifier import ClassifierService
from agent.helpdesk import HelpDeskService
from agent.models import Context
from agent.slack import SlackService
from agent.sniffspot import SniffspotService


@dataclass
class Services:
    helpdesk: HelpDeskService
    sniffspot: SniffspotService
    slack: SlackService
    classifier: ClassifierService


def _build_default_services() -> Services:
    from agent.classifier import RefundClassifier
    from agent.helpdesk import HelpScout
    from agent.slack import Slack
    from agent.sniffspot import Sniffspot

    return Services(
        helpdesk=HelpScout(),
        sniffspot=Sniffspot(),
        slack=Slack(),
        classifier=RefundClassifier(),
    )


def build_services(runtime: Runtime[Context]) -> Services:
    if runtime.context.services is not None:
        return runtime.context.services

    return _build_default_services()
