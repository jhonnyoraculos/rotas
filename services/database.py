from __future__ import annotations

import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, joinedload, selectinload, sessionmaker
from streamlit.errors import StreamlitSecretNotFoundError

from models import (
    AppSetting,
    Base,
    HolidayCache,
    HolidaySyncStatus,
    Route,
    RouteCity,
    RouteWeekdayCity,
    RouteWeekdayProfile,
    RouteWeekdayTemplate,
    WeeklySchedule,
)
from utils.city_normalizer import (
    Municipality,
    fetch_state_municipalities,
    identify_municipality,
    normalize_text,
)
from utils.dates import business_week
from utils.route_parser import (
    extract_route_code,
    is_ignored_city_line,
    strip_route_code,
)

_SCHEMA_LOCK_KEY = 82726010422026
_ROUTE_MATRIX_KEY = "route_weekday_matrix_columns"


def _streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(name)
        return str(value) if value else None
    except (KeyError, FileNotFoundError, TypeError, StreamlitSecretNotFoundError):
        return None


def database_url() -> str:
    raw = os.getenv("DATABASE_URL") or _streamlit_secret("DATABASE_URL")
    if not raw:
        Path("data").mkdir(parents=True, exist_ok=True)
        return "sqlite:///data/rotas.db"
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+psycopg://", 1)
    if raw.startswith("postgresql://") and "+psycopg" not in raw:
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    target = url or database_url()
    kwargs: dict = {"pool_pre_ping": True}
    if target.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(target, **kwargs)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    factory = sessionmaker(
        bind=get_engine(url), expire_on_commit=False, autoflush=False
    )
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@lru_cache(maxsize=4)
def initialize_database(url: str | None = None) -> None:
    engine = get_engine(url)
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _SCHEMA_LOCK_KEY},
            )
            Base.metadata.create_all(connection)
        return
    Base.metadata.create_all(engine)


def connection_description() -> str:
    url = database_url()
    if url.startswith("sqlite"):
        return "SQLite local (configure DATABASE_URL para usar Neon/PostgreSQL)"
    return "PostgreSQL/Neon"


def count_routes() -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count(Route.id))) or 0)


def database_stats() -> dict[str, int]:
    with session_scope() as session:
        return {
            "rotas": int(session.scalar(select(func.count(Route.id))) or 0),
            "cidades": int(session.scalar(select(func.count(RouteCity.id))) or 0),
            "itens_escala": int(
                session.scalar(select(func.count(WeeklySchedule.id))) or 0
            ),
            "feriados_cache": int(
                session.scalar(select(func.count(HolidayCache.id))) or 0
            ),
        }


def list_routes(active_only: bool = False) -> list[Route]:
    with session_scope() as session:
        statement = (
            select(Route).options(selectinload(Route.cities)).order_by(Route.code)
        )
        if active_only:
            statement = statement.where(Route.active.is_(True))
        return list(session.scalars(statement).unique())


def get_route(route_id: int) -> Route | None:
    with session_scope() as session:
        return session.scalar(
            select(Route)
            .where(Route.id == route_id)
            .options(selectinload(Route.cities))
        )


def count_route_weekday_profiles() -> int:
    with session_scope() as session:
        return int(
            session.scalar(select(func.count(RouteWeekdayProfile.id))) or 0
        )


def list_route_weekday_profiles(
    route_id: int | None = None,
) -> list[RouteWeekdayProfile]:
    with session_scope() as session:
        statement = (
            select(RouteWeekdayProfile)
            .options(
                joinedload(RouteWeekdayProfile.route),
                selectinload(RouteWeekdayProfile.cities),
            )
            .order_by(
                RouteWeekdayProfile.weekday,
                RouteWeekdayProfile.position,
            )
        )
        if route_id is not None:
            statement = statement.where(RouteWeekdayProfile.route_id == route_id)
        return list(session.scalars(statement).unique())


