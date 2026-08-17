from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from services.holidays import Holiday, HolidayProvider, HolidayService, ProviderResult


class FakeProvider(HolidayProvider):
    def get_holidays(self, city, state, year, ibge_code=None):
        if city == "Mateus Leme":
            return ProviderResult(
                (
                    Holiday(
                        date(2026, 8, 21),
                        "Feriado Municipal de Teste",
                        "Municipal",
                        "teste",
                    ),
                ),
                True,
            )
        return ProviderResult((), True)


def test_holiday_in_any_city_marks_the_route() -> None:
    route = SimpleNamespace(
        id=40,
        code="R.40",
        name="Itaúna",
        cities=[
            SimpleNamespace(holiday_city="Itaúna", state="MG", ibge_code="3133808"),
            SimpleNamespace(
                holiday_city="Mateus Leme", state="MG", ibge_code="3140704"
            ),
            SimpleNamespace(holiday_city="Juatuba", state="MG", ibge_code="3136652"),
        ],
    )
    service = HolidayService(
        provider=FakeProvider(), persist=False, general_loader=lambda year, state: []
    )

    matches = service.match_week({date(2026, 8, 21): [route]})

    assert len(matches) == 1
    assert matches[0].route_code == "R.40"
    assert matches[0].city == "Mateus Leme"
    assert matches[0].date == date(2026, 8, 21)
