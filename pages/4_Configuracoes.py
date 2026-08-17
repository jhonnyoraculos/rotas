from __future__ import annotations

import requests
import streamlit as st

from services.database import (
    connection_description,
    database_stats,
    initialize_database,
    list_unresolved_cities,
    resolve_route_city,
)
from services.excel_importer import import_workbook
from ui.spreadsheet import (
    LOGO_PATH,
    apply_spreadsheet_style,
    render_page_header,
)
from utils.city_normalizer import fetch_state_municipalities
from utils.dates import today_in_brazil

st.set_page_config(
    page_title="Configurações", page_icon=str(LOGO_PATH), layout="wide"
)
apply_spreadsheet_style("settings")
initialize_database()

render_page_header(
    "Configurações",
    "Dados, integrações e saúde operacional do sistema.",
    "Central de controle",
)
st.write(f"**Banco em uso:** {connection_description()}")
stats = database_stats()
columns = st.columns(4)
columns[0].metric("Rotas", stats["rotas"])
columns[1].metric("Cidades/localidades", stats["cidades"])
columns[2].metric("Itens de escala", stats["itens_escala"])
columns[3].metric("Feriados em cache", stats["feriados_cache"])

st.markdown("### Importar ROTAS_2026.xlsx")
st.caption(
    "A importação mescla as rotas e substitui o modelo semanal e a semana atual. "
    "O banco passa a ser a fonte principal após a operação."
)
uploaded = st.file_uploader("Arquivo Excel", type=["xlsx", "xlsm"])
if uploaded is not None and st.button("Analisar e importar", type="primary"):
    try:
        with st.spinner("Analisando abas, rotas e municípios..."):
            analysis = import_workbook(uploaded, reference_date=today_in_brazil())
        st.session_state.pop("weekly_holiday_results", None)
        st.success("Planilha importada.")
        st.code("\n".join(analysis.summary_lines()), language="text")
    except Exception as error:  # noqa: BLE001 - arquivo externo pode falhar de vários modos
        st.error(f"Falha na importação: {error}")

st.markdown("### Localidades pendentes")
unresolved = list_unresolved_cities()
if not unresolved:
    st.success("Todas as localidades cadastradas estão associadas a um município.")
else:
    st.warning(
        f"{len(unresolved)} localidade(s) não identificada(s). Selecione o município real; "
        "o sistema não faz associação aproximada automaticamente."
    )
    unresolved_id = st.selectbox(
        "Localidade",
        options=[item.id for item in unresolved],
        format_func=lambda value: next(
            f"{item.route.code} — {item.city_original}"
            for item in unresolved
            if item.id == value
        ),
    )
    try:
        municipalities = fetch_state_municipalities("MG")
    except (requests.RequestException, ValueError, KeyError) as error:
        municipalities = ()
        st.error(f"Não foi possível carregar os municípios do IBGE: {error}")
    if municipalities:
        municipality_by_code = {item.ibge_code: item for item in municipalities}
        selected_code = st.selectbox(
            "Município correspondente",
            options=sorted(municipality_by_code),
            format_func=lambda value: municipality_by_code[value].name,
        )
        if st.button("Vincular município", type="primary"):
            municipality = municipality_by_code[selected_code]
            resolve_route_city(
                unresolved_id,
                municipality.name,
                municipality.state,
                municipality.ibge_code,
            )
            st.session_state.pop("weekly_holiday_results", None)
            st.success("Localidade vinculada.")
            st.rerun()

st.markdown("### Segredos")
st.code(
    'DATABASE_URL = "postgresql://usuario:senha@host/neondb?sslmode=require"',
    language="toml",
)
st.caption(
    "Salve em .streamlit/secrets.toml localmente ou configure os mesmos nomes nos segredos "
    "do Streamlit Community Cloud. O provedor gratuito de feriados municipais não exige "
    "token. Nunca envie os segredos ao Git."
)
