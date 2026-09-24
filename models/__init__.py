"""Modelos persistentes da aplicação."""

from models.entities import (
    AppSetting,
    Base,
    CityRegistry,
    HolidayCache,
    HolidaySyncStatus,
    Route,
    RouteCity,
    RouteWeekdayCity,
    RouteWeekdayProfile,
    RouteWeekdayTemplate,
    WeeklySchedule,
)

__all__ = [
    "AppSetting",
    "Base",
    "CityRegistry",
    "HolidayCache",
    "HolidaySyncStatus",
    "Route",
    "RouteCity",
    "RouteWeekdayCity",
    "RouteWeekdayProfile",
    "RouteWeekdayTemplate",
    "WeeklySchedule",
]
