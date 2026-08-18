from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError

from services.database import (
    count_route_weekday_profiles,
    initialize_database,
    list_route_weekday_profiles,
    replace_weekday_route_matrix,
    saved_route_matrix_columns,
)
from services.excel_importer import import_weekday_profiles
from ui.spreadsheet import (
    LOGO_PATH,
    apply_spreadsheet_style,
    render_page_header,
)
from utils.city_normalizer import normalize_text
from utils.dates import monday_of, today_in_brazil
from utils.route_parser import extract_route_code

DAY_LABELS = (
    "SEGUNDA - FEIRA",
    "TERCA - FEIRA",
    "QUARTA - FEIRA",
    "QUINTA - FEIRA",
    "SEXTA - FEIRA",
)


def _display_cell(value: object) -> str:
    text = "" if value is None or pd.isna(value) else str(value).strip()
    return text.lstrip("!* ").strip()


def _cell_class(value: object) -> str:
    text = "" if value is None or pd.isna(value) else str(value).strip()
    display = _display_cell(text)
    normalized = normalize_text(display)
    if not display:
        return "empty"
    if text.startswith("!") or "CONDICAO" in normalized:
        return "matrix-condition"
    if (
        text.startswith("*")
        or extract_route_code(display)
        or normalized.startswith("EXTRA ")
        or "REGIAO" in normalized
    ):
        return "matrix-route"
    return ""


def _columns_dataframe(columns: dict[int, list[str]]) -> pd.DataFrame:
    data = {
        DAY_LABELS[weekday]: list(columns.get(weekday, []))
        for weekday in range(5)
    }
    max_rows = max((len(values) for values in data.values()), default=0)
    max_rows = max(max_rows + 8, 18)
    for label, values in data.items():
        values.extend([""] * (max_rows - len(values)))
        data[label] = values
    return pd.DataFrame(data)


def _matrix_dataframe(profiles: list) -> pd.DataFrame:
    profile_by_weekday: dict[int, list] = {weekday: [] for weekday in range(5)}
    for profile in profiles:
        profile_by_weekday[profile.weekday].append(profile)

    columns: dict[str, list[str]] = {}
    for weekday, label in enumerate(DAY_LABELS):
        lines: list[str] = []
        for profile in sorted(
            profile_by_weekday[weekday], key=lambda item: item.position
        ):
            lines.append(profile.label)
            lines.extend(city.city_original for city in profile.cities)
        columns[label] = lines

    max_rows = max((len(values) for values in columns.values()), default=0)
    max_rows = max(max_rows + 8, 18)
    for label, values in columns.items():
        values.extend([""] * (max_rows - len(values)))
        columns[label] = values
    return pd.DataFrame(columns)


def _edited_columns(dataframe: pd.DataFrame) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for weekday, label in enumerate(DAY_LABELS):
        result[weekday] = [
            "" if pd.isna(value) else str(value).strip()
            for value in dataframe[label].tolist()
        ]
    return result


def _render_matrix_preview(dataframe: pd.DataFrame) -> None:
    parts = [
        '<div class="route-sheet-shell route-matrix-preview">',
        '<div class="route-sheet-desktop"><div class="route-sheet-scroll">',
        '<table class="route-sheet matrix-sheet"><thead><tr>',
    ]
    for label in DAY_LABELS:
        parts.append(f"<th>{html.escape(label)}</th>")
    parts.append("</tr></thead><tbody>")
    for _, row in dataframe.iterrows():
        parts.append("<tr>")
        for label in DAY_LABELS:
            raw_value = row[label]
            display = _display_cell(raw_value)
            class_name = _cell_class(raw_value)
            class_attr = f' class="{class_name}"' if class_name else ""
            content = html.escape(display) if display else "&nbsp;"
            parts.append(f"<td{class_attr}>{content}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div></div></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


st.set_page_config(
    page_title="Informacoes das Rotas",
    page_icon=str(LOGO_PATH),
    layout="wide",
)
apply_spreadsheet_style("route_info")
initialize_database()

render_page_header(
    "Informacoes das rotas",
    "Edite a matriz mestre de rotas e cidades por dia da semana.",
    "Malha semanal",
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
            st.warning(f"Nao foi possivel organizar a planilha por dia: {error}")

save_notice = st.session_state.pop("route_matrix_save_notice", None)
if save_notice:
    st.success(save_notice)

profiles = list_route_weekday_profiles()
saved_columns = saved_route_matrix_columns()
matrix = (
    _columns_dataframe(saved_columns)
    if saved_columns is not None
    else _matrix_dataframe(profiles)
)
unique_routes = {
    profile.route.code
    for profile in profiles
    if getattr(profile, "route", None) is not None
}
unique_cities = {
    city.city_original.casefold()
    for profile in profiles
    for city in profile.cities
}

metric_routes, metric_cities, metric_days = st.columns(3)
metric_routes.metric("Rotas na matriz", len(unique_routes))
metric_cities.metric("Cidades na matriz", len(unique_cities))
metric_days.metric("Dias uteis", "5")

with st.form("route_matrix_form"):
    edited = st.data_editor(
        matrix,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key="route_matrix_editor",
        column_config={
            label: st.column_config.TextColumn(
                label,
                width="large",
            )
            for label in DAY_LABELS
        },
    )
    save_matrix = st.form_submit_button("Salvar matriz de rotas", type="primary")

if save_matrix:
    try:
        replace_weekday_route_matrix(
            _edited_columns(edited),
            reference_monday=monday_of(today_in_brazil()),
        )
        st.session_state.pop("weekly_holiday_results", None)
        st.session_state.route_matrix_save_notice = (
            "Matriz salva. A escala semanal agora usa estas rotas e cidades por dia."
        )
        st.rerun()
    except (ValueError, IntegrityError) as error:
        st.error(f"Nao foi possivel salvar a matriz: {error}")

st.caption(
    "R.xxx fica como rota. CONDICAO ou ! no inicio fica vermelho. "
    "* no inicio fica em negrito na visualizacao."
)

_render_matrix_preview(matrix)
