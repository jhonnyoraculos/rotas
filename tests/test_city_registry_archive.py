from __future__ import annotations

from datetime import date

from services import database


def test_removing_city_keeps_its_ibge_code_but_excludes_it_from_week_holidays(
    monkeypatch, tmp_path
) -> None:
    url = f"sqlite:///{tmp_path / 'city-registry.db'}"
    database.initialize_database(url)
    original_session_scope = database.session_scope
    monkeypatch.setattr(database, "session_scope", lambda: original_session_scope(url))

    monday = date(2026, 9, 21)
    database.replace_weekday_route_matrix(
        {0: ["ITAUNA (R.40)", "ITAUNA", "AZURITA"]},
        reference_monday=monday,
    )
    azurita = next(
        row
        for row in database.list_city_registry()
        if row["city_original"] == "AZURITA"
    )
    database.save_city_registry(
        [
            {
                **azurita,
                "municipality_name": "Azurita",
                "state": "MG",
                "ibge_code": "3199999",
            }
        ]
    )

    database.replace_weekday_route_matrix(
        {0: ["ITAUNA (R.40)", "ITAUNA"]},
        reference_monday=monday,
    )

    archived = next(
        row
        for row in database.list_city_registry()
        if row["city_original"] == "AZURITA"
    )
    assert archived["ibge_code"] == "3199999"

    schedule = database.load_week_schedule(monday)
    route_ids = [route.id for route in schedule[monday]]
    active_week_cities = database.list_week_holiday_city_rows(route_ids)
    assert all(row["city_original"] != "AZURITA" for row in active_week_cities)