def save_route(
    route_id: int | None, code: str, name: str, active: bool = True
) -> Route:
    from utils.route_parser import extract_route_code

    canonical_code = extract_route_code(code)
    if not canonical_code:
        raise ValueError("Código inválido. Use o formato R.40, por exemplo.")
    clean_name = " ".join(name.split()).strip()
    if not clean_name:
        raise ValueError("Informe o nome da rota.")
    with session_scope() as session:
        route = session.get(Route, route_id) if route_id else None
        if route is None:
            route = Route(
                code=canonical_code,
                name=clean_name,
                normalized_name=normalize_text(clean_name),
                active=active,
            )
            session.add(route)
        else:
            route.code = canonical_code
            route.name = clean_name
            route.normalized_name = normalize_text(clean_name)
            route.active = active
        session.flush()
        return route


def replace_route_cities(route_id: int, cities: Sequence[dict]) -> None:
    with session_scope() as session:
        route = session.get(Route, route_id)
        if route is None:
            raise ValueError("Rota não encontrada.")
        session.execute(delete(RouteCity).where(RouteCity.route_id == route_id))
        seen: set[str] = set()
        for item in cities:
            original = " ".join(str(item.get("city_original") or "").split()).strip()
            if not original:
                continue
            normalized = normalize_text(original)
            if normalized in seen:
                continue
            seen.add(normalized)
            municipality = (
                " ".join(str(item.get("municipality_name") or "").split()).strip()
                or None
            )
            ibge_code = str(item.get("ibge_code") or "").strip() or None
            session.add(
                RouteCity(
                    route_id=route_id,
                    city_original=original,
                    municipality_name=municipality,
                    normalized_city=normalized,
                    state=str(item.get("state") or "MG").strip().upper()[:2],
                    ibge_code=ibge_code,
                    needs_review=not bool(ibge_code and municipality),
                )
            )


def list_unresolved_cities() -> list[RouteCity]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(RouteCity)
                .where(RouteCity.needs_review.is_(True))
                .options(joinedload(RouteCity.route))
                .order_by(Route.code, RouteCity.city_original)
                .join(RouteCity.route)
            )
        )


def resolve_route_city(
    route_city_id: int, municipality_name: str, state: str, ibge_code: str
) -> None:
    with session_scope() as session:
        item = session.get(RouteCity, route_city_id)
        if item is None:
            raise ValueError("Localidade não encontrada.")
        item.municipality_name = municipality_name
        item.state = state.upper()
        item.ibge_code = str(ibge_code)
        item.needs_review = False


def list_city_registry() -> list[dict]:
    cities: dict[str, dict] = {}
    with session_scope() as session:
        route_cities = list(session.scalars(select(RouteCity)))
        weekday_cities = list(session.scalars(select(RouteWeekdayCity)))
    for city in [*route_cities, *weekday_cities]:
        normalized = city.normalized_city or normalize_text(city.city_original)
        if not normalized:
            continue
        existing = cities.get(normalized)
        row = {
            "normalized_city": normalized,
            "city_original": city.city_original,
            "municipality_name": city.municipality_name or "",
            "state": city.state or "MG",
            "ibge_code": city.ibge_code or "",
            "needs_review": city.needs_review,
        }
        if existing is None:
            cities[normalized] = row
            continue
        if (
            (not existing["ibge_code"] and row["ibge_code"])
            or (existing["needs_review"] and not row["needs_review"])
        ):
            cities[normalized] = row
    return sorted(cities.values(), key=lambda item: item["city_original"])


def _update_city_registry_record(
    record: RouteCity | RouteWeekdayCity,
    original: str,
    normalized: str,
    municipality: str | None,
    state: str,
    ibge_code: str | None,
    needs_review: bool,
) -> None:
    record.city_original = original
    record.normalized_city = normalized
    record.municipality_name = municipality
    record.state = state
    record.ibge_code = ibge_code
    record.needs_review = needs_review


