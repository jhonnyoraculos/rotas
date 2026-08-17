from pathlib import Path

from services.excel_importer import auto_import_if_available


def test_auto_import_checks_data_folder_then_project_root(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    root_file = tmp_path / "ROTAS_2026.xlsx"
    root_file.write_bytes(b"planilha")
    imported: list[Path] = []

    monkeypatch.setattr("services.database.count_routes", lambda: 0)
    monkeypatch.setattr(
        "services.excel_importer.import_workbook",
        lambda candidate: imported.append(Path(candidate)) or "resultado",
    )

    assert auto_import_if_available() == "resultado"
    assert imported == [Path("ROTAS_2026.xlsx")]
