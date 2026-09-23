from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_COMPONENT_PATH = Path(__file__).resolve().parent / "auth_storage_component"
_auth_storage = components.declare_component(
    "jr_auth_storage",
    path=str(_COMPONENT_PATH),
)


def sync_auth_storage(
    *,
    command: str | None = None,
    token: str | None = None,
    command_id: str | None = None,
) -> dict:
    """Lê ou atualiza o token persistente mantido no navegador."""
    value = _auth_storage(
        command=command,
        token=token,
        command_id=command_id,
        key="jr_auth_storage",
        default={"status": "loading", "token": None, "command_id": None},
    )
    return value if isinstance(value, dict) else {"status": "loading", "token": None}
