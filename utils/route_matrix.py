from __future__ import annotations

import math
from collections.abc import Sequence

from utils.city_normalizer import normalize_text
from utils.route_parser import extract_route_code


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _visible_value(value: object) -> str:
    return _cell_text(value).lstrip("!* ").strip()


def _ends_route_block(value: object) -> bool:
    visible = _visible_value(value)
    normalized = normalize_text(visible)
    return bool(extract_route_code(visible)) or normalized.startswith(
        ("EXTRA BH", "COLETA ")
    )


def route_choices_for_weekday(
    columns: dict[int, Sequence[object]], weekday: int
) -> list[tuple[str, str]]:
    """Retorna (codigo, rotulo) das rotas na ordem exibida no dia."""
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in columns.get(weekday, []):
        label = _visible_value(value)
        code = extract_route_code(label)
        if code and code not in seen:
            seen.add(code)
            result.append((code, label))
    return result


def add_cities_to_route_block(
    columns: dict[int, Sequence[object]],
    weekday: int,
    route_code: str,
    city_names: Sequence[str],
    *,
    condition: bool = False,
) -> tuple[dict[int, list[str]], int]:
    """Inclui cidades no bloco da rota sem alterar a ordem das demais rotas."""
    updated = {
        day: [_cell_text(value) for value in columns.get(day, [])]
        for day in range(5)
    }
    values = updated.get(weekday, [])
    route_index = next(
        (
            index
            for index, value in enumerate(values)
            if extract_route_code(_visible_value(value)) == route_code
        ),
        None,
    )
    if route_index is None:
        raise ValueError("A rota selecionada não foi encontrada nesse dia.")

    next_block_index = next(
        (
            index
            for index in range(route_index + 1, len(values))
            if _ends_route_block(values[index])
        ),
        None,
    )
    if next_block_index is None:
        non_empty_indexes = [
            index
            for index in range(route_index + 1, len(values))
            if _cell_text(values[index])
        ]
        insertion_index = (
            max(non_empty_indexes) + 1 if non_empty_indexes else route_index + 1
        )
        block_end = insertion_index
    else:
        insertion_index = next_block_index
        block_end = next_block_index

    existing = {
        normalize_text(_visible_value(value))
        for value in values[route_index + 1 : block_end]
        if _visible_value(value)
    }
    additions: list[str] = []
    for value in city_names:
        typed_value = " ".join(str(value or "").split()).strip()
        is_condition = condition or typed_value.startswith("!")
        city = typed_value.lstrip("!* ").strip()
        normalized = normalize_text(city)
        if not normalized or normalized in existing:
            continue
        if extract_route_code(city):
            raise ValueError("O nome da cidade não pode conter um código de rota.")
        existing.add(normalized)
        additions.append(f"!{city}" if is_condition else city)

    if not additions:
        return updated, 0

    original_length = len(values)
    values[insertion_index:insertion_index] = additions
    while len(values) > original_length and values and not _cell_text(values[-1]):
        values.pop()
    updated[weekday] = values

    maximum = max((len(day_values) for day_values in updated.values()), default=0)
    for day_values in updated.values():
        day_values.extend([""] * (maximum - len(day_values)))
    return updated, len(additions)