def _merge_or_update_city_registry_records(
    session: Session,
    model: type[RouteCity | RouteWeekdayCity],
    old_normalized: str,
    original: str,
    new_normalized: str,
    municipality: str | None,
    state: str,
    ibge_code: str | None,
    needs_review: bool,
) -> None:
    parent_column = model.route_id if model is RouteCity else model.profile_id
    records = list(
        session.scalars(
            select(model)
            .where(model.normalized_city == old_normalized)
            .order_by(model.id)
        )
    )
    for record in records:
        parent_id = record.route_id if model is RouteCity else record.profile_id
        duplicate = session.scalar(
            select(model)
            .where(
                parent_column == parent_id,
                model.normalized_city == new_normalized,
                model.id != record.id,
            )
            .order_by(model.id)
        )
        if duplicate is not None:
            _update_city_registry_record(
                duplicate,
                original,
                new_normalized,
                municipality,
                state,
                ibge_code,
                needs_review,
            )
            if (
                isinstance(record, RouteWeekdayCity)
                and record.position < duplicate.position
            ):
                duplicate.position = record.position
            session.delete(record)
            continue
        _update_city_registry_record(
            record,
            original,
            new_normalized,
            municipality,
            state,
            ibge_code,
            needs_review,
        )


def save_city_registry(rows: Sequence[dict]) -> None:
    with session_scope() as session:
        matrix_label_replacements: dict[str, str] = {}
        for item in rows:
            normalized = str(item.get("normalized_city") or "").strip()
            original = " ".join(str(item.get("city_original") or "").split()).strip()
            if not normalized:
                normalized = normalize_text(original)
            if not normalized:
                continue
            municipality = (
                " ".join(str(item.get("municipality_name") or "").split()).strip()
                or None
            )
            state = str(item.get("state") or "MG").strip().upper()[:2] or "MG"
            ibge_code = str(item.get("ibge_code") or "").strip() or None
            if ibge_code and municipality is None:
                municipality = original or None
            needs_review = not bool(ibge_code and municipality)
            new_normalized = normalize_text(original)
            matrix_label_replacements[normalized] = original
            for model in (RouteCity, RouteWeekdayCity):
                _merge_or_update_city_registry_records(
                    session,
                    model,
                    normalized,
                    original,
                    new_normalized,
                    municipality,
                    state,
                    ibge_code,
                    needs_review,
                )
        _apply_city_registry_labels_to_matrix(session, matrix_label_replacements)


def _route_city_dict(city: RouteCity) -> dict:
    return {
        "city_original": city.city_original,
        "municipality_name": city.municipality_name,
        "state": city.state,
        "ibge_code": city.ibge_code,
        "needs_review": city.needs_review,
    }


def _clean_matrix_cell(value: object) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except (ImportError, TypeError, ValueError):
        pass
    return " ".join(str(value).split()).strip()


def _matrix_cell_value(value: object) -> str:
    text_value = _clean_matrix_cell(value)
    return text_value.lstrip("!* ").strip()


def _save_route_matrix_columns(
    session: Session, columns: dict[int, Sequence[object]]
) -> None:
    payload = {
        str(weekday): [_clean_matrix_cell(value) for value in columns.get(weekday, [])]
        for weekday in range(5)
    }
    setting = session.get(AppSetting, _ROUTE_MATRIX_KEY)
    if setting is None:
        session.add(AppSetting(key=_ROUTE_MATRIX_KEY, value=json.dumps(payload)))
    else:
        setting.value = json.dumps(payload)


def saved_route_matrix_columns() -> dict[int, list[str]] | None:
    with session_scope() as session:
        setting = session.get(AppSetting, _ROUTE_MATRIX_KEY)
        if setting is None or not setting.value:
            return None
        try:
            payload = json.loads(setting.value)
        except (TypeError, json.JSONDecodeError):
            return None
    return {
        weekday: [
            _clean_matrix_cell(value)
            for value in payload.get(str(weekday), [])
        ]
        for weekday in range(5)
    }


