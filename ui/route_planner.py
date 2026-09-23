from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_COMPONENT_PATH = Path(__file__).resolve().parent / "route_planner_component"
_route_planner = components.declare_component(
    "jr_route_planner",
    path=str(_COMPONENT_PATH),
)


def render_route_planner(board: dict, *, key: str) -> dict | None:
    """Renderiza o quadro e devolve eventos de interação para o Streamlit."""
    return _route_planner(board=board, key=key, default=None)
