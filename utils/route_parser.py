from __future__ import annotations

import re
from dataclasses import dataclass, field

from utils.city_normalizer import normalize_text

ROUTE_RE = re.compile(r"\(?\s*R\s*\.\s*(\d+)\s*\)?", re.IGNORECASE)


@dataclass
class ParsedRoute:
    code: str
    name: str
    original: str
    cities: list[str] = field(default_factory=list)


def extract_route_code(value: object) -> str | None:
    if value is None:
        return None
    match = ROUTE_RE.search(str(value))
    return f"R.{int(match.group(1))}" if match else None


def strip_route_code(value: object) -> str:
    if value is None:
        return ""
    text = ROUTE_RE.sub("", str(value))
    return re.sub(r"\s+", " ", text).strip(" -–—()\t\n")


def route_label(name: str, code: str) -> str:
    return f"{name.strip()} ({code})"


def is_ignored_city_line(value: str) -> bool:
    normalized = normalize_text(value)
    ignored = {
        "",
        "CIDADE",
        "CIDADES",
        "MUNICIPIO",
        "MUNICIPIOS",
        "ROTA",
        "ROTAS",
        "CIDADES X ROTAS ATUALIZADAS",
        "CIDADE X ROTA",
    }
    return normalized in ignored