def _apply_city_registry_labels_to_matrix(
    session: Session, replacements: dict[str, str]
) -> None:
    if not replacements:
        return
    setting = session.get(AppSetting, _ROUTE_MATRIX_KEY)
    if setting is None or not setting.value:
        return
    try:
        payload = json.loads(setting.value)
    except (TypeError, json.JSONDecodeError):
        return

    changed = False
    for weekday in range(5):
        values = payload.get(str(weekday), [])
        if not isinstance(values, list):
            continue
        updated_values = []
        for value in values:
            text_value = _clean_matrix_cell(value)
            matrix_value = _matrix_cell_value(text_value)
            replacement = replacements.get(normalize_text(matrix_value))
            if replacement:
                prefix = text_value[: len(text_value) - len(text_value.lstrip("!* "))]
                updated_values.append(f"{prefix}{replacement}")
                changed = True
            else:
                updated_values.append(text_value)
        payload[str(weekday)] = updated_values

    if changed:
        setting.value = json.dumps(payload)


def _resolve_matrix_city(
    original: str,
    state: str,
    existing_by_name: dict[str, dict],
    municipalities: tuple[Municipality, ...] | None,
) -> dict:
    existing = existing_by_name.get(normalize_text(original), {})
    if existing:
        return {
            "city_original": original,
            "municipality_name": existing.get("municipality_name"),
            "state": existing.get("state", state),
            "ibge_code": existing.get("ibge_code"),
            "needs_review": existing.get("needs_review", True),
        }
    municipality = identify_municipality(original, state, municipalities)
    return {
        "city_original": original,
        "municipality_name": municipality.name if municipality else None,
        "state": municipality.state if municipality else state,
        "ibge_code": municipality.ibge_code if municipality else None,
        "needs_review": municipality is None,
    }


def _weekday_blocks_from_columns(
    columns: dict[int, Sequence[object]],
) -> tuple[dict[str, dict], dict[int, list[str]]]:
    routes: dict[str, dict] = {}
    schedule: dict[int, list[str]] = {weekday: [] for weekday in range(5)}
    for weekday in range(5):
        current: dict | None = None
        blocks_by_code: dict[str, dict] = {}
        for raw_value in columns.get(weekday, []):
            value = _matrix_cell_value(raw_value)
            if not value:
                continue
            code = extract_route_code(value)
            if code:
                name = strip_route_code(value) or code
                route_item = routes.setdefault(
                    code, {"name": name, "weekdays": {}}
                )
                if route_item["name"] == code and name != code:
                    route_item["name"] = name
                if code not in schedule[weekday]:
                    schedule[weekday].append(code)
                current = route_item["weekdays"].setdefault(
                    weekday, {"name": name, "cities": []}
                )
                current["name"] = current.get("name") or name
                blocks_by_code[code] = current
                continue
            if current is None or is_ignored_city_line(value):
                continue
            normalized = normalize_text(value)
            if normalized.startswith(("EXTRA BH", "COLETA ")):
                current = None
                continue
            if _clean_matrix_cell(raw_value).startswith("!") or "CONDICAO" in normalized:
                continue
            if normalized and all(
                normalize_text(existing) != normalized
                for existing in current["cities"]
            ):
                current["cities"].append(value)
        for code, block in blocks_by_code.items():
            routes[code]["weekdays"][weekday] = block
    return routes, schedule


def _weekday_city_rows(route_item: dict, profile_item: dict) -> list[dict]:
    global_rows = list(route_item.get("cities") or [])
    source_cities = list(profile_item.get("cities") or [])
    normalized_name = normalize_text(profile_item.get("name"))
    route_city = next(
        (
            row
            for row in global_rows
            if normalized_name
            in {
                normalize_text(row.get("city_original")),
                normalize_text(row.get("municipality_name")),
            }
        ),
        None,
    )
    if route_city and all(
        normalize_text(city) != normalize_text(route_city["city_original"])
        for city in source_cities
    ):
        source_cities.insert(0, route_city["city_original"])

    global_by_name: dict[str, dict] = {}
    for row in global_rows:
        for value in (row.get("city_original"), row.get("municipality_name")):
            normalized = normalize_text(value)
            if normalized:
                global_by_name.setdefault(normalized, row)

    result: list[dict] = []
    seen: set[str] = set()
    for city in source_cities:
        original = " ".join(str(city or "").split()).strip()
        normalized = normalize_text(original)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        matched = global_by_name.get(normalized, {})
        result.append(
            {
                "city_original": original,
                "municipality_name": matched.get("municipality_name"),
                "state": matched.get("state", "MG"),
                "ibge_code": matched.get("ibge_code"),
                "needs_review": matched.get("needs_review", True),
            }
        )
    return result


