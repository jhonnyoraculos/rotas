from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, delete, func, select
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
    RouteWeekdayTemplate,
    WeeklySchedule,
)
from utils.city_normalizer import normalize_text
from utils.dates import business_week


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


def initialize_database(url: str | None = None) -> None:
    Base.metadata.create_all(get_engine(url))


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
                .options(joinedload(WeeklySchedule.route).selectinload(Route.cities))
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
