from __future__ import annotations

from datetime import date

from services import database
from utils.city_normalizer import Municipality


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
            "name": "ITAUNA",
            "cities": [
                {
                    "city_original": "ITAUNA",
                    "municipality_name": "Itauna",
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
                0: {"name": "ITAUNA", "cities": ["MATEUS LEME"]},
                1: {"name": "ITAUNA", "cities": ["AZURITA"]},
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
        "ITAUNA",
        "MATEUS LEME",
    ]
    assert [city.city_original for city in profiles[1].cities] == [
        "ITAUNA",
        "AZURITA",
    ]


def test_route_matrix_save_updates_profiles_and_current_week(
    monkeypatch, tmp_path
) -> None:
    url = f"sqlite:///{tmp_path / 'route-matrix.db'}"
    database.initialize_database(url)
    original_session_scope = database.session_scope
    monkeypatch.setattr(
        database,
        "session_scope",
        lambda: original_session_scope(url),
    )
    monkeypatch.setattr(
        database,
        "fetch_state_municipalities",
        lambda state: (
            Municipality("Divinopolis", "MG", "3122306"),
            Municipality("Itauna", "MG", "3133808"),
            Municipality("Mateus Leme", "MG", "3140704"),
        ),
    )

    database.replace_weekday_route_matrix(
        {
            0: [
                "DIVINOPOLIS (R.10)",
                "ITAUNA (R.40)",
                "ITAUNA",
                "!SAO ROQUE DE MINAS CONDICAO",
                "MATEUS LEME",
            ],
            1: [
                "DIVINOPOLIS (R.10)",
                "ITAUNA (R.40)",
                "AZURITA",
            ],
        },
        reference_monday=date(2026, 8, 17),
    )

    schedule = database.load_week_schedule(date(2026, 8, 17))
    assert [route.code for route in schedule[date(2026, 8, 17)]] == [
        "R.10",
        "R.40",
    ]
    assert [route.code for route in schedule[date(2026, 8, 18)]] == [
        "R.10",
        "R.40",
    ]

    monday_r10 = schedule[date(2026, 8, 17)][0]
    monday_r40 = schedule[date(2026, 8, 17)][1]
    tuesday_r40 = schedule[date(2026, 8, 18)][1]
    assert [
        city.city_original
        for profile in monday_r10.weekday_profiles
        if profile.weekday == 0
        for city in profile.cities
    ] == ["DIVINOPOLIS"]
    assert [
        city.city_original
        for profile in monday_r40.weekday_profiles
        if profile.weekday == 0
        for city in profile.cities
    ] == ["ITAUNA", "MATEUS LEME"]
    assert [
        city.city_original
        for profile in tuesday_r40.weekday_profiles
        if profile.weekday == 1
        for city in profile.cities
    ] == ["ITAUNA", "AZURITA"]

    saved_matrix = database.saved_route_matrix_columns()
    assert saved_matrix is not None
    assert "!SAO ROQUE DE MINAS CONDICAO" in saved_matrix[0]

    registry = database.list_city_registry()
    azurita = next(item for item in registry if item["city_original"] == "AZURITA")
    assert azurita["needs_review"]

    database.save_city_registry(
        [
            {
                **azurita,
                "municipality_name": "Mateus Leme",
                "state": "MG",
                "ibge_code": "3140704",
            }
        ]
    )

    updated = database.load_week_schedule(date(2026, 8, 17))[date(2026, 8, 18)][1]
    tuesday_azurita = next(
        city
        for profile in updated.weekday_profiles
        if profile.weekday == 1
        for city in profile.cities
        if city.city_original == "AZURITA"
    )
    assert tuesday_azurita.municipality_name == "Mateus Leme"
    assert tuesday_azurita.ibge_code == "3140704"
    assert not tuesday_azurita.needs_review
