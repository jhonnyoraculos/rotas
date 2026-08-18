from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, JsCode

from services.database import (
    count_route_weekday_profiles,
    initialize_database,
    list_city_registry,
    list_route_weekday_profiles,
    replace_weekday_route_matrix,
    save_city_registry,
    saved_route_matrix_columns,
)
from services.excel_importer import import_weekday_profiles
from ui.spreadsheet import (
    LOGO_PATH,
    apply_spreadsheet_style,
    render_page_header,
)
from utils.city_normalizer import resolve_municipality_fields
from utils.dates import monday_of, today_in_brazil
from utils.route_matrix import add_cities_to_route_block, route_choices_for_weekday

DAY_LABELS = (
    "SEGUNDA-FEIRA",
    "TERÇA-FEIRA",
    "QUARTA-FEIRA",
    "QUINTA-FEIRA",
    "SEXTA-FEIRA",
)


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


def _grid_options(dataframe: pd.DataFrame) -> dict:
    builder = GridOptionsBuilder.from_dataframe(dataframe)
    builder.configure_default_column(
        editable=True,
        filter=False,
        resizable=True,
        sortable=False,
        suppressMenu=True,
        wrapText=False,
    )
    cell_style = JsCode(
        """
        function(params) {
            const raw = String(params.value || '').trim();
            const text = raw.replace(/^[!*\\s]+/, '').trim();
            const normalized = text
                .normalize('NFD')
                .replace(/[\\u0300-\\u036f]/g, '')
                .toUpperCase();
            if (!text) {
                return {
                    backgroundColor: 'rgba(255,255,255,.84)',
                    color: 'transparent'
                };
            }
            if (raw.startsWith('!') || normalized.includes('CONDICAO')) {
                return {
                    color: '#e00000',
                    fontWeight: '520',
                    backgroundColor: 'rgba(255,255,255,.90)'
                };
            }
            if (
                raw.startsWith('*') ||
                /\\(?\\s*R\\s*\\.\\s*\\d+\\s*\\)?/i.test(text) ||
                normalized.startsWith('EXTRA ') ||
                normalized.includes('REGIAO')
            ) {
                return {
                    color: '#050b14',
                    fontWeight: '850',
                    textAlign: 'center',
                    backgroundColor: 'rgba(255,255,255,.92)'
                };
            }
            return {
                color: '#0f233d',
                fontWeight: '430',
                backgroundColor: 'rgba(255,255,255,.84)'
            };
        }
        """
    )
    formatter = JsCode(
        """
        function(params) {
            return String(params.value || '').replace(/^[!*\\s]+/, '').trim();
        }
        """
    )
    for label in DAY_LABELS:
        builder.configure_column(
            label,
            cellStyle=cell_style,
            valueFormatter=formatter,
            minWidth=245,
        )
    options = builder.build()
    options["headerHeight"] = 28
    options["rowHeight"] = 24
    options["singleClickEdit"] = True
    options["stopEditingWhenCellsLoseFocus"] = True
    options["suppressMovableColumns"] = True
    return options


def _grid_data(response: object) -> pd.DataFrame:
    data = response["data"] if isinstance(response, dict) else response.data
    dataframe = pd.DataFrame(data)
    return dataframe.reindex(columns=DAY_LABELS).fillna("")


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
        ],
        columns=[
            "_normalized_city",
            "Localidade original",
            "Município oficial",
            "UF",
            "Código IBGE",
            "Pendente",
        ],
    )


