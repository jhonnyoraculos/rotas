from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from services.database import (
    connection_description,
    ensure_week_schedule,
    initialize_database,
    list_routes,
    load_week_schedule,
    replace_schedule_day,
)
from services.excel_exporter import export_week_to_excel
from services.excel_importer import auto_import_if_available
from services.holidays import HolidayService, holiday_matches_for_display
from ui.spreadsheet import (
    apply_spreadsheet_style,
    render_schedule_table,
    schedule_dataframe,
)
from utils.dates import business_week, monday_of, today_in_brazil, week_title
from utils.route_parser import extract_route_code

st.set_page_config(page_title="Escala de Rotas", page_icon="🗓️", layout="wide")
apply_spreadsheet_style()


try:
    initialize_database()
    imported = auto_import_if_available()
except Exception as error:  # noqa: BLE001 - limite de apresentação da aplicação
    st.error(f"Não foi possível iniciar o banco de dados: {error}")
    st.stop()

if imported:
    st.success("ROTAS_2026.xlsx importado automaticamente na primeira execução.")

if "week_monday" not in st.session_state:
    st.session_state.week_monday = monday_of(today_in_brazil())
if "week_search_date" not in st.session_state:
    st.session_state.week_search_date = st.session_state.week_monday

st.title("Escala semanal de rotas")
left, center, right, spacer = st.columns([1.2, 0.7, 1.2, 4])
with left:
    if st.button("◀ Semana anterior", use_container_width=True):
        st.session_state.week_monday -= timedelta(days=7)
        st.session_state.week_search_date = st.session_state.week_monday
        st.rerun()
with center:
    if st.button("Hoje", use_container_width=True):
        st.session_state.week_monday = monday_of(today_in_brazil())
        st.session_state.week_search_date = today_in_brazil()
        st.rerun()
with right:
    if st.button("Próxima semana ▶", use_container_width=True):
        st.session_state.week_monday += timedelta(days=7)
        st.session_state.week_search_date = st.session_state.week_monday
        st.rerun()

with st.form("week_calendar_search"):
    calendar_col, search_col = st.columns([3, 1], vertical_alignment="bottom")
    with calendar_col:
        searched_date = st.date_input(
            "Pesquisar semana por data",
            key="week_search_date",
            format="DD/MM/YYYY",
            help="Escolha qualquer dia; a semana de segunda a sexta será exibida.",
        )
    with search_col:
        search_week = st.form_submit_button(
            "Pesquisar semana", type="primary", use_container_width=True
        )

if search_week:
    st.session_state.week_monday = monday_of(searched_date)
    st.rerun()

monday = st.session_state.week_monday
st.subheader(week_title(monday))
st.caption(connection_description())

ensure_week_schedule(monday)
schedule = load_week_schedule(monday)
routes = list_routes(active_only=True)

if not routes:
    st.warning(
        "Nenhuma rota foi importada. Coloque ROTAS_2026.xlsx em data/ e reinicie, "
        "ou envie o arquivo na página Configurações."
    )
    st.stop()

with st.spinner("Verificando feriados da semana..."):
    holiday_service = HolidayService()
    matches = holiday_service.match_week(schedule)

render_schedule_table(monday, schedule, matches)

selected_matches = []
try:
    selected_date = date.fromisoformat(str(st.query_params.get("holiday_date")))
    selected_route_id = int(str(st.query_params.get("holiday_route")))
    selected_matches = [
        match
        for match in matches
        if match.date == selected_date and match.route_id == selected_route_id
    ]
except (TypeError, ValueError):
    pass

if selected_matches:
    selected = selected_matches[0]
    st.markdown('<div id="holiday-details"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            f"#### 🔴 {selected.date:%d/%m/%Y} — "
            f"{selected.route_name} ({selected.route_code})"
        )
        for match in selected_matches:
            detail_col1, detail_col2, detail_col3 = st.columns(3)
            detail_col1.markdown(f"**Cidade afetada**  \n{match.city}")
            detail_col2.markdown(f"**Feriado**  \n{match.name}")
            detail_col3.markdown(f"**Tipo**  \n{match.holiday_type}")
        if st.button("Fechar informações", key="close_holiday_details"):
            st.query_params.clear()
            st.rerun()

button_col, export_col, _ = st.columns([1.2, 1.6, 4])
with button_col:
    if st.button(
        "Fechar edição" if st.session_state.get("editing") else "Editar escala",
        use_container_width=True,
    ):
        st.session_state.editing = not st.session_state.get("editing", False)
        st.rerun()
with export_col:
    export_bytes = export_week_to_excel(monday, schedule, matches)
    st.download_button(
        "📥 Exportar semana para Excel",
        data=export_bytes,
        file_name=f"escala_{monday:%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

if st.session_state.get("editing"):
    st.markdown("#### Editar escala")
    st.caption(
        "Digite ou cole o código (ex.: R.40) ou o nome completo. Linhas vazias são ignoradas; "
        "a ordem das células define a posição no dia."
    )
    original = schedule_dataframe(monday, schedule)
    edited = st.data_editor(
        original,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=f"schedule_editor_{monday.isoformat()}",
    )
    if st.button("Salvar alterações", type="primary"):
        routes_by_code = {route.code: route for route in routes}
        routes_by_label = {route.label.casefold(): route for route in routes}
        invalid: list[str] = []
        resolved: dict[date, list[int]] = {}
        for column_index, column in enumerate(edited.columns):
            day = business_week(monday)[column_index]
            ids: list[int] = []
            for raw in edited[column].tolist():
                if pd.isna(raw) or not str(raw).strip():
                    continue
                value = str(raw).strip()
                code = extract_route_code(value)
                route = (
                    routes_by_code.get(code)
                    if code
                    else routes_by_label.get(value.casefold())
                )
                if route is None:
                    invalid.append(f"{column}: {value}")
                else:
                    ids.append(route.id)
            resolved[day] = ids
        if invalid:
            st.error("Rotas não reconhecidas: " + "; ".join(invalid))
        else:
            for day, route_ids in resolved.items():
                replace_schedule_day(day, route_ids)
            st.success("Escala salva.")
            st.rerun()

st.markdown("### Feriados encontrados nesta semana")
display_matches = holiday_matches_for_display(matches)
if not display_matches:
    st.success("Nenhum feriado encontrado para as rotas desta semana.")
else:
    for match in display_matches:
        if match.holiday_type.casefold() == "nacional":
            title = (
                f"🔴 {match.date:%d/%m/%Y} — Todas as cidades — {match.name}"
            )
        else:
            title = (
                f"🔴 {match.date:%d/%m/%Y} — {match.route_name} "
                f"({match.route_code}) — {match.city}"
            )
        with st.expander(
            title
        ):
            st.write(f"**Cidade afetada:** {match.city}")
            st.write(f"**Feriado:** {match.name}")
            st.write(f"**Tipo:** {match.holiday_type}")

if holiday_service.warnings:
    st.info(" ".join(sorted(holiday_service.warnings)))
