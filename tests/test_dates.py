from datetime import date

from utils.dates import business_week, monday_of


def test_current_week_always_starts_on_monday() -> None:
    assert monday_of(date(2026, 8, 18)) == date(2026, 8, 17)
    assert business_week(date(2026, 8, 18))[-1] == date(2026, 8, 21)
