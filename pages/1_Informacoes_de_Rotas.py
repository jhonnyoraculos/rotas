from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError

from services.database import (
    connection_description,
    count_route_weekday_profiles,
    initialize_database,
    list_city_registry,
    list_route_weekday_profiles,
    replace_weekday_route_matrix,
    resolve_pending_city_codes,
    save_city_registry,
    saved_route_matrix_columns,
)
from services.excel_importer import import_weekday_profiles
from ui.auth import is_admin, render_account_sidebar, require_auth
from ui.route_planner import render_route_planner
from ui.spreadsheet import LOGO_PATH, apply_spreadsheet_style, render_page_header
from utils.city_normalizer import normalize_text
from utils.dates import monday_of, today_in_brazil
from utils.route_parser import extract_route_code
from utils.route_planner import (
    board_signature,
    board_to_columns,
    clone_board,
    columns_to_board,
    deduplicate_board_cities,
    find_city,
    find_route,
)

DAY_LABELS = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta")
PLANNER_CSS = """
<style>
  .planner-help {display:flex; flex-wrap:wrap; gap:.5rem; margin:-.25rem 0 .8rem;}
  .planner-help span {padding:.34rem .55rem; border:1px solid rgba(18,82,154,.12); border-radius:999px; color:#60748c; background:rgba(255,255,255,.62); font-size:.69rem;}
  .planner-help b {color:#165f9e;}
</style>
"""


def _profiles_to_columns(profiles: list) -> dict[int, list[str]]:
    columns: dict[int, list[str]] = {weekday: [] for weekday in range(5)}
    for profile in sorted(profiles, key=lambda item: (item.weekday, item.position)):
        columns[profile.weekday].append(profile.label)
        columns[profile.weekday].extend(city.city_original for city in profile.cities)
    return columns


def _saved_signature(columns: dict[int, list[str]]) -> str:
    return json.dumps(columns, ensure_ascii=False, sort_keys=True)


def _reset_planner_state(columns: dict[int, list[str]]) -> None:
    st.session_state.route_planner_draft = columns_to_board(columns)
    st.session_state.route_planner_source = _saved_signature(columns)
    st.session_state.route_planner_undo = []
    st.session_state.route_planner_redo = []
    st.session_state.pop("route_planner_dialog", None)


def _ensure_planner_state(columns: dict[int, list[str]]) -> None:
    source = _saved_signature(columns)
    if (
        "route_planner_draft" not in st.session_state
        or st.session_state.get("route_planner_source") != source
    ):
        _reset_planner_state(columns)


def _apply_board_change(updated: dict) -> None:
    # Duplicidades legadas precisam poder ser removidas gradualmente. A validação
    # estrita continua sendo aplicada ao salvar e em cada operação de inclusão.
    board_to_columns(updated, enforce_unique_cities=False)
    previous = st.session_state.route_planner_draft
    if board_signature(previous) == board_signature(updated):
        return
    history = st.session_state.setdefault("route_planner_undo", [])
    history.append(clone_board(previous))
    del history[:-20]
    st.session_state.route_planner_redo = []
    st.session_state.route_planner_draft = clone_board(updated)


def _close_dialog() -> None:
    st.session_state.pop("route_planner_dialog", None)
    st.rerun()


