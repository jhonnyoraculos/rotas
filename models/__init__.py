"""Modelos persistentes da aplicação."""

from models.entities import (
    AppSetting,
    Base,
    HolidayCache,
    HolidaySyncStatus,
    Route,
    RouteCity,
    RouteWeekdayTemplate,
    WeeklySchedule,
)

__all__ = [
    "AppSetting",
    "Base",
    "HolidayCache",
    "HolidaySyncStatus",
    "Route",
    "RouteCity",
    "RouteWeekdayTemplate",
    "WeeklySchedule",
]
