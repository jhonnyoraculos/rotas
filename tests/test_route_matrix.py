import pytest

from utils.route_matrix import add_cities_to_route_block, route_choices_for_weekday


def sample_columns() -> dict[int, list[str]]:
    return {
        0: [
            "DIVINOPOLIS (R.10)",
            "DIVINOPOLIS",
            "CARMO DO CAJURU (R.20)",
            "CARMO DO CAJURU",
            "",
            "",
        ],
        1: ["DIVINOPOLIS (R.10)", "DIVINOPOLIS", "", "", "", ""],
        2: ["", "", "", "", "", ""],
        3: ["", "", "", "", "", ""],
        4: ["", "", "", "", "", ""],
    }


def test_route_choices_preserve_matrix_order() -> None:
    assert route_choices_for_weekday(sample_columns(), 0) == [
        ("R.10", "DIVINOPOLIS (R.10)"),
        ("R.20", "CARMO DO CAJURU (R.20)"),
    ]


def test_add_multiple_cities_before_next_route_and_skip_duplicate() -> None:
    updated, added = add_cities_to_route_block(
        sample_columns(),
        0,
        "R.10",
        ["Divinópolis", "NOVA CIDADE", "OUTRA CIDADE"],
    )

    assert added == 2
    assert updated[0][:5] == [
        "DIVINOPOLIS (R.10)",
        "DIVINOPOLIS",
        "NOVA CIDADE",
        "OUTRA CIDADE",
        "CARMO DO CAJURU (R.20)",
    ]


def test_add_condition_city_to_last_route_uses_available_blank_row() -> None:
    updated, added = add_cities_to_route_block(
        sample_columns(), 0, "R.20", ["CIDADE ESPECIAL"], condition=True
    )

    assert added == 1
    assert updated[0][4] == "!CIDADE ESPECIAL"
    assert len(updated[0]) == 6


def test_add_city_before_extra_region_separator() -> None:
    columns = sample_columns()
    columns[0] = [
        "LAGOA DA PRATA (R.80)",
        "ARCOS",
        "EXTRA BH / REGIÃO",
        "PITANGUI (R.42)",
        "PITANGUI",
        "",
    ]

    updated, added = add_cities_to_route_block(
        columns, 0, "R.80", ["FORMIGA"]
    )

    assert added == 1
    assert updated[0][2:4] == ["FORMIGA", "EXTRA BH / REGIÃO"]


def test_add_city_rejects_route_code_in_name() -> None:
    with pytest.raises(ValueError, match="código de rota"):
        add_cities_to_route_block(sample_columns(), 0, "R.10", ["TESTE R.999"])
