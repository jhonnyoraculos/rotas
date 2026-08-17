from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import requests

from services.holidays import (
    FeriadosApiProvider,
    Holiday,
    HolidayProvider,
    HolidayService,
    OpenDatasetHolidayProvider,
    ProviderResult,
)


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


def test_provider_uses_bearer_authorization(monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"feriados": []}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("services.holidays.requests.get", fake_get)

    result = FeriadosApiProvider("token-valido").get_holidays(
        "Itaúna", "MG", 2026, "3133808"
    )

    assert result.complete
    assert captured["headers"] == {"Authorization": "Bearer token-valido"}


def test_provider_stops_after_rejected_key(monkeypatch) -> None:
    calls = 0

    def fake_get(url, **kwargs):
        nonlocal calls
        calls += 1
        response = requests.Response()
        response.status_code = 401
        response.url = url
        raise requests.HTTPError(response=response)

    monkeypatch.setattr("services.holidays.requests.get", fake_get)
    service = HolidayService(
        provider=FeriadosApiProvider("token-invalido"),
        persist=False,
        general_loader=lambda year, state: [],
    )

    service.city_holidays("Itaúna", "MG", 2026, "3133808")
    service.city_holidays("Mateus Leme", "MG", 2026, "3140704")

    assert calls == 1
    assert service.warnings == {
        "A FERIADOS_API_KEY foi recusada. Copie novamente o token do painel do provedor."
    }


def test_open_dataset_provider_filters_by_ibge_code(monkeypatch) -> None:
    holiday = Holiday(
        date(2026, 8, 21),
        "Feriado Municipal de Teste",
        "Municipal",
        "feriados-brasil",
    )
    monkeypatch.setattr(
        "services.holidays._fetch_open_dataset_year",
        lambda year: {"3140704": (holiday,)},
    )

    result = OpenDatasetHolidayProvider().get_holidays(
        "Mateus Leme", "MG", 2026, "3140704"
    )

    assert result.complete
    assert result.holidays == (holiday,)


def test_open_dataset_is_the_default_provider() -> None:
    service = HolidayService(persist=False)

    assert isinstance(service.provider, OpenDatasetHolidayProvider)
