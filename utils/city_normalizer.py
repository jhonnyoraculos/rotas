from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
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


_OPERATIONAL_WORDS = {
    "CIDADE",
    "MUNICIPIO",
    "MUNICIPAL",
    "LOCALIDADE",
    "ROTA",
    "COLETA",
    "ENTREGA",
    "CARGA",
    "CONDICAO",
    "CONDICOES",
    "ESPECIAL",
}


def municipality_match_key(value: object, state: str = "MG") -> str:
    """Remove marcações operacionais sem alterar o nome mostrado ao usuário."""
    normalized = normalize_text(value)
    normalized = re.sub(r"\bR\s*\.\s*\d+\b", " ", normalized)
    normalized = re.sub(r"[^A-Z0-9]+", " ", normalized)
    tokens = [
        token
        for token in normalized.split()
        if token not in _OPERATIONAL_WORDS and not token.isdigit()
    ]
    normalized_state = normalize_text(state)
    if tokens and tokens[-1] == normalized_state:
        tokens.pop()
    return " ".join(tokens)


def _single_municipality(candidates: list[Municipality]) -> Municipality | None:
    unique = {item.ibge_code: item for item in candidates}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _fuzzy_municipality(
    candidate: str, municipalities: tuple[Municipality, ...]
) -> Municipality | None:
    """Aceita apenas um nome próximo claramente melhor que os demais."""
    if len(candidate) < 5:
        return None
    scored = sorted(
        (
            (
                SequenceMatcher(
                    None, candidate, municipality_match_key(item.name, item.state)
                ).ratio(),
                item,
            )
            for item in municipalities
        ),
        key=lambda value: value[0],
        reverse=True,
    )
    if not scored:
        return None
    best_score, best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.88 and best_score - second_score >= 0.035:
        return best
    return None


def identify_municipality(
    city: str,
    state: str = "MG",
    municipalities: tuple[Municipality, ...] | None = None,
) -> Municipality | None:
    """Identifica município por nome limpo, trecho único ou aproximação segura."""
    try:
        values = (
            municipalities
            if municipalities is not None
            else fetch_state_municipalities(state)
        )
        exact = municipality_index(state, values)
        raw_key = normalize_text(city)
        clean_key = municipality_match_key(city, state)
        for key in (raw_key, clean_key):
            if key in exact:
                return exact[key]

        # Ex.: "* SÃO SEBASTIÃO DO OESTE - CONDIÇÃO" ou
        # "CIDADE: ITAÚNA / MG". Só aceita se houver um único município no texto.
        padded = f" {clean_key} "
        contained = [
            municipality
            for official_key, municipality in exact.items()
            if official_key and f" {official_key} " in padded
        ]
        matched = _single_municipality(contained)
        if matched is not None:
            return matched
        return _fuzzy_municipality(clean_key, values)
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
