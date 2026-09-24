from utils.route_planner import (
    board_signature,
    board_to_columns,
    clone_board,
    columns_to_board,
    deduplicate_board_cities,
)


def test_route_planner_roundtrip_preserves_routes_conditions_and_notes() -> None:
    columns = {
        0: [
            "ITAÚNA (R.40)",
            "ITAÚNA",
            "!SÃO ROQUE DE MINAS CONDIÇÃO",
            "EXTRA BH / REGIÃO",
            "CONTAGEM",
            "CARMO DO CAJURU (R.20)",
            "CARMO DA CACHOEIRA",
            "",
        ],
        1: [],
        2: [],
        3: [],
        4: [],
    }

    board = columns_to_board(columns)
    monday = board["days"][0]

    assert [item["kind"] for item in monday["items"]] == ["route", "note", "route"]
    assert monday["items"][0]["cities"][1]["condition"] is True
    assert board_to_columns(board)[0] == [value for value in columns[0] if value]


def test_route_planner_roundtrip_keeps_weekday_and_city_order() -> None:
    columns = {
        0: ["A (R.10)", "A1", "A2", "B (R.20)", "B1"],
        1: ["C (R.30)", "C1"],
    }

    board = columns_to_board(columns)
    first_route = board["days"][0]["items"].pop(0)
    board["days"][2]["items"].append(first_route)
    first_route["cities"].reverse()

    rebuilt = board_to_columns(board)
    assert rebuilt[0] == ["B (R.20)", "B1"]
    assert rebuilt[2] == ["A (R.10)", "A2", "A1"]


def test_board_signature_detects_removing_one_duplicate_city() -> None:
    board = columns_to_board(
        {0: ["ITAÚNA (R.40)", "ITAÚNA", "AZURITA", "AZURITA", "JUATUBA"]}
    )
    updated = clone_board(board)
    cities = updated["days"][0]["items"][0]["cities"]
    del cities[2]

    assert board_signature(updated) != board_signature(board)


def test_route_planner_rejects_duplicate_city_inside_route() -> None:
    board = columns_to_board(
        {0: ["ITAÚNA (R.40)", "AZURITA", "AZURITA"]}
    )

    try:
        board_to_columns(board)
    except ValueError as error:
        assert "mais de uma vez na rota R.40" in str(error)
    else:
        raise AssertionError("Era esperado erro para cidade duplicada na rota")


def test_route_planner_rejects_same_city_in_two_routes_on_same_day() -> None:
    board = columns_to_board(
        {
            0: [
                "ITAÚNA (R.40)",
                "AZURITA",
                "PARÁ DE MINAS (R.41)",
                "AZURITA",
            ]
        }
    )

    try:
        board_to_columns(board)
    except ValueError as error:
        assert "já está na rota R.40 neste dia" in str(error)
    else:
        raise AssertionError("Era esperado erro para cidade duplicada no dia")


def test_route_planner_allows_same_city_on_different_days() -> None:
    board = columns_to_board(
        {
            0: ["ITAÚNA (R.40)", "AZURITA"],
            1: ["PARÁ DE MINAS (R.41)", "AZURITA"],
        }
    )

    rebuilt = board_to_columns(board)

    assert rebuilt[0][-1] == "AZURITA"
    assert rebuilt[1][-1] == "AZURITA"


def test_deduplicate_board_cities_keeps_first_city_in_the_day() -> None:
    board = columns_to_board(
        {
            0: [
                "ITAÚNA (R.40)",
                "AZURITA",
                "PARÁ DE MINAS (R.41)",
                "AZURITA",
            ]
        }
    )

    cleaned, removed = deduplicate_board_cities(board)

    assert removed == ["AZURITA"]
    assert board_to_columns(cleaned)[0] == [
        "ITAÚNA (R.40)",
        "AZURITA",
        "PARÁ DE MINAS (R.41)",
    ]


def test_route_planner_rejects_duplicate_route_in_same_day() -> None:
    board = columns_to_board({0: ["A (R.10)", "A1"]})
    board["days"][0]["items"].append(
        {
            "id": "duplicate",
            "kind": "route",
            "code": "R.10",
            "name": "A",
            "cities": [],
        }
    )

    try:
        board_to_columns(board)
    except ValueError as error:
        assert "mais de uma vez" in str(error)
    else:
        raise AssertionError("Era esperado erro para rota duplicada no dia")