def _replace_weekday_profiles_in_session(
    session: Session,
    routes: dict[str, dict],
    route_by_code: dict[str, Route],
    schedule: dict[int, list[str]],
) -> None:
    session.execute(delete(RouteWeekdayCity))
    session.execute(delete(RouteWeekdayProfile))
    for weekday in range(5):
        scheduled_codes = list(schedule.get(weekday, []))
        detail_codes = [
            code
            for code, item in routes.items()
            if weekday in item.get("weekdays", {})
        ]
        ordered_codes = [*scheduled_codes]
        ordered_codes.extend(code for code in detail_codes if code not in ordered_codes)
        for position, code in enumerate(ordered_codes):
            route = route_by_code.get(code)
            route_item = routes.get(code)
            if route is None or route_item is None:
                continue
            profile_item = route_item.get("weekdays", {}).get(weekday)
            if profile_item is None:
                continue
            profile = RouteWeekdayProfile(
                weekday=weekday,
                route_id=route.id,
                display_name=profile_item.get("name") or route.name,
                position=position,
            )
            session.add(profile)
            session.flush()
            for city_position, city in enumerate(
                _weekday_city_rows(route_item, profile_item)
            ):
                session.add(
                    RouteWeekdayCity(
                        profile_id=profile.id,
                        city_original=city["city_original"],
                        municipality_name=city.get("municipality_name"),
                        normalized_city=normalize_text(city["city_original"]),
                        state=city.get("state", "MG"),
                        ibge_code=city.get("ibge_code"),
                        needs_review=city.get("needs_review", True),
                        position=city_position,
                    )
                )


def replace_route_weekday_profiles(
    routes: dict[str, dict], schedule: dict[int, list[str]]
) -> None:
    with session_scope() as session:
        existing_routes = list(
            session.scalars(select(Route).options(selectinload(Route.cities))).unique()
        )
        route_by_code = {route.code: route for route in existing_routes}
        enriched: dict[str, dict] = {}
        for code, item in routes.items():
            route = route_by_code.get(code)
            if route is None:
                continue
            enriched[code] = {
                **item,
                "cities": [_route_city_dict(city) for city in route.cities],
            }
        _replace_weekday_profiles_in_session(
            session, enriched, route_by_code, schedule
        )


