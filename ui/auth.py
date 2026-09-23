from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from ui.auth_storage import sync_auth_storage

ROLE_KEY = "jr_access_role"
ADMIN_ROLE = "admin"
VIEWER_ROLE = "viewer"
_STORAGE_ACTION_KEY = "jr_auth_storage_action"
_REMEMBER_SECONDS = 30 * 24 * 60 * 60


def _setting(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value.strip()
    try:
        secret = st.secrets.get(name)
        return str(secret).strip() if secret else None
    except (KeyError, FileNotFoundError, TypeError, StreamlitSecretNotFoundError):
        return None


def _admin_credentials() -> tuple[str | None, str | None]:
    return _setting("ADMIN_USERNAME"), _setting("ADMIN_PASSWORD")


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def _remember_signing_key(username: str, password: str) -> bytes:
    configured_secret = _setting("AUTH_SECRET")
    if configured_secret:
        return configured_secret.encode("utf-8")
    return hashlib.sha256(
        f"jr-rotas\0{username}\0{password}".encode()
    ).digest()


def _create_remember_token(
    username: str, password: str, *, now: int | None = None
) -> str:
    issued_at = int(time.time()) if now is None else now
    payload = {
        "exp": issued_at + _REMEMBER_SECONDS,
        "role": ADMIN_ROLE,
        "sub": username,
        "v": 1,
    }
    body = _urlsafe_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        _remember_signing_key(username, password), body.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{body}.{_urlsafe_encode(signature)}"


def _validate_remember_token(
    token: str, username: str, password: str, *, now: int | None = None
) -> bool:
    try:
        body, encoded_signature = token.split(".", 1)
        expected_signature = hmac.new(
            _remember_signing_key(username, password),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(
            _urlsafe_decode(encoded_signature), expected_signature
        ):
            return False
        payload = json.loads(_urlsafe_decode(body).decode("utf-8"))
        current_time = int(time.time()) if now is None else now
        return (
            payload.get("v") == 1
            and payload.get("role") == ADMIN_ROLE
            and payload.get("sub") == username
            and int(payload.get("exp", 0)) > current_time
        )
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _queue_storage_action(command: str, token: str | None = None) -> None:
    st.session_state[_STORAGE_ACTION_KEY] = {
        "command": command,
        "token": token,
        "command_id": secrets.token_urlsafe(12),
    }


def _sync_browser_session() -> None:
    pending = st.session_state.get(_STORAGE_ACTION_KEY)
    result = sync_auth_storage(
        command=pending.get("command") if pending else None,
        token=pending.get("token") if pending else None,
        command_id=pending.get("command_id") if pending else None,
    )

    if pending:
        if result.get("command_id") == pending.get("command_id"):
            st.session_state.pop(_STORAGE_ACTION_KEY, None)
        return

    if current_role() or result.get("status") != "ready":
        return

    token = result.get("token")
    admin_username, admin_password = _admin_credentials()
    if (
        isinstance(token, str)
        and admin_username
        and admin_password
        and _validate_remember_token(token, admin_username, admin_password)
    ):
        st.session_state[ROLE_KEY] = ADMIN_ROLE
        st.rerun()


def current_role() -> str | None:
    role = st.session_state.get(ROLE_KEY)
    return role if role in {ADMIN_ROLE, VIEWER_ROLE} else None


def is_admin(role: str | None = None) -> bool:
    return (role or current_role()) == ADMIN_ROLE


def require_auth() -> str:
    """Exige uma escolha de acesso e retorna o papel da sessão atual."""
    _sync_browser_session()
    role = current_role()
    if role:
        return role

    st.markdown(
        """
        <style>
          .block-container {max-width:760px!important;padding-top:clamp(2rem,8vh,6rem)!important;}
          .access-kicker {color:#1764a7;font-size:.72rem;font-weight:850;letter-spacing:.15em;text-transform:uppercase;}
          .access-title {margin:.35rem 0 .45rem;color:#092f5d;font-size:clamp(2rem,5vw,3.2rem);font-weight:900;letter-spacing:-.05em;}
          .access-copy {margin:0 0 1.1rem;color:#60738a;}
          [data-testid="stVerticalBlockBorderWrapper"] {background:rgba(255,255,255,.78);border:1px solid rgba(18,82,154,.16)!important;border-radius:22px!important;box-shadow:0 20px 55px rgba(7,43,88,.13);}
        </style>
        <div class="access-kicker">JR Ferragens • Acesso ao sistema</div>
        <div class="access-title">Como você deseja entrar?</div>
        <p class="access-copy">Visitantes podem consultar toda a operação. Alterações são exclusivas do administrador.</p>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        if st.button(
            "Continuar como visitante",
            type="primary",
            width="stretch",
            help="Acesso somente para visualização, sem login.",
        ):
            st.session_state[ROLE_KEY] = VIEWER_ROLE
            st.rerun()

        st.divider()
        st.markdown("#### Entrar como administrador")
        admin_username, admin_password = _admin_credentials()
        with st.form("admin_login_form"):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            remember_access = st.checkbox(
                "Lembrar meu acesso por 30 dias",
                help="Mantém este navegador conectado sem guardar sua senha.",
            )
            submitted = st.form_submit_button(
                "Entrar como administrador", width="stretch"
            )

        if submitted:
            if not admin_username or not admin_password:
                st.error(
                    "Administrador ainda não configurado. Defina ADMIN_USERNAME e "
                    "ADMIN_PASSWORD nos segredos do aplicativo."
                )
            elif hmac.compare_digest(
                username.strip(), admin_username
            ) and hmac.compare_digest(password, admin_password):
                st.session_state[ROLE_KEY] = ADMIN_ROLE
                if remember_access:
                    _queue_storage_action(
                        "store",
                        _create_remember_token(admin_username, admin_password),
                    )
                else:
                    _queue_storage_action("clear")
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")

        if not admin_username or not admin_password:
            st.caption(
                "O acesso de visitante já está disponível. Para habilitar o administrador, "
                "configure as duas credenciais do ambiente."
            )

    st.stop()


def render_account_sidebar(role: str) -> None:
    label = "Administrador" if role == ADMIN_ROLE else "Visitante • somente leitura"
    with st.sidebar:
        st.markdown(
            '<div style="margin:.8rem .4rem .35rem;color:rgba(255,255,255,.48);'
            'font-size:.66rem;font-weight:850;letter-spacing:.14em;text-transform:uppercase">'
            "Sessão</div>"
            '<div style="margin:0 .4rem .65rem;padding:.58rem .7rem;border:1px solid '
            "rgba(255,255,255,.13);border-radius:11px;color:rgba(255,255,255,.86);"
            'background:rgba(255,255,255,.07);font-size:.75rem;font-weight:700">'
            f"{'●' if role == ADMIN_ROLE else '◉'} {label}</div>",
            unsafe_allow_html=True,
        )
        if st.button("Sair", key="logout_session", width="stretch"):
            _queue_storage_action("clear")
            st.session_state.pop(ROLE_KEY, None)
            for state_key in (
                "editing",
                "route_planner_draft",
                "route_planner_source",
                "route_planner_undo",
                "route_planner_redo",
                "route_planner_dialog",
                "route_planner_last_event",
            ):
                st.session_state.pop(state_key, None)
            st.rerun()


def require_admin(role: str) -> None:
    if role == ADMIN_ROLE:
        return
    st.warning("Esta área é exclusiva do administrador.")
    if st.button("Voltar para a escala", type="primary"):
        st.switch_page("app.py")
    st.stop()
