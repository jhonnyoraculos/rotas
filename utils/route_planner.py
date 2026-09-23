from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Sequence

from utils.city_normalizer import normalize_text
from utils.route_parser import (
    extract_route_code,
    is_ignored_city_line,
    strip_route_code,
)

DAY_NAMES = ("SEG", "TER", "QUA", "QUI", "SEX")


def _clean(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _item_id(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def columns_to_board(columns: dict[int, Sequence[object]]) -> dict:
    """Transforma a matriz persistida em blocos visuais sem alterar seu contrato."""
    days: list[dict] = []
    for weekday, day_name in enumerate(DAY_NAMES):
        items: list[dict] = []
        current: dict | None = None
        note: dict | None = None
        route_occurrences: dict[str, int] = {}

        for row_index, raw_value in enumerate(columns.get(weekday, [])):
            raw = _clean(raw_value)
            visible = raw.lstrip("!* ").strip()
            if not visible:
                continue

            code = extract_route_code(visible)
            if code:
                occurrence = route_occurrences.get(code, 0)
                route_occurrences[code] = occurrence + 1
                current = {
                    "id": f"route-{weekday}-{_item_id(code, occurrence)}",
                    "kind": "route",
                    "code": code,
                    "name": strip_route_code(visible) or code,
                    "cities": [],
                }
                items.append(current)
                note = None
                continue

            normalized = normalize_text(visible)
            if normalized.startswith(("EXTRA BH", "COLETA ")):
                note = {
                    "id": f"note-{weekday}-{_item_id(row_index, visible)}",
                    "kind": "note",
                    "title": visible,
                    "lines": [],
                }
                items.append(note)
                current = None
                continue

            if current is not None:
                if is_ignored_city_line(visible):
                    continue
                current["cities"].append(
                    {
                        "id": f"city-{weekday}-{_item_id(current['id'], row_index, visible)}",
                        "name": visible,
                        "condition": raw.startswith("!") or "CONDICAO" in normalized,
                    }
                )
                continue

            if note is None:
                note = {
                    "id": f"note-{weekday}-{_item_id('loose', row_index)}",
                    "kind": "note",
                    "title": "Observações operacionais",
                    "lines": [],
                }
                items.append(note)
            note["lines"].append(visible)

        days.append({"weekday": weekday, "label": day_name, "items": items})
    return {"days": days}


def board_to_columns(board: dict) -> dict[int, list[str]]:
    """Converte o planner de volta ao mesmo formato consumido pelo banco atual."""
    result: dict[int, list[str]] = {weekday: [] for weekday in range(5)}
    days = board.get("days") if isinstance(board, dict) else None
    if not isinstance(days, list):
        raise ValueError("O planejamento visual recebido é inválido.")  # noqa: TRY004

    seen_weekdays: set[int] = set()
    for day in days:
        if not isinstance(day, dict):
            continue
        try:
            weekday = int(day.get("weekday"))
        except (TypeError, ValueError):
            continue
        if weekday not in result or weekday in seen_weekdays:
            continue
        seen_weekdays.add(weekday)
        seen_codes: set[str] = set()
        for item in day.get("items", []):
            if not isinstance(item, dict):
                continue
            if item.get("kind") == "note":
                title = _clean(item.get("title"))
                if title and title != "Observações operacionais":
                    result[weekday].append(title)
                result[weekday].extend(
                    value
                    for value in (_clean(line) for line in item.get("lines", []))
                    if value
                )
                continue
            if item.get("kind") != "route":
                continue
            code = extract_route_code(item.get("code"))
            name = _clean(item.get("name"))
            if not code or not name:
                raise ValueError("Toda rota precisa ter código e nome.")
            if code in seen_codes:
                raise ValueError(f"A rota {code} aparece mais de uma vez no mesmo dia.")
            seen_codes.add(code)
            result[weekday].append(f"{name} ({code})")
            seen_cities: set[str] = set()
            for city in item.get("cities", []):
                if not isinstance(city, dict):
                    continue
                city_name = _clean(city.get("name")).lstrip("!* ").strip()
                normalized = normalize_text(city_name)
                if not normalized or normalized in seen_cities:
                    continue
                if extract_route_code(city_name):
                    raise ValueError(
                        "O nome da cidade não pode conter um código de rota."
                    )
                seen_cities.add(normalized)
                prefix = "!" if bool(city.get("condition")) else ""
                result[weekday].append(f"{prefix}{city_name}")
    return result


def board_signature(board: dict) -> str:
    columns = board_to_columns(board)
    return json.dumps(columns, ensure_ascii=False, sort_keys=True)


def clone_board(board: dict) -> dict:
    return copy.deepcopy(board)


def find_route(board: dict, route_id: str) -> tuple[dict, dict] | None:
    for day in board.get("days", []):
        for item in day.get("items", []):
            if item.get("kind") == "route" and item.get("id") == route_id:
                return day, item
    return None


def find_city(board: dict, city_id: str) -> tuple[dict, dict, dict] | None:
    for day in board.get("days", []):
        for route in day.get("items", []):
            if route.get("kind") != "route":
                continue
            for city in route.get("cities", []):
                if city.get("id") == city_id:
                    return day, route, city
    return None