def _parse_city_lines(text: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for line in text.splitlines():
        typed = " ".join(line.split()).strip()
        condition = typed.startswith("!")
        name = typed.lstrip("!* ").strip()
        normalized = normalize_text(name)
        if not normalized or normalized in seen:
            continue
        if extract_route_code(name):
            raise ValueError("O nome da cidade não pode conter um código de rota.")
        seen.add(normalized)
        rows.append(
            {
                "id": f"city-{secrets.token_hex(6)}",
                "name": name,
                "condition": condition or "CONDICAO" in normalized,
            }
        )
    return rows


def _day_city_names(
    day: dict,
    *,
    exclude_route_id: str | None = None,
    exclude_city_id: str | None = None,
) -> dict[str, str]:
    names: dict[str, str] = {}
    for item in day.get("items", []):
        if item.get("kind") != "route" or item.get("id") == exclude_route_id:
            continue
        for city in item.get("cities", []):
            if city.get("id") == exclude_city_id:
                continue
            normalized = normalize_text(city.get("name"))
            if normalized:
                names.setdefault(normalized, str(city.get("name", "")).strip())
    return names


def _city_conflicts(
    day: dict,
    cities: list[dict],
    *,
    exclude_route_id: str | None = None,
    exclude_city_id: str | None = None,
) -> list[str]:
    existing = _day_city_names(
        day,
        exclude_route_id=exclude_route_id,
        exclude_city_id=exclude_city_id,
    )
    return [
        city["name"]
        for city in cities
        if normalize_text(city.get("name")) in existing
    ]


def _show_city_conflicts(conflicts: list[str]) -> None:
    names = ", ".join(dict.fromkeys(conflicts))
    st.error(
        f"A cidade {names} já está cadastrada neste dia. "
        "Uma cidade não pode aparecer em duas rotas do mesmo dia."
    )


def _mark_city_codes_pending() -> None:
    st.session_state.route_city_lookup_notice = True


def _refresh_city_codes_notice() -> None:
    if any(bool(item.get("needs_review")) for item in list_city_registry()):
        _mark_city_codes_pending()
    else:
        st.session_state.pop("route_city_lookup_notice", None)


@st.dialog("Nova rota", width="large")
def _new_route_dialog() -> None:
    board = st.session_state.route_planner_draft
    with st.form("planner_new_route_form"):
        day_col, code_col = st.columns([2, 1])
        weekday = day_col.selectbox(
            "Dia da semana", range(5), format_func=lambda value: DAY_LABELS[value]
        )
        code_typed = code_col.text_input("Código", placeholder="R.40")
        name = st.text_input("Nome da rota", placeholder="ITAÚNA")
        cities_text = st.text_area(
            "Cidades",
            placeholder="Uma cidade por linha\nUse ! no início para condição especial",
            height=150,
        )
        submitted = st.form_submit_button("Criar rota", type="primary")
    if st.button("Cancelar", key="cancel_new_route"):
        _close_dialog()
    if not submitted:
        return
    code = extract_route_code(code_typed)
    if not code or not name.strip():
        st.error("Informe um código no formato R.40 e o nome da rota.")
        return
    day = board["days"][weekday]
    if any(
        item.get("kind") == "route" and item.get("code") == code
        for item in day["items"]
    ):
        st.error(f"A rota {code} já existe em {DAY_LABELS[weekday].lower()}.")
        return
    try:
        cities = _parse_city_lines(cities_text)
    except ValueError as error:
        st.error(str(error))
        return
    conflicts = _city_conflicts(day, cities)
    if conflicts:
        _show_city_conflicts(conflicts)
        return
    updated = clone_board(board)
    updated["days"][weekday]["items"].append(
        {
            "id": f"route-{secrets.token_hex(6)}",
            "kind": "route",
            "code": code,
            "name": " ".join(name.split()).strip(),
            "cities": cities,
        }
    )
    _apply_board_change(updated)
    if cities:
        _mark_city_codes_pending()
    _close_dialog()


@st.dialog("Editar rota", width="large")
def _edit_route_dialog(route_id: str) -> None:
    board = st.session_state.route_planner_draft
    found = find_route(board, route_id)
    if found is None:
        st.warning("Esta rota não está mais no planejamento.")
        if st.button("Fechar"):
            _close_dialog()
        return
    day, route = found
    st.caption(
        f"{DAY_LABELS[day['weekday']]} • código e nome serão atualizados em todos os dias; "
        "as cidades abaixo pertencem somente a este bloco."
    )
    with st.form(f"planner_edit_route_{route_id}"):
        code_col, name_col = st.columns([1, 3])
        code_typed = code_col.text_input("Código", value=route["code"])
        name = name_col.text_input("Nome", value=route["name"])
        cities_text = st.text_area(
            "Cidades e condições",
            value="\n".join(
                f"{'!' if city.get('condition') else ''}{city['name']}"
                for city in route.get("cities", [])
            ),
            height=220,
            help="Uma cidade por linha. Use ! no início para marcar condição especial.",
        )
        submitted = st.form_submit_button("Aplicar alterações", type="primary")
    if st.button("Cancelar", key=f"cancel_edit_route_{route_id}"):
        _close_dialog()
    if not submitted:
        return
    code = extract_route_code(code_typed)
    clean_name = " ".join(name.split()).strip()
    if not code or not clean_name:
        st.error("Informe um código no formato R.40 e o nome da rota.")
        return
    old_code = route["code"]
    if code != old_code:
        for candidate_day in board["days"]:
            has_old = any(
                item.get("kind") == "route" and item.get("code") == old_code
                for item in candidate_day["items"]
            )
            has_new = any(
                item.get("kind") == "route" and item.get("code") == code
                for item in candidate_day["items"]
            )
            if has_old and has_new:
                st.error(
                    f"Não é possível usar {code}: esse código já aparece em {candidate_day['label']}."
                )
                return
    try:
        cities = _parse_city_lines(cities_text)
    except ValueError as error:
        st.error(str(error))
        return
    conflicts = _city_conflicts(day, cities, exclude_route_id=route_id)
    if conflicts:
        _show_city_conflicts(conflicts)
        return
    updated = clone_board(board)
    for candidate_day in updated["days"]:
        for candidate in candidate_day["items"]:
            if candidate.get("kind") == "route" and candidate.get("code") == old_code:
                candidate["code"] = code
                candidate["name"] = clean_name
                if candidate.get("id") == route_id:
                    candidate["cities"] = cities
    _apply_board_change(updated)
    previous_names = {
        normalize_text(city.get("name")) for city in route.get("cities", [])
    }
    if any(normalize_text(city.get("name")) not in previous_names for city in cities):
        _mark_city_codes_pending()
    _close_dialog()


@st.dialog("Adicionar cidade")
def _add_city_dialog(route_id: str) -> None:
    board = st.session_state.route_planner_draft
    found = find_route(board, route_id)
    if found is None:
        _close_dialog()
        return
    day, route = found
    st.caption(f"{route['code']} — {route['name']} • {DAY_LABELS[day['weekday']]}")
    with st.form(f"planner_add_city_{route_id}"):
        names = st.text_area("Novas cidades", placeholder="Uma por linha", height=130)
        condition = st.checkbox("Marcar todas como condição especial")
        submitted = st.form_submit_button("Adicionar", type="primary")
    if st.button("Cancelar", key=f"cancel_add_city_{route_id}"):
        _close_dialog()
    if not submitted:
        return
    try:
        additions = _parse_city_lines(names)
    except ValueError as error:
        st.error(str(error))
        return
    if not additions:
        st.warning("Informe ao menos uma cidade.")
        return
    conflicts = _city_conflicts(day, additions)
    if conflicts:
        _show_city_conflicts(conflicts)
        return
    if condition:
        for city in additions:
            city["condition"] = True
    updated = clone_board(board)
    updated_found = find_route(updated, route_id)
    assert updated_found is not None
    updated_found[1]["cities"].extend(additions)
    _apply_board_change(updated)
    _mark_city_codes_pending()
    _close_dialog()


@st.dialog("Editar cidade")
def _edit_city_dialog(city_id: str) -> None:
    board = st.session_state.route_planner_draft
    found = find_city(board, city_id)
    if found is None:
        _close_dialog()
        return
    day, route, city = found
    st.caption(f"{route['code']} — {route['name']} • {DAY_LABELS[day['weekday']]}")
    with st.form(f"planner_edit_city_{city_id}"):
        name = st.text_input("Cidade/localidade", value=city["name"])
        condition = st.checkbox("Condição especial", value=bool(city.get("condition")))
        submitted = st.form_submit_button("Salvar cidade", type="primary")
    if st.button("Cancelar", key=f"cancel_edit_city_{city_id}"):
        _close_dialog()
    if not submitted:
        return
    clean_name = " ".join(name.split()).strip().lstrip("!* ").strip()
    if not clean_name or extract_route_code(clean_name):
        st.error("Informe uma cidade válida, sem código de rota.")
        return
    conflicts = _city_conflicts(
        day,
        [{"name": clean_name}],
        exclude_city_id=city_id,
    )
    if conflicts:
        _show_city_conflicts(conflicts)
        return
    updated = clone_board(board)
    updated_found = find_city(updated, city_id)
    assert updated_found is not None
    updated_found[2]["name"] = clean_name
    updated_found[2]["condition"] = condition
    _apply_board_change(updated)
    if normalize_text(clean_name) != normalize_text(city.get("name")):
        _mark_city_codes_pending()
    _close_dialog()


@st.dialog("Excluir rota")
def _delete_route_dialog(route_id: str) -> None:
    board = st.session_state.route_planner_draft
    found = find_route(board, route_id)
    if found is None:
        _close_dialog()
        return
    day, route = found
    st.warning(
        f"Remover {route['code']} — {route['name']} de {DAY_LABELS[day['weekday']].lower()}? "
        "As cidades deste bloco serão removidas junto."
    )
    remove_all = st.checkbox("Remover esta rota de todos os dias da semana")
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Excluir", type="primary", width="stretch"):
        updated = clone_board(board)
        for candidate_day in updated["days"]:
            if remove_all or candidate_day["weekday"] == day["weekday"]:
                candidate_day["items"] = [
                    item
                    for item in candidate_day["items"]
                    if not (
                        item.get("kind") == "route"
                        and (
                            item.get("code") == route["code"]
                            if remove_all
                            else item.get("id") == route_id
                        )
                    )
                ]
        _apply_board_change(updated)
        _close_dialog()
    if cancel_col.button("Cancelar", width="stretch"):
        _close_dialog()


@st.dialog("Remover cidade")
def _delete_city_dialog(city_id: str) -> None:
    board = st.session_state.route_planner_draft
    found = find_city(board, city_id)
    if found is None:
        _close_dialog()
        return
    day, route, city = found
    st.warning(
        f"Remover {city['name']} de {route['code']} em {DAY_LABELS[day['weekday']].lower()}?"
    )
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Remover", type="primary", width="stretch"):
        updated = clone_board(board)
        updated_found = find_city(updated, city_id)
        assert updated_found is not None
        updated_found[1]["cities"].remove(updated_found[2])
        _apply_board_change(updated)
        _close_dialog()
    if cancel_col.button("Cancelar", width="stretch"):
        _close_dialog()


def _render_active_dialog() -> None:
    request = st.session_state.get("route_planner_dialog")
    if not request:
        return
    action = request.get("action")
    item_id = request.get("id")
    if action == "new_route":
        _new_route_dialog()
    elif action == "edit_route" and item_id:
        _edit_route_dialog(item_id)
    elif action == "delete_route" and item_id:
        _delete_route_dialog(item_id)
    elif action == "add_city" and item_id:
        _add_city_dialog(item_id)
    elif action == "edit_city" and item_id:
        _edit_city_dialog(item_id)
    elif action == "delete_city" and item_id:
        _delete_city_dialog(item_id)


def _clean_editor_value(value: object, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    return str(value).strip()


def _city_registry_dataframe(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "_normalized_city": item["normalized_city"],
                "Localidade original": item["city_original"],
                "Município oficial": item["municipality_name"],
                "UF": item["state"],
                "Código IBGE": item["ibge_code"],
                "Pendente": item["needs_review"],
            }
            for item in rows
        ]
    )


