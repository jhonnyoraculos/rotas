from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from ui.spreadsheet import render_schedule_table


def test_alert_cell_links_to_its_holiday_details(monkeypatch) -> None:
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
    assert "holiday_date=2026-08-19" in rendered[0]
    assert "holiday_route=900" in rendered[0]
    assert 'target="_self"' in rendered[0]
    assert "BOM DESPACHO (R.900)" in rendered[0]