def replace_weekday_route_matrix(
    columns: dict[int, Sequence[object]],
    state: str = "MG",
    reference_monday: date | None = None,
) -> None:
    parsed_routes, schedule = _weekday_blocks_from_columns(columns)
    normalized_state = state.strip().upper()[:2] or "MG"
    try:
        municipalities = fetch_state_municipalities(normalized_state)
    except Exception:  # noqa: BLE001 - a consulta ao IBGE pode estar indisponivel
        municipalities = None

    with session_scope() as session:
        _save_route_matrix_columns(session, columns)
        existing_routes = list(
            session.scalars(select(Route).options(selectinload(Route.cities))).unique()
        )
        route_by_code = {route.code: route for route in existing_routes}

        for code, item in parsed_routes.items():
            route = route_by_code.get(code)
            if route is None:
                route = Route(
                    code=code,
                    name=item["name"],
                    normalized_name=normalize_text(item["name"]),
                    active=True,
                )
                session.add(route)
                session.flush()
                route_by_code[code] = route
            else:
                route.name = item["name"] or route.name
                route.normalized_name = normalize_text(route.name)
                route.active = True

        enriched: dict[str, dict] = {}
        for code, item in parsed_routes.items():
            route = route_by_code.get(code)
            if route is None:
                continue
            existing_by_name: dict[str, dict] = {}
            for city in route.cities:
                city_row = _route_city_dict(city)
                for value in (city.city_original, city.municipality_name):
                    normalized = normalize_text(value)
                    if normalized:
                        existing_by_name.setdefault(normalized, city_row)

            global_rows: list[dict] = []
            global_seen: set[str] = set()
            route_city = _resolve_matrix_city(
                route.name, normalized_state, existing_by_name, municipalities
            )
            if route_city.get("ibge_code"):
                global_rows.append(route_city)
                global_seen.add(normalize_text(route_city["city_original"]))

            weekdays: dict[int, dict] = {}
            for weekday, profile_item in item.get("weekdays", {}).items():
                rows: list[dict] = []
                for original in profile_item.get("cities", []):
                    normalized = normalize_text(original)
                    if not normalized:
                        continue
                    row = _resolve_matrix_city(
                        original, normalized_state, existing_by_name, municipalities
                    )
                    rows.append(row)
                    if normalized not in global_seen:
                        global_seen.add(normalized)
                        global_rows.append(row)
                weekdays[weekday] = {
                    "name": profile_item.get("name") or route.name,
                    "cities": [row["city_original"] for row in rows],
                }
            session.execute(delete(RouteCity).where(RouteCity.route_id == route.id))
            for row in global_rows:
                session.add(
                    RouteCity(
                        route_id=route.id,
                        city_original=row["city_original"],
                        municipality_name=row.get("municipality_name"),
                        normalized_city=normalize_text(row["city_original"]),
                        state=row.get("state", normalized_state),
                        ibge_code=row.get("ibge_code"),
                        needs_review=row.get("needs_review", True),
                    )
                )
            enriched[code] = {
                "name": route.name,
                "cities": global_rows,
                "weekdays": weekdays,
            }

        session.execute(delete(RouteWeekdayTemplate))
        _replace_weekday_profiles_in_session(
            session, enriched, route_by_code, schedule
        )
        for weekday, codes in schedule.items():
            for position, code in enumerate(codes):
                route = route_by_code.get(code)
                if route is not None:
                    session.add(
                        RouteWeekdayTemplate(
                            weekday=weekday,
                            route_id=route.id,
                            position=position,
                        )
                    )

        if reference_monday is not None:
            days = business_week(reference_monday)
            session.execute(delete(WeeklySchedule).where(WeeklySchedule.date.in_(days)))
            for weekday, codes in schedule.items():
                for position, code in enumerate(codes):
                    route = route_by_code.get(code)
                    if route is not None:
                        session.add(
                            WeeklySchedule(
                                date=days[weekday],
                                route_id=route.id,
                                position=position,
                            )
                        )
            key = f"week_materialized:{days[0].isoformat()}"
            setting = session.get(AppSetting, key)
            if setting is None:
                session.add(AppSetting(key=key, value="matrix"))
            else:
                setting.value = "matrix"


