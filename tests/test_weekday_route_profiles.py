from __future__ import annotations

from datetime import date

from sqlalchemy import select

from models import Route, RouteCity, RouteWeekdayCity, RouteWeekdayProfile
from services import database
from utils.city_normalizer import Municipality, resolve_municipality_fields


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
            Municipality("Araxa", "MG", "3104007"),
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

    database.save_city_registry(
        [
            {
                **azurita,
                "city_original": "AZURITA CORRIGIDA",
                "municipality_name": "Mateus Leme",
                "state": "MG",
                "ibge_code": "3140704",
            }
        ]
    )

    renamed = database.load_week_schedule(date(2026, 8, 17))[date(2026, 8, 18)][1]
    assert any(
        city.city_original == "AZURITA CORRIGIDA"
        for profile in renamed.weekday_profiles
        if profile.weekday == 1
        for city in profile.cities
    )
    saved_after_rename = database.saved_route_matrix_columns()
    assert saved_after_rename is not None
    assert "AZURITA CORRIGIDA" in saved_after_rename[1]

    assert resolve_municipality_fields(
        "ARAXA- CONDICOES",
        "Araxa",
        "MG",
        "",
        (Municipality("Araxa", "MG", "3104007"),),
    ) == ("Araxa", "MG", "3104007")


def test_city_registry_merge_prevents_duplicate_city_keys(
    monkeypatch, tmp_path
) -> None:
    url = f"sqlite:///{tmp_path / 'merge-city-registry.db'}"
    database.initialize_database(url)
    original_session_scope = database.session_scope
    monkeypatch.setattr(
        database,
        "session_scope",
        lambda: original_session_scope(url),
    )

    database.import_snapshot(
        {
            "R.40": {
                "name": "ITAUNA",
                "cities": [
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
                    0: {
                        "name": "ITAUNA",
                        "cities": ["MATEUS LEME", "AZURITA"],
                    },
                },
            }
        },
        {0: ["R.40"], 1: [], 2: [], 3: [], 4: []},
        date(2026, 8, 17),
    )

    registry = database.list_city_registry()
    azurita = next(item for item in registry if item["city_original"] == "AZURITA")

    database.save_city_registry(
        [
            {
                **azurita,
                "city_original": "MATEUS LEME",
                "municipality_name": "Mateus Leme",
                "state": "MG",
                "ibge_code": "3140704",
            }
        ]
    )

    schedule = database.load_week_schedule(date(2026, 8, 17))
    monday_route = schedule[date(2026, 8, 17)][0]
    monday_cities = [
        city.city_original
        for profile in monday_route.weekday_profiles
        if profile.weekday == 0
        for city in profile.cities
    ]
    assert monday_cities.count("MATEUS LEME") == 1


def test_city_registry_save_merges_accented_legacy_duplicates(
    monkeypatch, tmp_path
) -> None:
    url = f"sqlite:///{tmp_path / 'accented-duplicates.db'}"
    database.initialize_database(url)
    original_session_scope = database.session_scope
    monkeypatch.setattr(
        database,
        "session_scope",
        lambda: original_session_scope(url),
    )

    database.import_snapshot(
        {
            "R.50": {
                "name": "SAO JOSE DA LAPA",
                "cities": [
                    {
                        "city_original": "SAO JOSE DA LAPA",
                        "municipality_name": None,
                        "state": "MG",
                        "ibge_code": None,
                        "needs_review": True,
                    },
                ],
                "weekdays": {
                    0: {
                        "name": "SAO JOSE DA LAPA",
                        "cities": ["SAO JOSE DA LAPA"],
                    },
                },
            }
        },
        {0: ["R.50"], 1: [], 2: [], 3: [], 4: []},
        date(2026, 8, 17),
    )

    with database.session_scope() as session:
        route = session.scalar(select(Route).where(Route.code == "R.50"))
        assert route is not None
        profile = session.scalar(
            select(RouteWeekdayProfile).where(RouteWeekdayProfile.route_id == route.id)
        )
        assert profile is not None
        session.add(
            RouteCity(
                route_id=route.id,
                city_original="SÃO JOSÉ DA LAPA",
                municipality_name=None,
                normalized_city="SÃO JOSÉ DA LAPA",
                state="MG",
                ibge_code=None,
                needs_review=True,
            )
        )
        session.add(
            RouteWeekdayCity(
                profile_id=profile.id,
                city_original="SÃO JOSÉ DA LAPA",
                municipality_name=None,
                normalized_city="SÃO JOSÉ DA LAPA",
                state="MG",
                ibge_code=None,
                needs_review=True,
                position=1,
            )
        )

    database.save_city_registry(
        [
            {
                "normalized_city": "SAO JOSE DA LAPA",
                "city_original": "SÃO JOSE DA LAPA",
                "municipality_name": "São José da Lapa",
                "state": "MG",
                "ibge_code": "3162955",
            },
            {
                "normalized_city": "SÃO JOSÉ DA LAPA",
                "city_original": "SÃO JOSÉ DA LAPA",
                "municipality_name": "São José da Lapa",
                "state": "MG",
                "ibge_code": "3162955",
            },
        ]
    )

    registry = database.list_city_registry()
    sao_jose_rows = [
        item for item in registry if item["ibge_code"] == "3162955"
    ]
    assert len(sao_jose_rows) == 1

    with database.session_scope() as session:
        route = session.scalar(select(Route).where(Route.code == "R.50"))
        assert route is not None
        route_rows = list(
            session.scalars(select(RouteCity).where(RouteCity.route_id == route.id))
        )
        assert len(route_rows) == 1
