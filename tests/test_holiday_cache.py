from __future__ import annotations

from datetime import date

from services import database
from services.holidays import (
    CityHolidayMatch,
    HolidayMatch,
    deserialize_week_holiday_results,
    serialize_week_holiday_results,
)


def test_online_holiday_cache_ignores_duplicate_entries(monkeypatch, tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'holidays.db'}"
    database.initialize_database(url)
    original_session_scope = database.session_scope
    monkeypatch.setattr(
        database,
        "session_scope",
        lambda: original_session_scope(url),
    )
    duplicate = {
        "date": date(2026, 6, 1),
        "name": "Feriado Municipal",
        "type": "Municipal",
        "source": "feriados-brasil",
    }

    database.save_online_city_holidays(
        city_key="3122306",
        city="Divinópolis",
        state="MG",
        ibge_code="3122306",
        year=2026,
        entries=[duplicate, duplicate],
        complete=True,
    )

    cached = database.get_cached_city_holidays("3122306", 2026)
    assert len(cached) == 1
    assert cached[0].holiday_name == "Feriado Municipal"


def test_week_holiday_snapshot_persists_by_week_and_signature(
    monkeypatch, tmp_path
) -> None:
    url = f"sqlite:///{tmp_path / 'weekly-holidays.db'}"
    database.initialize_database(url)
    original_session_scope = database.session_scope
    monkeypatch.setattr(
        database,
        "session_scope",
        lambda: original_session_scope(url),
    )
    monday = date(2026, 8, 17)
    results = {"matches": [{"name": "Feriado"}], "city_matches": [], "warnings": []}

    database.save_week_holiday_snapshot(monday, "schedule-v1", results)

    loaded = database.load_week_holiday_snapshot(monday, "schedule-v1")
    assert loaded is not None
    assert loaded["matches"] == results["matches"]
    assert loaded["generated_at"]
    assert database.load_week_holiday_snapshot(monday, "schedule-v2") is None

    database.invalidate_week_holiday_snapshot(monday)
    assert database.load_week_holiday_snapshot(monday, "schedule-v1") is None


def test_week_holiday_result_serialization_roundtrip() -> None:
    route_match = HolidayMatch(
        date=date(2026, 8, 18),
        route_id=40,
        route_code="R.40",
        route_name="Itaúna",
        city="Itaúna",
        name="Feriado Municipal",
        holiday_type="Municipal",
        source="manual",
    )
    city_match = CityHolidayMatch(
        date=date(2026, 8, 18),
        city="Itaúna",
        state="MG",
        name="Feriado Municipal",
        holiday_type="Municipal",
        source="manual",
        routes=("Itaúna (R.40)",),
    )

    payload = serialize_week_holiday_results(
        [route_match], [city_match], {"Aviso de teste"}
    )
    matches, city_matches, warnings = deserialize_week_holiday_results(payload)

    assert matches == [route_match]
    assert city_matches == [city_match]
    assert warnings == {"Aviso de teste"}