def import_snapshot(
    routes: dict[str, dict], schedule: dict[int, list[str]], monday: date
) -> None:
    """Mescla rotas e substitui o modelo semanal e a escala da semana importada."""
    days = business_week(monday)
    with session_scope() as session:
        route_by_code: dict[str, Route] = {}
        for code, item in routes.items():
            route = session.scalar(select(Route).where(Route.code == code))
            if route is None:
                route = Route(
                    code=code,
                    name=item["name"],
                    normalized_name=normalize_text(item["name"]),
                    active=True,
                )
                session.add(route)
                session.flush()
            else:
                route.name = item["name"] or route.name
                route.normalized_name = normalize_text(route.name)
                route.active = True
            route_by_code[code] = route

            if item.get("cities"):
                session.execute(delete(RouteCity).where(RouteCity.route_id == route.id))
                seen: set[str] = set()
                for city in item["cities"]:
                    original = city["city_original"]
                    normalized = normalize_text(original)
                    if not normalized or normalized in seen:
                        continue
                    seen.add(normalized)
                    session.add(
                        RouteCity(
                            route_id=route.id,
                            city_original=original,
                            municipality_name=city.get("municipality_name"),
                            normalized_city=normalized,
                            state=city.get("state", "MG"),
                            ibge_code=city.get("ibge_code"),
                            needs_review=city.get("needs_review", True),
                        )
                    )

        _replace_weekday_profiles_in_session(
            session, routes, route_by_code, schedule
        )
        session.execute(delete(RouteWeekdayTemplate))
        session.execute(delete(WeeklySchedule).where(WeeklySchedule.date.in_(days)))
        for weekday, codes in schedule.items():
            for position, code in enumerate(codes):
                route = route_by_code.get(code)
                if route is None:
                    continue
                session.add(
                    RouteWeekdayTemplate(
                        weekday=weekday, route_id=route.id, position=position
                    )
                )
                session.add(
                    WeeklySchedule(
                        date=days[weekday], route_id=route.id, position=position
                    )
                )
        key = f"week_materialized:{monday.isoformat()}"
        setting = session.get(AppSetting, key)
        if setting is None:
            session.add(AppSetting(key=key, value="excel_import"))
        else:
            setting.value = "excel_import"


def ensure_week_schedule(monday: date) -> None:
    start = business_week(monday)[0]
    key = f"week_materialized:{start.isoformat()}"
    with session_scope() as session:
        if session.get(AppSetting, key) is not None:
            return
        templates = list(
            session.scalars(
                select(RouteWeekdayTemplate).order_by(
                    RouteWeekdayTemplate.weekday, RouteWeekdayTemplate.position
                )
            )
        )
        days = business_week(start)
        for template in templates:
            session.add(
                WeeklySchedule(
                    date=days[template.weekday],
                    route_id=template.route_id,
                    position=template.position,
                )
            )
        session.add(AppSetting(key=key, value="template"))


def load_week_schedule(monday: date) -> dict[date, list[Route]]:
    days = business_week(monday)
    result: dict[date, list[Route]] = {day: [] for day in days}
    with session_scope() as session:
        entries = list(
            session.scalars(
                select(WeeklySchedule)
                .where(WeeklySchedule.date.in_(days))
                .options(
                    joinedload(WeeklySchedule.route).selectinload(Route.cities),
                    joinedload(WeeklySchedule.route)
                    .selectinload(Route.weekday_profiles)
                    .selectinload(RouteWeekdayProfile.cities),
                )
                .order_by(WeeklySchedule.date, WeeklySchedule.position)
            ).unique()
        )
        for entry in entries:
            result[entry.date].append(entry.route)
    return result


def replace_schedule_day(day: date, route_ids: Sequence[int]) -> None:
    with session_scope() as session:
        session.execute(delete(WeeklySchedule).where(WeeklySchedule.date == day))
        seen: set[int] = set()
        for position, route_id in enumerate(route_ids):
            if route_id in seen:
                continue
            seen.add(route_id)
            session.add(WeeklySchedule(date=day, route_id=route_id, position=position))


def get_cached_city_holidays(city_key: str, year: int) -> list[HolidayCache]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(HolidayCache)
                .where(
                    HolidayCache.city_key == city_key,
                    HolidayCache.year == year,
                )
                .order_by(HolidayCache.date)
            )
        )


def holiday_sync_is_fresh(city_key: str, year: int, hours: int = 24) -> bool:
    with session_scope() as session:
        status = session.scalar(
            select(HolidaySyncStatus).where(
                HolidaySyncStatus.city_key == city_key,
                HolidaySyncStatus.year == year,
            )
        )
        if status is None or status.completeness != "complete":
            return False
        updated = status.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - updated < timedelta(hours=hours)


