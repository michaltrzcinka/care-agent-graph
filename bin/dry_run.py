from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, cast

from dotenv import load_dotenv
from pydantic import BaseModel

from agent.graph import build_graph
from agent.models import Context, ExecutionMode


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


async def _run(
    helpscout_conversation_id: str, execution_mode: ExecutionMode
) -> dict[str, Any]:
    graph = build_graph()
    final_state: dict[str, Any] = {}

    print("[dry-run] graph stream")
    async for event in graph.astream(
        {"helpscout_conversation_id": helpscout_conversation_id},
        context=Context(execution_mode=execution_mode, dry_run=True),
        stream_mode=["updates", "values"],
    ):
        stream_mode, payload = event
        if stream_mode == "values":
            final_state = payload
            continue

        for node_name, update in payload.items():
            print(f"\n[dry-run] node: {node_name}")
            print(json.dumps(update, indent=2, sort_keys=True, default=_json_default))

    return final_state


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Care Agent graph with dry-run write services."
    )
    parser.add_argument("helpscout_conversation_id")
    parser.add_argument(
        "--execution-mode",
        choices=("automation", "review"),
        default="automation",
        help="Graph execution mode. Defaults to automation.",
    )
    args = parser.parse_args()

    load_dotenv()
    execution_mode = cast(ExecutionMode, args.execution_mode)
    result = asyncio.run(_run(args.helpscout_conversation_id, execution_mode))

    print("\n[dry-run] graph result")
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
