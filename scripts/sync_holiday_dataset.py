from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL = (
    "https://api.github.com/repos/joaopbini/feriados-brasil/contents/"
    "dados/feriados/municipal/json/{year}.json"
)


def download_year(year: int, destination: Path) -> int:
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    headers = {
        "Accept": "application/vnd.github.raw+json",
        "User-Agent": "rotas-streamlit-dataset-sync",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    response = session.get(URL.format(year=year), headers=headers, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise TypeError("O arquivo remoto não contém uma lista JSON.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return len(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Atualiza o dataset municipal aberto.")
    parser.add_argument("year", type=int)
    parser.add_argument(
        "--destination", type=Path, default=None, help="Caminho JSON de destino."
    )
    args = parser.parse_args()
    destination = (
        args.destination or Path("data/holidays") / f"municipal_{args.year}.json"
    )
    count = download_year(args.year, destination)
    print(f"{count} feriados gravados em {destination}")


if __name__ == "__main__":
    main()
