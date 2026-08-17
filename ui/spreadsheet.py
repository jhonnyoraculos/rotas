from __future__ import annotations

import html
from datetime import date
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from utils.dates import WEEKDAY_NAMES, business_week

SPREADSHEET_CSS = """
<style>
    .block-container {max-width: 1800px; padding-top: 1.2rem; padding-left: 1.5rem; padding-right: 1.5rem;}
    [data-testid="stMetric"] {border: 1px solid #d0d0d0; border-radius: 0; padding: .5rem;}
    .route-sheet {border-collapse: collapse; table-layout: fixed; width: 100%; background: white; font-family: Calibri, Arial, sans-serif; font-size: 14px;}
    .route-sheet th, .route-sheet td {border: 1px solid #b7b7b7; padding: 7px 9px; text-align: left; vertical-align: middle; overflow-wrap: anywhere;}
    .route-sheet th {background: #d9ead3; text-align: center; color: #202020; font-weight: 700;}
    .route-sheet th.alert {background: #f4cccc; color: #9c0006;}
    .route-sheet td {height: 34px; background: #fff;}
    .route-sheet td.alert {background: #f4cccc; color: #9c0006; font-weight: 700; cursor: pointer; padding: 0;}
    .route-sheet td.alert a {display: block; color: inherit; padding: 7px 9px; text-decoration: none;}
    .route-sheet td.alert a:hover {background: #efb7b7;}
    .route-sheet td.empty {color: #aaa;}
    .sheet-caption {font-family: Calibri, Arial, sans-serif; color: #555; font-size: 13px; margin: .25rem 0 .6rem;}
</style>
"""


def apply_spreadsheet_style() -> None:
    st.markdown(SPREADSHEET_CSS, unsafe_allow_html=True)


def render_schedule_table(
    monday: date, schedule: dict[date, list], matches: list
) -> None:
    days = business_week(monday)
    match_map: dict[tuple[date, int], list] = {}
    for match in matches:
        match_map.setdefault((match.date, match.route_id), []).append(match)
    max_rows = max((len(schedule.get(day, [])) for day in days), default=0)
    max_rows = max(max_rows, 1)
    parts = [
        '<div class="sheet-caption">Passe o mouse sobre uma célula vermelha para ver o feriado.</div>'
    ]
    parts.append('<table class="route-sheet"><thead><tr>')
    for index, day in enumerate(days):
        alert = any(match.date == day for match in matches)
        class_name = ' class="alert"' if alert else ""
        prefix = "🔴 " if alert else ""
        parts.append(
            f"<th{class_name}>{prefix}{html.escape(WEEKDAY_NAMES[index])}<br>{day:%d/%m/%Y}</th>"
        )
    parts.append("</tr></thead><tbody>")
    for row_index in range(max_rows):
        parts.append("<tr>")
        for day in days:
            routes = schedule.get(day, [])
            if row_index >= len(routes):
                parts.append('<td class="empty">&nbsp;</td>')
                continue
            route = routes[row_index]
            affected = match_map.get((day, route.id), [])
            if affected:
                tooltip = " | ".join(
                    f"{item.city} — {item.name} ({item.holiday_type})"
                    for item in affected
                )
                query = urlencode(
                    {
                        "holiday_date": day.isoformat(),
                        "holiday_route": route.id,
                    }
                )
                href = html.escape(f"?{query}#holiday-details", quote=True)
                parts.append(
                    f'<td class="alert" title="{html.escape(tooltip, quote=True)}">'
                    f'<a href="{href}" target="_self">⚠ {html.escape(route.label)}</a>'
                    "</td>"
                )
            else:
                parts.append(f"<td>{html.escape(route.label)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def schedule_dataframe(monday: date, schedule: dict[date, list]) -> pd.DataFrame:
    days = business_week(monday)
    max_rows = max((len(schedule.get(day, [])) for day in days), default=0)
    max_rows = max(max_rows + 1, 2)
    data = {}
    for index, day in enumerate(days):
        values = [route.label for route in schedule.get(day, [])]
        values.extend([""] * (max_rows - len(values)))
        data[f"{WEEKDAY_NAMES[index]} {day:%d/%m}"] = values
    return pd.DataFrame(data)