def _clean_editor_value(value: object, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    return str(value).strip()


def _city_registry_rows(dataframe: pd.DataFrame) -> tuple[list[dict], int]:
    rows: list[dict] = []
    auto_filled = 0
    for item in dataframe.to_dict("records"):
        original = _clean_editor_value(item.get("Localidade original"))
        if not original:
            continue
        municipality = _clean_editor_value(item.get("Município oficial"))
        state = _clean_editor_value(item.get("UF"), "MG") or "MG"
        ibge = _clean_editor_value(item.get("Código IBGE"))
        resolved_name, resolved_state, resolved_code = resolve_municipality_fields(
            original,
            municipality,
            state,
            ibge,
        )
        if not ibge and resolved_code:
            auto_filled += 1
        rows.append(
            {
                "normalized_city": item.get("_normalized_city"),
                "city_original": original,
                "municipality_name": resolved_name,
                "state": resolved_state,
                "ibge_code": resolved_code,
            }
        )
    return rows, auto_filled


def _resolve_and_save_city_registry(dataframe: pd.DataFrame) -> int:
    resolved_rows, auto_filled = _city_registry_rows(dataframe)
    # O botão também confirma edições manuais. Salvar somente quando um código
    # era encontrado fazia município, localidade e código digitados voltarem ao
    # valor anterior depois do rerun do Streamlit.
    save_city_registry(resolved_rows)
    return auto_filled


def _advance_city_registry_editor() -> None:
    st.session_state.city_registry_editor_version = (
        st.session_state.get("city_registry_editor_version", 0) + 1
    )


def _advance_route_matrix_grid() -> None:
    st.session_state.route_matrix_grid_version = (
        st.session_state.get("route_matrix_grid_version", 0) + 1
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
            st.warning(f"Não foi possível organizar a planilha por dia: {error}")

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

st.markdown("### Adicionar cidades à rota")
st.caption(
    "Escolha o dia e a rota. Você pode colar várias cidades, uma em cada linha. "
    "A inclusão é salva automaticamente."
)
selected_weekday = st.selectbox(
    "Dia da semana",
    options=list(range(5)),
    format_func=lambda weekday: DAY_LABELS[weekday].capitalize(),
    key="new_city_weekday",
)
route_choices = route_choices_for_weekday(
    _edited_columns(matrix), selected_weekday
)
if not route_choices:
    st.info("Não há rotas cadastradas nesse dia.")
else:
    route_labels = {code: label for code, label in route_choices}
    with st.form("add_route_cities_form"):
        selected_route_code = st.selectbox(
            "Rota",
            options=list(route_labels),
            format_func=lambda code: route_labels[code],
        )
        new_cities_text = st.text_area(
            "Novas cidades",
            placeholder="Digite uma cidade por linha\nEx.: NOVA SERRANA\nPERDIGÃO",
            height=110,
        )
        mark_as_condition = st.checkbox(
            "Marcar todas como condição (texto vermelho)"
        )
        add_cities = st.form_submit_button(
            "Adicionar cidades à rota", type="primary"
        )

    if add_cities:
        try:
            city_names = new_cities_text.splitlines()
            updated_columns, added_count = add_cities_to_route_block(
                _edited_columns(matrix),
                selected_weekday,
                selected_route_code,
                city_names,
                condition=mark_as_condition,
            )
            if not added_count:
                st.warning(
                    "Informe ao menos uma cidade nova. Cidades repetidas não são "
                    "adicionadas novamente."
                )
            else:
                replace_weekday_route_matrix(
                    updated_columns,
                    reference_monday=monday_of(today_in_brazil()),
                )
                st.session_state.pop("weekly_holiday_results", None)
                city_word = (
                    "cidade adicionada"
                    if added_count == 1
                    else "cidades adicionadas"
                )
                st.session_state.route_matrix_save_notice = (
                    f"{added_count} {city_word} à rota {route_labels[selected_route_code]} "
                    f"de {DAY_LABELS[selected_weekday].lower()}."
                )
                _advance_route_matrix_grid()
                st.rerun()
        except (ValueError, IntegrityError) as error:
            st.error(f"Não foi possível adicionar as cidades: {error}")

custom_css = {
    ".ag-root-wrapper": {
        "border": "0 !important",
        "border-radius": "18px !important",
        "overflow": "hidden !important",
        "box-shadow": "0 18px 50px rgba(7, 43, 88, .12) !important",
    },
    ".ag-header": {
        "background": "linear-gradient(145deg, #0c477f, #082f61) !important",
        "border-bottom": "1px solid rgba(255,255,255,.18) !important",
    },
    ".ag-header-cell": {
        "background": "transparent !important",
        "border-right": "1px solid rgba(255,255,255,.18) !important",
        "color": "#fff !important",
    },
    ".ag-header-cell-text": {
        "color": "#fff !important",
        "font-size": "14px !important",
        "font-weight": "850 !important",
        "text-transform": "uppercase !important",
    },
    ".ag-cell": {
        "border-right": "1px solid rgba(7,43,88,.12) !important",
        "border-bottom": "1px solid rgba(7,43,88,.12) !important",
        "font-size": "12px !important",
        "line-height": "22px !important",
        "padding-left": "6px !important",
        "padding-right": "6px !important",
    },
    ".ag-row-hover .ag-cell": {
        "background-color": "rgba(235,245,255,.96) !important",
    },
    ".ag-cell-inline-editing": {
        "background": "#fff !important",
        "box-shadow": "inset 0 0 0 2px rgba(18,82,154,.48) !important",
    },
}

grid_version = st.session_state.get("route_matrix_grid_version", 0)
grid_key = f"route_matrix_grid_data_{grid_version}"
for state_key in list(st.session_state):
    if state_key.startswith("route_matrix_grid_data_") and state_key != grid_key:
        st.session_state.pop(state_key, None)

grid_response = AgGrid(
    matrix,
    gridOptions=_grid_options(matrix),
    height=min(max(420, len(matrix) * 24 + 48), 820),
    data_return_mode=DataReturnMode.AS_INPUT,
    update_on=["cellValueChanged"],
    allow_unsafe_jscode=True,
    theme="streamlit",
    custom_css=custom_css,
    key=grid_key,
    show_search=False,
    show_toolbar=False,
    show_download_button=False,
)
edited = _grid_data(grid_response)

save_matrix = st.button("Salvar matriz de rotas", type="primary")

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
        _advance_route_matrix_grid()
        st.rerun()
    except (ValueError, IntegrityError) as error:
        st.error(f"Não foi possível salvar a matriz: {error}")

city_rows = list_city_registry()
st.markdown("### Cidades e códigos IBGE")
if not city_rows:
    st.info("Salve a matriz para carregar as cidades aqui.")
else:
    city_registry = _city_registry_dataframe(city_rows)
    editor_version = st.session_state.get("city_registry_editor_version", 0)
    editor_key = f"city_registry_editor_data_{editor_version}"
    for state_key in list(st.session_state):
        if (
            state_key.startswith("city_registry_editor_data_")
            and state_key != editor_key
        ):
            st.session_state.pop(state_key, None)
    edited_cities = st.data_editor(
        city_registry,
        hide_index=True,
        width="stretch",
        disabled=["_normalized_city", "Pendente"],
        column_config={
            "_normalized_city": None,
            "Localidade original": st.column_config.TextColumn(width="medium"),
            "Município oficial": st.column_config.TextColumn(width="medium"),
            "UF": st.column_config.TextColumn(width="small"),
            "Código IBGE": st.column_config.TextColumn(width="small"),
            "Pendente": st.column_config.CheckboxColumn(width="small"),
        },
        key=editor_key,
    )
    load_codes_col, save_codes_col = st.columns([1, 1])
    with load_codes_col:
        load_codes = st.button("Carregar códigos", type="secondary")
    with save_codes_col:
        save_codes = st.button("Salvar cidades e códigos", type="primary")

    if load_codes:
        try:
            auto_filled_now = _resolve_and_save_city_registry(edited_cities)
            st.session_state.pop("weekly_holiday_results", None)
            st.session_state.route_matrix_save_notice = (
                (
                    "1 código IBGE preenchido."
                    if auto_filled_now == 1
                    else f"{auto_filled_now} códigos IBGE preenchidos."
                )
                if auto_filled_now
                else (
                    "Alterações salvas. Nenhum novo código IBGE foi encontrado "
                    "automaticamente."
                )
            )
            _advance_city_registry_editor()
            st.rerun()
        except (ValueError, IntegrityError) as error:
            st.error(f"Não foi possível carregar os códigos: {error}")

    if save_codes:
        try:
            resolved_rows, auto_filled = _city_registry_rows(edited_cities)
            save_city_registry(resolved_rows)
            st.session_state.pop("weekly_holiday_results", None)
            message = "Cidades e códigos IBGE salvos."
            if auto_filled:
                filled_message = (
                    "1 código preenchido automaticamente."
                    if auto_filled == 1
                    else f"{auto_filled} códigos preenchidos automaticamente."
                )
                message += f" {filled_message}"
            st.session_state.route_matrix_save_notice = message
            _advance_city_registry_editor()
            st.rerun()
        except (ValueError, IntegrityError) as error:
            st.error(f"Não foi possível salvar as cidades: {error}")
