from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_COMPONENT_PATH = Path(__file__).resolve().parent / "route_planner_component"
_route_planner = components.declare_component(
    "jr_route_planner",
    path=str(_COMPONENT_PATH),
)


def render_route_planner(
    board: dict,
    saved_board: dict,
    *,
    can_server_undo: bool,
    can_server_redo: bool,
    server_dirty: bool,
    read_only: bool,
    sync_token: str,
    key: str,
) -> dict | None:
    """Renderiza o quadro e devolve eventos de interação para o Streamlit."""
    return _route_planner(
        board=board,
        saved_board=saved_board,
        can_server_undo=can_server_undo,
        can_server_redo=can_server_redo,
        server_dirty=server_dirty,
        read_only=read_only,
        sync_token=sync_token,
        key=key,
        default=None,
    )
