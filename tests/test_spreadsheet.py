from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from ui.spreadsheet import render_holiday_cards, render_schedule_table


def test_alert_cell_expands_its_holiday_details_inline(monkeypatch) -> None:
    day = date(2026, 8, 19)
    route = SimpleNamespace(id=900, label="BOM DESPACHO (R.900)")
    match = SimpleNamespace(
        date=day,
        route_id=900,
        city="Bom Despacho",
        name="Assunção de Nossa Senhora",
        holiday_type="Municipal",
    )
    rendered: list[str] = []
    monkeypatch.setattr(
        "ui.spreadsheet.st.markdown",
        lambda content, **kwargs: rendered.append(content),
    )

    render_schedule_table(day, {day: [route]}, [match])

    assert len(rendered) == 1
    assert '<details class="holiday-cell">' in rendered[0]
    assert "<summary>" in rendered[0]
    assert "BOM DESPACHO (R.900)" in rendered[0]
    assert "Bom Despacho" in rendered[0]
    assert "Assunção de Nossa Senhora" in rendered[0]
    assert "Municipal" in rendered[0]
    assert "holiday_date=" not in rendered[0]
    assert '<div class="route-week-mobile">' in rendered[0]
    assert '<section class="route-day-card alert">' in rendered[0]
    assert '<details class="route-mobile-item">' in rendered[0]


def test_holiday_cards_render_a_safe_mobile_version(monkeypatch) -> None:
    entry = SimpleNamespace(
        date=date(2026, 8, 19),
        city="Bom Despacho",
        state="MG",
        holiday_name="Feriado <Municipal>",
        holiday_type="Municipal",
        source="manual",
    )
    rendered: list[str] = []
    monkeypatch.setattr(
        "ui.spreadsheet.st.markdown",
        lambda content, **kwargs: rendered.append(content),
    )

    render_holiday_cards([entry])

    assert len(rendered) == 1
    assert '<div class="holiday-mobile-list">' in rendered[0]
    assert "19/08/2026" in rendered[0]
    assert "Bom Despacho" in rendered[0]
    assert "Feriado &lt;Municipal&gt;" in rendered[0]
    assert "Feriado <Municipal>" not in rendered[0]
