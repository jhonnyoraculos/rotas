from __future__ import annotations

from datetime import date

from services import database


def test_import_keeps_route_cities_separated_by_weekday(
    monkeypatch, tmp_path
) -> None:
    url = f"sqlite:///{tmp_path / 'weekday-routes.db'}"
    database.initialize_database(url)
    original_session_scope = database.session_scope
    monkeypatch.setattr(
        database,
        "session_scope",
        lambda: original_session_scope(url),
    )
    routes = {
        "R.40": {
            "name": "ITAÚNA",
            "cities": [
                {
                    "city_original": "ITAÚNA",
                    "municipality_name": "Itaúna",
                    "state": "MG",
                    "ibge_code": "3133808",
                    "needs_review": False,
                },
                {
                    "city_original": "MATEUS LEME",
                    "municipality_name": "Mateus Leme",
                    "state": "MG",
                    "ibge_code": "3140704",
                    "needs_review": False,
                },
                {
                    "city_original": "AZURITA",
                    "municipality_name": None,
                    "state": "MG",
                    "ibge_code": None,
                    "needs_review": True,
                },
            ],
            "weekdays": {
                0: {"name": "ITAÚNA", "cities": ["MATEUS LEME"]},
                1: {"name": "ITAÚNA", "cities": ["AZURITA"]},
            },
        }
    }

    database.import_snapshot(
        routes,
        {0: ["R.40"], 1: ["R.40"], 2: [], 3: [], 4: []},
        date(2026, 8, 17),
    )

    profiles = database.list_route_weekday_profiles()
    assert len(profiles) == 2
    assert [city.city_original for city in profiles[0].cities] == [
        "ITAÚNA",
        "MATEUS LEME",
    ]
    assert [city.city_original for city in profiles[1].cities] == [
        "ITAÚNA",
        "AZURITA",
    ]
