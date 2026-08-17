from __future__ import annotations

from datetime import date
from io import BytesIO
from types import SimpleNamespace

from openpyxl import load_workbook

from services.excel_exporter import export_week_to_excel
from services.holidays import HolidayMatch


def test_export_marks_affected_route_in_red() -> None:
    route = SimpleNamespace(id=40, label="ITAÚNA (R.40)")
    day = date(2026, 8, 21)
    match = HolidayMatch(
        date=day,
        route_id=40,
        route_code="R.40",
        route_name="ITAÚNA",
        city="Mateus Leme",
        name="Feriado Municipal de Teste",
        holiday_type="Municipal",
        source="teste",
    )
    content = export_week_to_excel(date(2026, 8, 17), {day: [route]}, [match])
    workbook = load_workbook(BytesIO(content))
    sheet = workbook["ESCALA SEMANAL"]

    assert sheet["E3"].value.startswith("⚠")
    assert sheet["E3"].fill.fgColor.rgb.endswith("F4CCCC")
    assert "Mateus Leme" in sheet["E3"].comment.text