def _city_registry_rows(dataframe: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for item in dataframe.to_dict("records"):
        original = _clean_editor_value(item.get("Localidade original"))
        if not original:
            continue
        municipality = _clean_editor_value(item.get("Município oficial"))
        state = _clean_editor_value(item.get("UF"), "MG") or "MG"
        ibge = _clean_editor_value(item.get("Código IBGE"))
        rows.append(
            {
                "normalized_city": item.get("_normalized_city"),
                "city_original": original,
                "municipality_name": municipality,
                "state": state,
                "ibge_code": ibge,
            }
        )
    return rows


st.set_page_config(page_title="Rotas", page_icon=str(LOGO_PATH), layout="wide")
role = require_auth()
apply_spreadsheet_style("route_info")
render_account_sidebar(role)
st.markdown(PLANNER_CSS, unsafe_allow_html=True)
initialize_database()
if is_admin(role) and connection_description().startswith("SQLite"):
    st.warning(
        "Banco local ativo. Para que alterações não sejam perdidas após "
        "reinícios ou atualizações no Streamlit Cloud, configure DATABASE_URL "
        "com PostgreSQL/Neon nos segredos do aplicativo."
    )

render_page_header(
    "Rotas",
    "Organize rotas e cidades em um mapa operacional de segunda a sexta.",
    "Blueprint semanal",
)

if count_route_weekday_profiles() == 0:
    workbook = next(
        (
            candidate
            for candidate in (Path("data/ROTAS_2026.xlsx"), Path("ROTAS_2026.xlsx"))
            if candidate.exists()
        ),
        None,
    )
    if workbook is not None:
        try:
            with st.spinner("Organizando as cidades por dia da semana..."):
                import_weekday_profiles(workbook)
        except Exception as error:  # noqa: BLE001 - planilha externa pode variar
            st.warning(f"Não foi possível organizar a planilha por dia: {error}")

save_notice = st.session_state.pop("route_matrix_save_notice", None)
if save_notice:
    st.success(save_notice)
if st.session_state.get("route_city_lookup_notice"):
    st.warning(
        "Cidade nova adicionada. Salve as alterações e depois use "
        "‘Pesquisar códigos pendentes’ no cadastro IBGE."
    )

saved_columns = saved_route_matrix_columns()
if saved_columns is None:
    saved_columns = _profiles_to_columns(list_route_weekday_profiles())
_ensure_planner_state(saved_columns)
draft = st.session_state.route_planner_draft
saved_board = columns_to_board(saved_columns)
dirty = board_signature(draft) != board_signature(saved_board)
sync_value = f"{board_signature(draft)}|{board_signature(saved_board)}"
sync_token = hashlib.sha1(sync_value.encode("utf-8")).hexdigest()

planner_instructions = (
    "<span><b>◇ Visitante</b> consulta em modo somente leitura</span>"
    if not is_admin(role)
    else (
        "<span><b>⠿ Rota</b> arraste o card inteiro</span>"
        "<span><b>● Cidade</b> mova ou reordene o nó</span>"
        "<span><b>⧉ Copiar</b> use o ícone e cole no destino</span>"
        "<span>Arrastes não recarregam a página</span>"
    )
)
st.markdown(
    '<div class="planner-help">'
    f"{planner_instructions}"
    "<span><b>!</b> condição especial</span>"
    "<span>No celular, deslize os dias para o lado</span>"
    "</div>",
    unsafe_allow_html=True,
)

event = render_route_planner(
    draft,
    saved_board,
    can_server_undo=bool(st.session_state.get("route_planner_undo")),
    can_server_redo=bool(st.session_state.get("route_planner_redo")),
    server_dirty=dirty,
    read_only=not is_admin(role),
    sync_token=sync_token,
    key="weekly_route_blueprint",
)
if (
    is_admin(role)
    and event
    and event.get("nonce") != st.session_state.get("route_planner_last_event")
):
    st.session_state.route_planner_last_event = event.get("nonce")
    if event.get("type") == "save":
        try:
            submitted_board = event.get("board") or {}
            cleaned_board, removed_duplicates = deduplicate_board_cities(submitted_board)
            with st.spinner("Salvando o planejamento..."):
                replace_weekday_route_matrix(
                    board_to_columns(cleaned_board),
                    reference_monday=monday_of(today_in_brazil()),
                )
                _refresh_city_codes_notice()
            st.session_state.pop("weekly_holiday_results", None)
            save_message = (
                "Planejamento salvo. Rotas, cidades e ordem semanal foram atualizadas."
            )
            if removed_duplicates:
                duplicate_names = ", ".join(dict.fromkeys(removed_duplicates[:4]))
                remaining = len(removed_duplicates) - len(removed_duplicates[:4])
                suffix = f" e mais {remaining}" if remaining else ""
                save_message += (
                    f" {len(removed_duplicates)} duplicidade(s) legada(s) foram "
                    f"removidas automaticamente: {duplicate_names}{suffix}."
                )
            st.session_state.route_matrix_save_notice = save_message
            st.session_state.route_city_registry_version = (
                st.session_state.get("route_city_registry_version", 0) + 1
            )
            st.session_state.pop("route_planner_draft", None)
            st.rerun()
        except (ValueError, IntegrityError) as error:
            st.error(f"Não foi possível salvar o planejamento: {error}")
    elif event.get("type") == "discard":
        _reset_planner_state(saved_columns)
        st.session_state.pop("route_city_lookup_notice", None)
        st.rerun()
    elif event.get("type") == "undo":
        history = st.session_state.get("route_planner_undo", [])
        if history:
            redo = st.session_state.setdefault("route_planner_redo", [])
            redo.append(clone_board(st.session_state.route_planner_draft))
            del redo[:-20]
            st.session_state.route_planner_draft = history.pop()
            st.rerun()
    elif event.get("type") == "redo":
        redo = st.session_state.get("route_planner_redo", [])
        if redo:
            history = st.session_state.setdefault("route_planner_undo", [])
            history.append(clone_board(st.session_state.route_planner_draft))
            del history[:-20]
            st.session_state.route_planner_draft = redo.pop()
            st.rerun()
    elif event.get("type") == "action":
        try:
            _apply_board_change(event.get("board") or draft)
            st.session_state.route_planner_dialog = {
                "action": event.get("action"),
                "id": event.get("id"),
            }
            st.rerun()
        except ValueError as error:
            st.error(str(error))

if is_admin(role):
    _render_active_dialog()

with st.expander("Cadastro técnico de cidades e códigos IBGE"):
    st.caption(
        "Consulta dos vínculos municipais em modo somente leitura."
        if not is_admin(role)
        else "Ajuste vínculos municipais quando necessário. Esta seção continua usando o cadastro atual."
    )
    city_rows = list_city_registry()
    if not city_rows:
        st.info("Salve o planejamento para carregar as cidades aqui.")
    else:
        lookup_result = st.session_state.pop("route_city_lookup_result", None)
        if lookup_result:
            resolved_names = lookup_result.get("resolved", [])
            unresolved_names = lookup_result.get("unresolved", [])
            lookup_errors = lookup_result.get("errors", [])
            if resolved_names:
                st.success(
                    f"{len(resolved_names)} código(s) IBGE encontrado(s) e salvo(s)."
                )
            if unresolved_names:
                st.warning(
                    "Não foi possível localizar: "
                    + ", ".join(dict.fromkeys(unresolved_names))
                )
            if lookup_errors:
                st.error("Falha na consulta ao IBGE: " + " | ".join(lookup_errors))

        pending_count = sum(bool(item.get("needs_review")) for item in city_rows)
        if is_admin(role):
            if pending_count:
                st.warning(
                    f"{pending_count} cidade(s) aguardando código IBGE. "
                    "A pesquisa consultará somente estas pendências."
                )
            else:
                st.success("Todos os códigos IBGE estão atualizados.")

        city_registry = _city_registry_dataframe(city_rows)
        registry_version = st.session_state.get("route_city_registry_version", 0)
        edited_cities = st.data_editor(
            city_registry,
            hide_index=True,
            width="stretch",
            disabled=(True if not is_admin(role) else ["_normalized_city", "Pendente"]),
            column_config={
                "_normalized_city": None,
                "Localidade original": st.column_config.TextColumn(width="medium"),
                "Município oficial": st.column_config.TextColumn(width="medium"),
                "UF": st.column_config.TextColumn(width="small"),
                "Código IBGE": st.column_config.TextColumn(width="small"),
                "Pendente": st.column_config.CheckboxColumn(width="small"),
            },
            key=f"route_city_registry_editor_{registry_version}",
        )
        if is_admin(role):
            save_col, search_col = st.columns(2)
            if save_col.button("Salvar cidades e códigos", type="primary"):
                try:
                    save_city_registry(_city_registry_rows(edited_cities))
                    _refresh_city_codes_notice()
                    st.session_state.pop("weekly_holiday_results", None)
                    st.session_state.route_matrix_save_notice = (
                        "Cidades e códigos IBGE salvos."
                    )
                    st.session_state.route_city_registry_version = registry_version + 1
                    st.rerun()
                except (ValueError, IntegrityError) as error:
                    st.error(f"Não foi possível salvar as cidades: {error}")
            if search_col.button(
                "Pesquisar códigos pendentes",
                disabled=pending_count == 0,
                help="Consulta apenas cidades marcadas como pendentes.",
            ):
                with st.spinner("Consultando somente as cidades pendentes..."):
                    result = resolve_pending_city_codes()
                st.session_state.route_city_lookup_result = result
                st.session_state.pop("route_city_lookup_notice", None)
                st.session_state.pop("weekly_holiday_results", None)
                st.session_state.route_city_registry_version = registry_version + 1
                st.rerun()
