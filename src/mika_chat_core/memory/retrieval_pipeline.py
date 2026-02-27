"""Retrieval pipeline: decide and apply memory/knowledge injections.

This module keeps the orchestrator thin and makes it easy to evolve the
planner without scattering injection decisions across the codebase.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from ..planning.plan_types import RequestPlan


class RetrievalPipelineClient(Protocol):
    async def _inject_memory_retrieval_context(
        self,
        *,
        message: str,
        user_id: str,
        group_id: Optional[str],
        request_id: str,
        system_injection: Optional[str],
    ) -> Optional[str]: ...

    async def _inject_long_term_memory(
        self,
        *,
        message: str,
        user_id: str,
        group_id: Optional[str],
        request_id: str,
        system_injection: Optional[str],
    ) -> Optional[str]: ...

    async def _inject_knowledge_context(
        self,
        *,
        message: str,
        user_id: str,
        group_id: Optional[str],
        request_id: str,
        system_injection: Optional[str],
    ) -> Optional[str]: ...


async def apply_retrieval_pipeline(
    *,
    client: RetrievalPipelineClient,
    plan: RequestPlan,
    message: str,
    user_id: str,
    group_id: Optional[str],
    request_id: str,
    system_injection: Optional[str],
) -> Optional[str]:
    """Apply retrieval/memory/knowledge injections according to a RequestPlan."""

    injection = system_injection

    if bool(getattr(plan, "use_memory_retrieval", False)):
        return await client._inject_memory_retrieval_context(
            message=message,
            user_id=user_id,
            group_id=group_id,
            request_id=request_id,
            system_injection=injection,
        )

    if bool(getattr(plan, "use_ltm_memory", False)):
        injection = await client._inject_long_term_memory(
            message=message,
            user_id=user_id,
            group_id=group_id,
            request_id=request_id,
            system_injection=injection,
        )

    if bool(getattr(plan, "use_knowledge_auto_inject", False)):
        injection = await client._inject_knowledge_context(
            message=message,
            user_id=user_id,
            group_id=group_id,
            request_id=request_id,
            system_injection=injection,
        )

    return injection


__all__ = ["apply_retrieval_pipeline"]

