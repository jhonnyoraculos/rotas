from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import holidays as python_holidays
import requests
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from services import database
from utils.city_normalizer import normalize_text


@dataclass(frozen=True)
class Holiday:
    date: date
    name: str
    holiday_type: str
    source: str


@dataclass(frozen=True)
class ProviderResult:
    holidays: tuple[Holiday, ...]
    complete: bool
    message: str | None = None
    stop_requests: bool = False


@dataclass(frozen=True)
class HolidayMatch:
    date: date
    route_id: int
    route_code: str
    route_name: str
    city: str
    name: str
    holiday_type: str
    source: str


def holiday_matches_for_display(
    matches: Iterable[HolidayMatch],
) -> list[HolidayMatch]:
    """Remove repetições por rota dos feriados que atingem todo o país."""
    result: list[HolidayMatch] = []
    national_seen: set[tuple[date, str, str]] = set()
    for match in matches:
        if normalize_text(match.holiday_type) == "NACIONAL":
            key = (
                match.date,
                normalize_text(match.name),
                normalize_text(match.holiday_type),
            )
            if key in national_seen:
                continue
            national_seen.add(key)
        result.append(match)
    return result


class HolidayProvider(ABC):
    @abstractmethod
    def get_holidays(
        self, city: str, state: str, year: int, ibge_code: str | None = None
    ) -> ProviderResult:
        raise NotImplementedError


def _parse_date(value: str) -> date:
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            day, month, year = (int(part) for part in text[:10].split("/"))
            return date(year, month, day)
        except (ValueError, TypeError):
            raise ValueError(f"Data de feriado inválida: {value}") from None


def _api_key() -> str | None:
    value = os.getenv("FERIADOS_API_KEY")
    if value:
        return value
    try:
        secret = st.secrets.get("FERIADOS_API_KEY")
        return str(secret) if secret else None
    except (KeyError, FileNotFoundError, TypeError, StreamlitSecretNotFoundError):
        return None


