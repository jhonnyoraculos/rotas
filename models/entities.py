from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    cities: Mapped[list[RouteCity]] = relationship(
        back_populates="route", cascade="all, delete-orphan", order_by="RouteCity.id"
    )

    @property
    def label(self) -> str:
        return f"{self.name} ({self.code})"


class RouteCity(Base):
    __tablename__ = "route_cities"
    __table_args__ = (
        UniqueConstraint("route_id", "normalized_city", name="uq_route_city_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_id: Mapped[int] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), index=True
    )
    city_original: Mapped[str] = mapped_column(String(200))
    municipality_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    normalized_city: Mapped[str] = mapped_column(String(200), index=True)
    state: Mapped[str] = mapped_column(String(2), default="MG")
    ibge_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    route: Mapped[Route] = relationship(back_populates="cities")

    @property
    def holiday_city(self) -> str:
        return self.municipality_name or self.city_original


class RouteWeekdayTemplate(Base):
    __tablename__ = "route_weekday_template"
    __table_args__ = (
        UniqueConstraint("weekday", "route_id", name="uq_template_weekday_route"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weekday: Mapped[int] = mapped_column(Integer, index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    route: Mapped[Route] = relationship()


class WeeklySchedule(Base):
    __tablename__ = "weekly_schedule"
    __table_args__ = (
        UniqueConstraint("date", "route_id", name="uq_schedule_date_route"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    route: Mapped[Route] = relationship()


class HolidayCache(Base):
    __tablename__ = "holiday_cache"
    __table_args__ = (
        UniqueConstraint(
            "city_key",
            "year",
            "date",
            "holiday_name",
            "holiday_type",
            name="uq_holiday_cache_entry",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_key: Mapped[str] = mapped_column(String(100), index=True)
    city: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(2), default="MG")
    ibge_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    holiday_name: Mapped[str] = mapped_column(String(250))
    holiday_type: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class HolidaySyncStatus(Base):
    __tablename__ = "holiday_sync_status"
    __table_args__ = (
        UniqueConstraint("city_key", "year", name="uq_holiday_sync_city_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_key: Mapped[str] = mapped_column(String(100), index=True)
    year: Mapped[int] = mapped_column(Integer)
    completeness: Mapped[str] = mapped_column(String(20), default="partial")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
