from __future__ import annotations

from datetime import date

from sqlalchemy import select

from models import Route, RouteCity, WeeklySchedule
from services import database
from services.excel_importer import sync_canonical_workbook_if_changed


def _snapshot(code: str, city: str) -> dict[str, dict]:
    return {
        code: {
            "name": f"Rota {code}",
            "cities": [
                {
                    "city_original": city,
                    "municipality_name": city.title(),
                    "state": "MG",
                    "ibge_code": None,
                    "needs_review": True,
                }
            ],
        }
    }


def test_replacing_workbook_removes_previous_routes_and_schedule(
    monkeypatch, tmp_path
) -> None:
    url = f"sqlite:///{tmp_path / 'replacement.db'}"
    database.initialize_database(url)
    original_session_scope = database.session_scope
    monkeypatch.setattr(database, "session_scope", lambda: original_session_scope(url))

    monday = date(2026, 9, 21)
    database.import_snapshot(
        _snapshot("R.10", "Cidade antiga"),
        {0: ["R.10"], 1: [], 2: [], 3: [], 4: []},
        monday,
    )
    database.import_snapshot(
        _snapshot("R.20", "Cidade nova"),
        {0: [], 1: ["R.20"], 2: [], 3: [], 4: []},
        monday,
        replace_existing=True,
        source_signature="versao-nova",
    )

    with original_session_scope(url) as session:
        assert [route.code for route in session.scalars(select(Route))] == ["R.20"]
        assert [city.city_original for city in session.scalars(select(RouteCity))] == [
            "Cidade nova"
        ]
        assert len(list(session.scalars(select(WeeklySchedule)))) == 1
    assert database.canonical_workbook_signature() == "versao-nova"


def test_canonical_workbook_is_imported_only_when_its_version_changes(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    workbook = tmp_path / "ROTAS_2026.xlsx"
    workbook.write_bytes(b"nova planilha")
    imported: list[tuple[object, dict]] = []
    monkeypatch.setattr(
        "services.database.canonical_workbook_signature", lambda: "assinatura-atual"
    )
    monkeypatch.setattr(
        "services.excel_importer._workbook_signature", lambda path: "assinatura-atual"
    )
    monkeypatch.setattr(
        "services.excel_importer.import_workbook",
        lambda source, **kwargs: imported.append((source, kwargs)) or "resultado",
    )

    assert sync_canonical_workbook_if_changed() is None
    monkeypatch.setattr(
        "services.excel_importer._workbook_signature", lambda path: "assinatura-nova"
    )
    assert sync_canonical_workbook_if_changed() == "resultado"
    assert imported == [
        (
            workbook.relative_to(tmp_path),
            {"replace_existing": True, "source_signature": "assinatura-nova"},
        )
    ]
