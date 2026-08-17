from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from services.excel_importer import analyze_workbook, build_import_snapshot
from utils.city_normalizer import Municipality, normalize_text
from utils.route_parser import extract_route_code


def sample_workbook() -> BytesIO:
    workbook = Workbook()
    schedule = workbook.active
    schedule.title = "CARREGAMENTOS ATUALIZADOS"
    schedule.append(["Relatório de carregamentos"])
    schedule.append(
        ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"]
    )
    schedule.append(
        [
            "DIVINÓPOLIS (R.10)",
            "ITAÚNA ( R. 40 )",
            "PARÁ DE MINAS (R.41)",
            "LAVRAS (R.60)",
            "PONTE NOVA (R.401)",
        ]
    )

    cities = workbook.create_sheet("CIDADES X ROTAS ATUALIZADAS")
    cities["A1"] = "ITAÚNA ( R. 40 )"
    cities["A2"] = "ITAÚNA"
    cities["A3"] = "MATEUS LEME"
    cities["A4"] = "JUATUBA"
    cities["A5"] = "PARÁ DE MINAS (R.41)"
    cities["A6"] = "PARA DE MINAS"
    cities["B1"] = "DIVINÓPOLIS (R.10)"
    cities["B2"] = "DIVINÓPOLIS"

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def test_parser_understands_schedule_and_route_city_blocks() -> None:
    analysis = analyze_workbook(sample_workbook())

    assert analysis.header_row == 2
    assert analysis.schedule[1] == ["R.40"]
    assert analysis.routes["R.40"].cities == ["ITAÚNA", "MATEUS LEME", "JUATUBA"]
    assert analysis.routes["R.41"].cities == ["PARA DE MINAS"]
    assert "R.401" in analysis.routes


def test_route_regex_and_accent_normalization() -> None:
    assert extract_route_code("Itaúna ( R. 040 )") == "R.40"
    assert normalize_text("PARÁ   DE MINAS") == normalize_text("Para de Minas")


def test_route_name_is_included_when_it_is_an_official_municipality(
    monkeypatch,
) -> None:
    analysis = analyze_workbook(sample_workbook())
    municipalities = (
        Municipality("Divinópolis", "MG", "3122306"),
        Municipality("Itaúna", "MG", "3133808"),
        Municipality("Mateus Leme", "MG", "3140704"),
        Municipality("Juatuba", "MG", "3136652"),
        Municipality("Pará de Minas", "MG", "3147105"),
        Municipality("Ponte Nova", "MG", "3152105"),
    )
    monkeypatch.setattr(
        "services.excel_importer.fetch_state_municipalities",
        lambda state: municipalities,
    )

    snapshot = build_import_snapshot(analysis)

    cities = [item["municipality_name"] for item in snapshot["R.401"]["cities"]]
    assert cities == ["Ponte Nova"]
