from __future__ import annotations

from pathlib import Path

import streamlit as st

from services.database import (
    count_route_weekday_profiles,
    initialize_database,
    list_route_weekday_profiles,
    list_routes,
)
from services.excel_importer import import_weekday_profiles
from ui.spreadsheet import (
    LOGO_PATH,
    apply_spreadsheet_style,
    render_page_header,
    render_route_weekday_profiles,
)

st.set_page_config(
    page_title="Informações das Rotas",
    page_icon=str(LOGO_PATH),
    layout="wide",
)
apply_spreadsheet_style("route_info")
initialize_database()

render_page_header(
    "Informações das rotas",
    "Consulte as cidades atendidas por cada rota em cada dia da semana.",
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
            st.warning(f"Não foi possível organizar a planilha por dia: {error}")

routes = list_routes(active_only=True)
if not routes:
    st.info("Nenhuma rota cadastrada.")
    st.stop()

selected_id = st.selectbox(
    "Pesquisar rota",
    options=[route.id for route in routes],
    format_func=lambda value: next(
        route.label for route in routes if route.id == value
    ),
    help="Digite parte do nome ou do código para localizar uma rota.",
)
route = next(item for item in routes if item.id == selected_id)
profiles = list_route_weekday_profiles(route.id)

scheduled_days = len(profiles)
unique_cities = {
    (city.municipality_name or city.city_original).casefold()
    for profile in profiles
    for city in profile.cities
}
metric_days, metric_cities = st.columns(2)
metric_days.metric("Dias programados", f"{scheduled_days}/5")
metric_cities.metric("Cidades diferentes", len(unique_cities))

st.caption(
    "Informações importadas da aba CIDADES X ROTAS ATUALIZADAS. "
    "Cada coluna representa a composição específica daquele dia."
)

if not profiles:
    st.warning(
        "Esta rota ainda não possui cidades separadas por dia na planilha importada."
    )
else:
    render_route_weekday_profiles(route, profiles)