class FeriadosApiProvider(HolidayProvider):
    """Provedor municipal substituível, consultado por código IBGE."""

    base_url = "https://feriadosapi.com/api/v1/feriados/cidade/{ibge_code}"

    def __init__(self, api_key: str | None = None, timeout: int = 12):
        raw_key = api_key or _api_key()
        if raw_key and raw_key.lower().startswith("bearer "):
            raw_key = raw_key[7:]
        self.api_key = raw_key.strip() if raw_key else None
        self.timeout = timeout

    def get_holidays(
        self, city: str, state: str, year: int, ibge_code: str | None = None
    ) -> ProviderResult:
        if not ibge_code:
            return ProviderResult((), False, "Município sem código IBGE.")
        if not self.api_key:
            return ProviderResult(
                (),
                False,
                "FERIADOS_API_KEY não configurada; cobertura municipal parcial.",
                stop_requests=True,
            )
        try:
            response = requests.get(
                self.base_url.format(ibge_code=ibge_code),
                params={"ano": year},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            items = (
                payload.get("feriados", payload)
                if isinstance(payload, dict)
                else payload
            )
            parsed = []
            for item in items:
                parsed.append(
                    Holiday(
                        date=_parse_date(str(item["data"])),
                        name=str(item["nome"]),
                        holiday_type=str(item.get("tipo", "Municipal")).title(),
                        source="feriadosapi",
                    )
                )
            return ProviderResult(tuple(parsed), True)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            messages = {
                401: "A FERIADOS_API_KEY foi recusada. Copie novamente o token do painel do provedor.",
                403: "A chave não possui acesso aos municípios do interior ou está sem cota.",
                429: "O limite de consultas da Feriados API foi atingido. Tente novamente mais tarde.",
            }
            message = messages.get(
                status,
                f"A Feriados API respondeu com erro HTTP {status or 'desconhecido'}.",
            )
            return ProviderResult((), False, message, stop_requests=True)
        except requests.RequestException:
            return ProviderResult(
                (),
                False,
                "A Feriados API está indisponível. Os dados em cache continuam em uso.",
                stop_requests=True,
            )
        except (ValueError, TypeError, KeyError):
            return ProviderResult(
                (),
                False,
                "A Feriados API retornou uma resposta inválida. Os dados em cache continuam em uso.",
                stop_requests=True,
            )


OPEN_DATASET_URL = (
    "https://raw.githubusercontent.com/joaopbini/feriados-brasil/"
    "master/dados/feriados/municipal/json/{year}.json"
)
OPEN_DATASET_LOCAL = Path(__file__).resolve().parents[1] / "data" / "holidays"


@st.cache_data(ttl=604800, show_spinner=False)
def _fetch_open_dataset_year(year: int) -> dict[str, tuple[Holiday, ...]]:
    local_file = OPEN_DATASET_LOCAL / f"municipal_{year}.json"
    if local_file.exists():
        payload = json.loads(local_file.read_text(encoding="utf-8"))
    else:
        response = requests.get(OPEN_DATASET_URL.format(year=year), timeout=30)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise TypeError("Formato inesperado no dataset de feriados municipais.")

    grouped: dict[str, list[Holiday]] = {}
    seen: set[tuple[str, date, str, str]] = set()
    for item in payload:
        ibge_code = str(item.get("codigo_ibge") or "").strip()
        if not ibge_code:
            continue
        holiday = Holiday(
            date=_parse_date(str(item["data"])),
            name=str(item.get("nome") or "Feriado Municipal"),
            holiday_type=str(item.get("tipo") or "Municipal").title(),
            source="feriados-brasil",
        )
        key = (ibge_code, holiday.date, holiday.name, holiday.holiday_type)
        if key in seen:
            continue
        seen.add(key)
        grouped.setdefault(ibge_code, []).append(holiday)
    return {
        code: tuple(sorted(entries, key=lambda holiday: holiday.date))
        for code, entries in grouped.items()
    }


class OpenDatasetHolidayProvider(HolidayProvider):
    """Dataset aberto por ano, sem conta ou token, indexado por código IBGE."""

    def get_holidays(
        self, city: str, state: str, year: int, ibge_code: str | None = None
    ) -> ProviderResult:
        if not ibge_code:
            return ProviderResult((), False, "Município sem código IBGE.")
        try:
            holidays_by_city = _fetch_open_dataset_year(year)
            return ProviderResult(
                holidays_by_city.get(str(ibge_code), ()),
                complete=True,
            )
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 404:
                message = (
                    f"O dataset gratuito ainda não possui dados municipais de {year}."
                )
            else:
                message = "Não foi possível baixar o dataset gratuito de feriados."
            return ProviderResult((), False, message, stop_requests=True)
        except requests.RequestException:
            return ProviderResult(
                (),
                False,
                "O dataset gratuito está temporariamente indisponível; usando o cache do banco.",
                stop_requests=True,
            )
        except (ValueError, TypeError, KeyError):
            return ProviderResult(
                (),
                False,
                "O dataset gratuito retornou dados inválidos; usando o cache do banco.",
                stop_requests=True,
            )


@st.cache_data(ttl=86400, show_spinner=False)
def get_general_holidays(year: int, state: str = "MG") -> tuple[Holiday, ...]:
    """BrasilAPI para nacionais; python-holidays cobre o fallback e o estado."""
    national: dict[date, Holiday] = {}
    try:
        response = requests.get(
            f"https://brasilapi.com.br/api/feriados/v1/{year}", timeout=10
        )
        response.raise_for_status()
        for item in response.json():
            holiday_date = _parse_date(str(item["date"]))
            national[holiday_date] = Holiday(
                date=holiday_date,
                name=str(item["name"]),
                holiday_type="Nacional",
                source="brasilapi",
            )
    except (requests.RequestException, ValueError, TypeError, KeyError):
        pass

    offline_national = python_holidays.country_holidays("BR", years=[year])
    for holiday_date, name in offline_national.items():
        national.setdefault(
            holiday_date,
            Holiday(holiday_date, str(name), "Nacional", "python-holidays"),
        )

    result = dict(national)
    try:
        state_calendar = python_holidays.country_holidays(
            "BR", subdiv=state.upper(), years=[year]
        )
        for holiday_date, name in state_calendar.items():
            if holiday_date not in national:
                result[holiday_date] = Holiday(
                    holiday_date, str(name), "Estadual", "python-holidays"
                )
    except (NotImplementedError, ValueError):
        pass
    return tuple(sorted(result.values(), key=lambda item: item.date))


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_city_online(
    city: str,
    state: str,
    year: int,
    ibge_code: str | None,
    _api_key_value: str | None,
) -> ProviderResult:
    return FeriadosApiProvider(_api_key_value).get_holidays(
        city, state, year, ibge_code
    )


def clear_holiday_memory_cache() -> None:
    get_general_holidays.clear()
    _fetch_city_online.clear()
    _fetch_open_dataset_year.clear()


class HolidayService:
    def __init__(
        self,
        provider: HolidayProvider | None = None,
        persist: bool = True,
        general_loader: Callable[[int, str], Iterable[Holiday]] = get_general_holidays,
    ):
        self.provider = provider or OpenDatasetHolidayProvider()
        self.persist = persist
        self.general_loader = general_loader
        self.warnings: set[str] = set()
        self._municipal_requests_blocked = False
        self._manual_by_year: dict[int, dict[str, list[Holiday]]] = {}

    def _city_key(self, city: str, ibge_code: str | None) -> str:
        return str(ibge_code) if ibge_code else normalize_text(city)

    def city_holidays(
        self, city: str, state: str, year: int, ibge_code: str | None
    ) -> list[Holiday]:
        city_key = self._city_key(city, ibge_code)
        if not self.persist:
            if self._municipal_requests_blocked:
                return []
            response = self.provider.get_holidays(city, state, year, ibge_code)
            if response.message:
                self.warnings.add(response.message)
            if response.stop_requests:
                self._municipal_requests_blocked = True
            return list(response.holidays)

        if isinstance(self.provider, OpenDatasetHolidayProvider):
            response = self.provider.get_holidays(city, state, year, ibge_code)
            if response.message:
                self.warnings.add(response.message)
            if response.stop_requests:
                self._municipal_requests_blocked = True
            if response.complete:
                combined = {
                    (item.date, item.name, item.holiday_type): item
                    for item in response.holidays
                }
                for item in self._manual_holidays(city_key, year):
                    combined[(item.date, item.name, item.holiday_type)] = item
                return sorted(combined.values(), key=lambda item: item.date)
            if not ibge_code:
                return self._manual_holidays(city_key, year)

        cached = database.get_cached_city_holidays(city_key, year)
        if self._municipal_requests_blocked:
            return [
                Holiday(item.date, item.holiday_name, item.holiday_type, item.source)
                for item in cached
            ]
        if database.holiday_sync_is_fresh(city_key, year):
            return [
                Holiday(item.date, item.holiday_name, item.holiday_type, item.source)
                for item in cached
            ]

        if isinstance(self.provider, FeriadosApiProvider):
            response = _fetch_city_online(
                city, state, year, ibge_code, self.provider.api_key
            )
        else:
            response = self.provider.get_holidays(city, state, year, ibge_code)
        if response.complete:
            database.save_online_city_holidays(
                city_key,
                city,
                state,
                ibge_code,
                year,
                [
                    {
                        "date": item.date,
                        "name": item.name,
                        "type": item.holiday_type,
                        "source": item.source,
                    }
                    for item in response.holidays
                ],
                complete=True,
            )
            cached = database.get_cached_city_holidays(city_key, year)
        elif response.message:
            self.warnings.add(response.message)
        if response.stop_requests:
            self._municipal_requests_blocked = True

        return [
            Holiday(item.date, item.holiday_name, item.holiday_type, item.source)
            for item in cached
        ]

    def _manual_holidays(self, city_key: str, year: int) -> list[Holiday]:
        if year not in self._manual_by_year:
            grouped: dict[str, list[Holiday]] = {}
            for item in database.list_manual_holiday_cache(year):
                grouped.setdefault(item.city_key, []).append(
                    Holiday(
                        item.date,
                        item.holiday_name,
                        item.holiday_type,
                        item.source,
                    )
                )
            self._manual_by_year[year] = grouped
        return self._manual_by_year[year].get(city_key, [])

    def match_week(self, schedule: dict[date, list]) -> list[HolidayMatch]:
        matches: list[HolidayMatch] = []
        seen: set[tuple] = set()
        general_by_year_state: dict[tuple[int, str], list[Holiday]] = {}

        for day, routes in schedule.items():
            state = "MG"
            key = (day.year, state)
            if key not in general_by_year_state:
                general_by_year_state[key] = list(self.general_loader(day.year, state))
            general_today = [
                item for item in general_by_year_state[key] if item.date == day
            ]
            for route in routes:
                for item in general_today:
                    city_label = (
                        "Todas as cidades"
                        if normalize_text(item.holiday_type) == "NACIONAL"
                        else "Minas Gerais"
                    )
                    self._append_match(matches, seen, day, route, city_label, item)

                for route_city in route.cities:
                    city = route_city.holiday_city
                    for item in self.city_holidays(
                        city, route_city.state, day.year, route_city.ibge_code
                    ):
                        if item.date != day:
                            continue
                        if normalize_text(item.holiday_type) in {
                            "NACIONAL",
                            "ESTADUAL",
                        }:
                            continue
                        self._append_match(matches, seen, day, route, city, item)
        return sorted(
            matches,
            key=lambda item: (item.date, item.route_code, item.city, item.name),
        )

    @staticmethod
    def _append_match(
        matches: list[HolidayMatch],
        seen: set[tuple],
        day: date,
        route,
        city: str,
        holiday: Holiday,
    ) -> None:
        key = (day, route.id, normalize_text(city), holiday.name, holiday.holiday_type)
        if key in seen:
            return
        seen.add(key)
        matches.append(
            HolidayMatch(
                date=day,
                route_id=route.id,
                route_code=route.code,
                route_name=route.name,
                city=city,
                name=holiday.name,
                holiday_type=holiday.holiday_type,
                source=holiday.source,
            )
        )
