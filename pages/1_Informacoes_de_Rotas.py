from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError

from services.database import (
    count_route_weekday_profiles,
    initialize_database,
    list_route_weekday_profiles,
    replace_weekday_route_matrix,
)
from services.excel_importer import import_weekday_profiles
from ui.spreadsheet import (
    LOGO_PATH,
    apply_spreadsheet_style,
    render_page_header,
)
from utils.dates import monday_of, today_in_brazil

DAY_LABELS = (
    "SEGUNDA - FEIRA",
    "TERCA - FEIRA",
    "QUARTA - FEIRA",
    "QUINTA - FEIRA",
    "SEXTA - FEIRA",
)


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
matrix = _matrix_dataframe(profiles)
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
    "Linhas com codigo no formato R.10, R.40 ou R.600 viram rotas. "
    "As linhas abaixo de cada rota viram as cidades daquele dia."
)
