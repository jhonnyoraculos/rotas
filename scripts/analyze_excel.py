from __future__ import annotations

import argparse
from pathlib import Path

from services.excel_importer import analyze_workbook, build_import_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analisa a estrutura da planilha de rotas."
    )
    parser.add_argument("arquivo", type=Path)
    args = parser.parse_args()
    analysis = analyze_workbook(args.arquivo)
    build_import_snapshot(analysis)
    print("\n".join(analysis.summary_lines()))


if __name__ == "__main__":
    main()
