from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from services.database import (
    add_manual_holiday,
    delete_manual_holiday,
    initialize_database,
    invalidate_holiday_sync,
    list_holiday_cache,
    list_routes,
)
from services.holidays import clear_holiday_memory_cache
from ui.spreadsheet import (
    LOGO_PATH,
    apply_spreadsheet_style,
    render_holiday_cards,
    render_page_header,
)
from utils.city_normalizer import normalize_text
from utils.dates import today_in_brazil

st.set_page_config(page_title="Feriados", page_icon=str(LOGO_PATH), layout="wide")
apply_spreadsheet_style("holidays")
initialize_database()

render_page_header(
    "Feriados",
    "Pesquise o calendário e mantenha exceções municipais com rapidez.",
    "Calendário operacional",
)

st.markdown("### Pesquisar feriados")
with st.form("holiday_filters"):
    year_col, text_col = st.columns([1, 3])
    with year_col:
        year = st.number_input(
            "Ano", min_value=1900, max_value=2199, value=today_in_brazil().year
        )
    with text_col:
        search_text = st.text_input(
            "Pesquisar",
            placeholder="Digite o nome do feriado ou da cidade",
        )

    entries = list_holiday_cache(int(year))
    city_options = sorted({item.city for item in entries})
    type_options = sorted({item.holiday_type for item in entries})
    source_options = sorted({item.source for item in entries})

    city_col, type_col, source_col = st.columns(3)
    with city_col:
        selected_cities = st.multiselect(
            "Município", options=city_options, placeholder="Todos os municípios"
        )
    with type_col:
        selected_types = st.multiselect(
            "Tipo", options=type_options, placeholder="Todos os tipos"
        )
    with source_col:
        selected_sources = st.multiselect(
            "Fonte", options=source_options, placeholder="Todas as fontes"
        )
    st.form_submit_button("Aplicar filtros", type="primary")

normalized_search = normalize_text(search_text)
filtered_entries = [
    item
    for item in entries
    if (not selected_cities or item.city in selected_cities)
    and (not selected_types or item.holiday_type in selected_types)
    and (not selected_sources or item.source in selected_sources)
    and (
        not normalized_search
        or normalized_search
        in normalize_text(f"{item.city} {item.holiday_name} {item.state}")
    )
]

if filtered_entries:
    st.caption(
        f"{len(filtered_entries)} feriado(s) encontrado(s) de {len(entries)} armazenado(s) no ano."
    )
    with st.container(key="holiday_table"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Data": item.date.strftime("%d/%m/%Y"),
                        "Cidade": item.city,
                        "UF": item.state,
                        "Feriado": item.holiday_name,
                        "Tipo": item.holiday_type,
                        "Fonte": item.source,
                    }
                    for item in filtered_entries
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    render_holiday_cards(filtered_entries)
elif entries:
    st.info("Nenhum feriado corresponde aos filtros selecionados.")
else:
    st.info("Ainda não há feriados armazenados para esse ano.")

st.markdown("### Adicionar feriado manual")
city_options: dict[str, object] = {}
for route in list_routes():
    for city in route.cities:
        label = f"{city.holiday_city} / {city.state}"
        city_options.setdefault(label, city)

if not city_options:
    st.warning("Cadastre cidades nas rotas antes de incluir um feriado municipal.")
else:
    with st.form("manual_holiday", clear_on_submit=True):
        selected = st.selectbox("Município", options=sorted(city_options))
        holiday_date = st.date_input("Data", value=date(int(year), 1, 1))
        holiday_name = st.text_input("Nome do feriado")
        if st.form_submit_button("Salvar feriado", type="primary"):
            city = city_options[selected]
            if not holiday_name.strip():
                st.error("Informe o nome do feriado.")
            else:
                add_manual_holiday(
                    city.holiday_city,
                    city.state,
                    city.ibge_code,
                    holiday_date,
                    holiday_name.strip(),
                    "Municipal",
                )
                st.session_state.pop("weekly_holiday_results", None)
                st.success("Feriado salvo.")
                st.rerun()

manual_entries = [item for item in entries if item.source == "manual"]
if manual_entries:
    selected_manual = st.selectbox(
        "Excluir cadastro manual",
        options=[item.id for item in manual_entries],
        format_func=lambda value: next(
            f"{item.date:%d/%m/%Y} — {item.city} — {item.holiday_name}"
            for item in manual_entries
            if item.id == value
        ),
    )
    if st.button("Excluir selecionado"):
        delete_manual_holiday(selected_manual)
        st.session_state.pop("weekly_holiday_results", None)
        st.success("Cadastro manual excluído.")
        st.rerun()

if st.button("Atualizar consultas online neste ano"):
    invalidate_holiday_sync(year=int(year))
    clear_holiday_memory_cache()
    st.session_state.pop("weekly_holiday_results", None)
    st.success(
        "Cache de consulta invalidado. As cidades serão atualizadas ao abrir uma semana."
    )
