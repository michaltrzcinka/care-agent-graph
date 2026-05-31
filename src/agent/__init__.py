"""New LangGraph Agent.

This module defines a custom graph.
"""

from dotenv import load_dotenv

load_dotenv()

from agent.graph import graph

__all__ = ["graph"]