def save_online_city_holidays(
    city_key: str,
    city: str,
    state: str,
    ibge_code: str | None,
    year: int,
    entries: Sequence[dict],
    complete: bool,
    message: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.execute(
            delete(HolidayCache).where(
                HolidayCache.city_key == city_key,
                HolidayCache.year == year,
                HolidayCache.source != "manual",
            )
        )
        manual_keys = set(
            session.execute(
                select(
                    HolidayCache.date,
                    HolidayCache.holiday_name,
                    HolidayCache.holiday_type,
                ).where(
                    HolidayCache.city_key == city_key,
                    HolidayCache.year == year,
                    HolidayCache.source == "manual",
                )
            ).all()
        )
        unique_entries: dict[tuple[date, str, str], dict] = {}
        for item in entries:
            entry_key = (item["date"], item["name"], item["type"])
            if entry_key in manual_keys:
                continue
            unique_entries.setdefault(entry_key, item)

        rows = [
            {
                "city_key": city_key,
                "city": city,
                "state": state,
                "ibge_code": ibge_code,
                "year": year,
                "date": item["date"],
                "holiday_name": item["name"],
                "holiday_type": item["type"],
                "source": item.get("source", "feriadosapi"),
                "updated_at": now,
            }
            for item in unique_entries.values()
        ]
        if rows:
            dialect = session.get_bind().dialect.name
            conflict_columns = [
                "city_key",
                "year",
                "date",
                "holiday_name",
                "holiday_type",
            ]
            if dialect == "postgresql":
                statement = postgresql_insert(HolidayCache).values(rows)
                session.execute(
                    statement.on_conflict_do_nothing(index_elements=conflict_columns)
                )
            elif dialect == "sqlite":
                statement = sqlite_insert(HolidayCache).values(rows)
                session.execute(
                    statement.on_conflict_do_nothing(index_elements=conflict_columns)
                )
            else:
                session.add_all(HolidayCache(**row) for row in rows)
        status = session.scalar(
            select(HolidaySyncStatus).where(
                HolidaySyncStatus.city_key == city_key,
                HolidaySyncStatus.year == year,
            )
        )
        if status is None:
            status = HolidaySyncStatus(city_key=city_key, year=year)
            session.add(status)
        status.completeness = "complete" if complete else "partial"
        status.message = message
        status.updated_at = now


def list_holiday_cache(year: int | None = None) -> list[HolidayCache]:
    with session_scope() as session:
        statement = select(HolidayCache).order_by(
            HolidayCache.date, HolidayCache.city, HolidayCache.holiday_name
        )
        if year is not None:
            statement = statement.where(HolidayCache.year == year)
        return list(session.scalars(statement))


def list_manual_holiday_cache(year: int) -> list[HolidayCache]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(HolidayCache)
                .where(
                    HolidayCache.year == year,
                    HolidayCache.source == "manual",
                )
                .order_by(HolidayCache.date, HolidayCache.city)
            )
        )


def add_manual_holiday(
    city: str,
    state: str,
    ibge_code: str | None,
    holiday_date: date,
    name: str,
    holiday_type: str = "Municipal",
) -> None:
    city_key = str(ibge_code) if ibge_code else normalize_text(city)
    with session_scope() as session:
        existing = session.scalar(
            select(HolidayCache).where(
                HolidayCache.city_key == city_key,
                HolidayCache.date == holiday_date,
                HolidayCache.holiday_name == name,
                HolidayCache.holiday_type == holiday_type,
            )
        )
        if existing is None:
            session.add(
                HolidayCache(
                    city_key=city_key,
                    city=city,
                    state=state,
                    ibge_code=ibge_code,
                    year=holiday_date.year,
                    date=holiday_date,
                    holiday_name=name,
                    holiday_type=holiday_type,
                    source="manual",
                )
            )


def delete_manual_holiday(holiday_id: int) -> None:
    with session_scope() as session:
        session.execute(
            delete(HolidayCache).where(
                HolidayCache.id == holiday_id, HolidayCache.source == "manual"
            )
        )


def invalidate_holiday_sync(
    city_key: str | None = None, year: int | None = None
) -> None:
    with session_scope() as session:
        statement = delete(HolidaySyncStatus)
        if city_key:
            statement = statement.where(HolidaySyncStatus.city_key == city_key)
        if year:
            statement = statement.where(HolidaySyncStatus.year == year)
        session.execute(statement)
