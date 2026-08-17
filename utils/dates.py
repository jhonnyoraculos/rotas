from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAY_NAMES = (
    "SEGUNDA-FEIRA",
    "TERÇA-FEIRA",
    "QUARTA-FEIRA",
    "QUINTA-FEIRA",
    "SEXTA-FEIRA",
)


def today_in_brazil() -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def monday_of(value: date) -> date:
    return value - timedelta(days=value.weekday())


def business_week(monday: date) -> list[date]:
    start = monday_of(monday)
    return [start + timedelta(days=index) for index in range(5)]


def week_title(monday: date) -> str:
    days = business_week(monday)
    return f"Semana de {days[0]:%d/%m/%Y} até {days[-1]:%d/%m/%Y}"
