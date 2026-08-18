from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import requests

IBGE_MUNICIPALITIES_URL = (
    "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{state}/municipios"
)


def normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text


@dataclass(frozen=True)
class Municipality:
    name: str
    state: str
    ibge_code: str


@lru_cache(maxsize=27)
def fetch_state_municipalities(state: str = "MG") -> tuple[Municipality, ...]:
    response = requests.get(
        IBGE_MUNICIPALITIES_URL.format(state=state.upper()), timeout=12
    )
    response.raise_for_status()
    result = []
    for item in response.json():
        result.append(
            Municipality(
                name=item["nome"], state=state.upper(), ibge_code=str(item["id"])
            )
        )
    return tuple(result)


def municipality_index(
    state: str = "MG", municipalities: tuple[Municipality, ...] | None = None
) -> dict[str, Municipality]:
    values = (
        municipalities
        if municipalities is not None
        else fetch_state_municipalities(state)
    )
    return {normalize_text(item.name): item for item in values}


def identify_municipality(
    city: str,
    state: str = "MG",
    municipalities: tuple[Municipality, ...] | None = None,
) -> Municipality | None:
    """Faz somente correspondência exata normalizada; distritos não são inferidos."""
    try:
        return municipality_index(state, municipalities).get(normalize_text(city))
    except (requests.RequestException, ValueError, KeyError):
        return None


def resolve_municipality_fields(
    city_original: str,
    municipality_name: str,
    state: str,
    ibge_code: str,
    municipalities: tuple[Municipality, ...] | None = None,
) -> tuple[str, str, str]:
    """Completa nome, UF e código quando há correspondência oficial exata."""
    official_name = str(municipality_name or "").strip()
    normalized_state = str(state or "MG").strip().upper() or "MG"
    current_code = str(ibge_code or "").strip()
    if current_code:
        return official_name, normalized_state, current_code

    candidates = [
        value
        for value in (official_name, str(city_original or "").strip())
        if value
    ]
    if not candidates:
        return official_name, normalized_state, current_code
    seen_candidates: set[str] = set()
    for candidate in candidates:
        normalized_candidate = normalize_text(candidate)
        if normalized_candidate in seen_candidates:
            continue
        seen_candidates.add(normalized_candidate)
        municipality = identify_municipality(
            candidate,
            normalized_state,
            municipalities,
        )
        if municipality is not None:
            return municipality.name, municipality.state, municipality.ibge_code
    return official_name, normalized_state, current_code
