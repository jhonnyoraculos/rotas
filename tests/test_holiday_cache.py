from __future__ import annotations

from datetime import date

from services import database


def test_online_holiday_cache_ignores_duplicate_entries(
    monkeypatch, tmp_path
) -> None:
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
