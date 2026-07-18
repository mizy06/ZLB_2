from __future__ import annotations

from .normalize import normalize_graph
from .schemas import AssembleRequest, NormalizeRequest, SolveRequest, SolveResponse
from .topology import solve_topology


def assemble_mindmap(request: AssembleRequest) -> SolveResponse:
    normalized = normalize_graph(
        NormalizeRequest.model_validate(request.model_dump())
    )
    return solve_topology(
        SolveRequest(
            graph=normalized,
            mode=request.mode,
            max_depth=request.max_depth,
            time_limit_seconds=request.time_limit_seconds,
        )
    )
