from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError

from services.database import (
    initialize_database,
    list_routes,
    replace_route_cities,
    save_route,
)
from ui.spreadsheet import (
    LOGO_PATH,
    apply_spreadsheet_style,
    render_page_header,
)

st.set_page_config(
    page_title="Cadastro de Rotas", page_icon=str(LOGO_PATH), layout="wide"
)
apply_spreadsheet_style("routes")
initialize_database()

render_page_header(
    "Cadastro de rotas",
    "Mantenha a relação real entre rota, localidade e município oficial.",
    "Gestão da malha",
)

routes = list_routes()
edit_tab, new_tab = st.tabs(["Editar rota", "Nova rota"])

with edit_tab:
    if not routes:
        st.info("Importe a planilha ou crie a primeira rota.")
    else:
        selected_id = st.selectbox(
            "Rota",
            options=[route.id for route in routes],
            format_func=lambda value: next(
                route.label for route in routes if route.id == value
            ),
        )
        route = next((item for item in routes if item.id == selected_id), None)
        if route:
            with st.form(f"edit_route_form_{route.id}"):
                col1, col2, col3 = st.columns([1, 3, 1])
                code = col1.text_input("Código", value=route.code)
                name = col2.text_input("Nome", value=route.name)
                active = col3.checkbox("Ativa", value=route.active)

                city_data = pd.DataFrame(
                    [
                        {
                            "Localidade original": city.city_original,
                            "Município oficial": city.municipality_name or "",
                            "UF": city.state,
                            "Código IBGE": city.ibge_code or "",
                        }
                        for city in route.cities
                    ],
                    columns=[
                        "Localidade original",
                        "Município oficial",
                        "UF",
                        "Código IBGE",
                    ],
                )
                edited = st.data_editor(
                    city_data,
                    num_rows="dynamic",
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Localidade original": st.column_config.TextColumn(
                            required=True
                        ),
                        "Município oficial": st.column_config.TextColumn(
                            help="Deixe vazio quando a localidade ainda não estiver vinculada."
                        ),
                        "UF": st.column_config.TextColumn(
                            default="MG", width="small"
                        ),
                        "Código IBGE": st.column_config.TextColumn(
                            help="Código de 7 dígitos do município oficial."
                        ),
                    },
                    key=f"cities_{route.id}",
                )
                save_route_cities = st.form_submit_button(
                    "Salvar rota e cidades", type="primary"
                )
            if save_route_cities:
                try:
                    saved = save_route(route.id, code, name, active)
                    rows = []
                    for item in edited.to_dict("records"):
                        original = item.get("Localidade original")
                        if pd.isna(original) or not str(original).strip():
                            continue
                        municipality = item.get("Município oficial")
                        ibge = item.get("Código IBGE")
                        state = item.get("UF")
                        rows.append(
                            {
                                "city_original": str(original).strip(),
                                "municipality_name": ""
                                if pd.isna(municipality)
                                else str(municipality).strip(),
                                "state": "MG" if pd.isna(state) else str(state).strip(),
                                "ibge_code": "" if pd.isna(ibge) else str(ibge).strip(),
                            }
                        )
                    replace_route_cities(saved.id, rows)
                    st.session_state.pop("weekly_holiday_results", None)
                    st.success("Rota salva.")
                    st.rerun()
                except (ValueError, IntegrityError) as error:
                    st.error(f"Não foi possível salvar: {error}")

with new_tab, st.form("new_route", clear_on_submit=True):
    code = st.text_input("Código", placeholder="R.40")
    name = st.text_input("Nome", placeholder="ITAÚNA")
    active = st.checkbox("Ativa", value=True)
    submitted = st.form_submit_button("Adicionar rota", type="primary")
    if submitted:
        try:
            save_route(None, code, name, active)
            st.session_state.pop("weekly_holiday_results", None)
            st.success(
                "Rota adicionada. Selecione-a na aba Editar rota para incluir cidades."
            )
            st.rerun()
        except (ValueError, IntegrityError) as error:
            st.error(f"Não foi possível adicionar: {error}")
