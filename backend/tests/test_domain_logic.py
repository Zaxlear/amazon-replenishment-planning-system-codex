from datetime import date

from app.services import (
    DailyEntryProjection,
    DailyInventoryResult,
    ShipmentUnitProjection,
    calculate_inventory,
    calculate_turnover,
    calculate_unit_quantities,
    next_saturday,
)


def test_calculate_unit_quantities_preserves_total() -> None:
    quantities = calculate_unit_quantities(1001, {"west": 40, "central": 35, "east": 25})
    assert quantities == {"west": 400, "central": 350, "east": 251}
    assert sum(quantities.values()) == 1001


def test_next_saturday_moves_forward() -> None:
    assert next_saturday(date(2026, 4, 15)) == date(2026, 4, 18)
    assert next_saturday(date(2026, 4, 18)) == date(2026, 4, 25)


def test_inventory_calculation_with_arrivals_and_override() -> None:
    entries = [
        DailyEntryProjection(date(2026, 5, 1), 50),
        DailyEntryProjection(date(2026, 5, 2), 50),
        DailyEntryProjection(date(2026, 5, 3), 50),
    ]
    results = calculate_inventory(
        initial_inventory=100,
        daily_entries=entries,
        overrides={date(2026, 5, 2): 120},
        arrivals_map={date(2026, 5, 3): 400},
    )

    assert results[0].opening_stock == 100
    assert results[0].closing_stock == 50
    assert results[1].opening_stock == 120
    assert results[1].closing_stock == 70
    assert results[2].opening_stock == 70
    assert results[2].available_stock == 470
    assert results[2].closing_stock == 420


def test_first_day_zero_inventory_is_not_stockout() -> None:
    results = calculate_inventory(
        initial_inventory=0,
        daily_entries=[DailyEntryProjection(date(2026, 5, 1), 30)],
        overrides={},
        arrivals_map={},
    )
    assert results[0].is_stockout is False
    assert results[0].actual_sales == 0


def test_middle_day_zero_inventory_is_stockout() -> None:
    results = calculate_inventory(
        initial_inventory=20,
        daily_entries=[
            DailyEntryProjection(date(2026, 5, 1), 20),
            DailyEntryProjection(date(2026, 5, 2), 10),
        ],
        overrides={},
        arrivals_map={},
    )
    assert results[1].is_stockout is True
    assert results[1].actual_sales == 0


def test_last_day_exact_consumption_is_not_stockout() -> None:
    results = calculate_inventory(
        initial_inventory=30,
        daily_entries=[
            DailyEntryProjection(date(2026, 5, 1), 10),
            DailyEntryProjection(date(2026, 5, 2), 20),
        ],
        overrides={},
        arrivals_map={},
    )
    assert results[1].is_stockout is False
    assert results[1].closing_stock == 0


def test_turnover_uses_fifo_order() -> None:
    daily_results = [
        DailyInventoryResult(date(2026, 5, 1), 0, 10, 10, 4, 4, 6, False, False),
        DailyInventoryResult(date(2026, 5, 2), 6, 5, 11, 7, 7, 4, False, False),
        DailyInventoryResult(date(2026, 5, 3), 4, 0, 4, 4, 4, 0, False, False),
    ]
    units = [
        ShipmentUnitProjection(1, "5月1日-美西", date(2026, 4, 18), date(2026, 5, 1), 10),
        ShipmentUnitProjection(2, "5月2日-美中", date(2026, 4, 25), date(2026, 5, 2), 5),
    ]

    results = calculate_turnover(units, daily_results)
    west = next(item for item in results if item.unit_id == 1)
    central = next(item for item in results if item.unit_id == 2)

    assert west.fully_sold is True
    assert west.sold_pieces == 10
    assert west.sell_through_date == date(2026, 5, 2)
    assert central.remaining_pieces == 1
    assert central.sold_pieces == 4

