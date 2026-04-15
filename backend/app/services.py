from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import DailySalesEntry, InventoryOverride, SalesPlan, ShipmentBatch, ShipmentPlan, ShipmentUnit, WarehouseConfig
from app.schemas import (
    ArrivalDetail,
    CalculationResponse,
    CalculationSummary,
    ChartDataPoint,
    DailyInventoryResultRead,
    InventoryOverrideRead,
    InventoryOverrideWrite,
    SalesPlanCreate,
    SalesPlanRead,
    SalesPlanSummary,
    SalesPlanUpdate,
    ShipmentBatchCreate,
    ShipmentBatchRead,
    ShipmentPlanCreate,
    ShipmentPlanRead,
    ShipmentPlanSummary,
    ShipmentPlanUpdate,
    ShipmentUnitRead,
    StockoutWarningRead,
    TurnoverRead,
    WarehouseConfigPayload,
    WarehouseConfigRead,
)

REGION_LABELS = {
    "west": "美西",
    "central": "美中",
    "east": "美东",
}
REGION_ORDER = ("west", "central", "east")


@dataclass(slots=True)
class DailyEntryProjection:
    entry_date: date
    planned_sales: int


@dataclass(slots=True)
class ShipmentUnitProjection:
    unit_id: int
    unit_label: str
    ship_date: date
    arrival_date: date
    quantity: int


@dataclass(slots=True)
class DailyInventoryResult:
    date: date
    opening_stock: int
    arrivals: int
    available_stock: int
    planned_sales: int
    actual_sales: int
    closing_stock: int
    is_stockout: bool
    has_override: bool


@dataclass(slots=True)
class ShipmentTurnoverResult:
    unit_id: int
    unit_label: str
    ship_date: date
    arrival_date: date
    total_pieces: int
    sold_pieces: int
    remaining_pieces: int
    avg_turnover_days: float | None
    fully_sold: bool
    sell_through_date: date | None


def validate_ship_date(ship_date: date) -> bool:
    return ship_date.weekday() == 5


def next_saturday(from_date: date) -> date:
    days_ahead = 5 - from_date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return from_date + timedelta(days=days_ahead)


def iter_dates(start_date: date, end_date: date) -> Iterable[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def calculate_unit_quantities(batch_quantity: int, allocation: dict[str, float]) -> dict[str, int]:
    raw = {region: batch_quantity * pct / 100 for region, pct in allocation.items()}
    floored = {region: int(value) for region, value in raw.items()}
    remainder = batch_quantity - sum(floored.values())
    decimals = sorted(raw.keys(), key=lambda region: raw[region] - floored[region], reverse=True)
    for index in range(remainder):
        floored[decimals[index]] += 1
    return floored


def check_stockout(opening: int, arrivals: int, planned: int, *, is_first: bool, is_last: bool) -> bool:
    available = opening + arrivals
    if is_first and available == 0:
        return False
    if is_last:
        if available == 0:
            return False
        if planned == available and available > 0:
            return False
    if available == 0:
        return True
    return planned >= available


def build_arrivals_map(shipment_units: Sequence[ShipmentUnitProjection]) -> dict[date, int]:
    arrivals: dict[date, int] = defaultdict(int)
    for unit in shipment_units:
        arrivals[unit.arrival_date] += unit.quantity
    return dict(arrivals)


def calculate_inventory(
    *,
    initial_inventory: int,
    daily_entries: Sequence[DailyEntryProjection],
    overrides: dict[date, int],
    arrivals_map: dict[date, int],
) -> list[DailyInventoryResult]:
    results: list[DailyInventoryResult] = []
    total_days = len(daily_entries)
    for index, entry in enumerate(daily_entries):
        is_first = index == 0
        is_last = index == total_days - 1

        if is_first:
            opening = overrides.get(entry.entry_date, initial_inventory)
        elif entry.entry_date in overrides:
            opening = overrides[entry.entry_date]
        else:
            opening = results[index - 1].closing_stock

        arrivals = arrivals_map.get(entry.entry_date, 0)
        available = opening + arrivals
        actual_sales = min(entry.planned_sales, available)
        stockout = check_stockout(
            opening,
            arrivals,
            entry.planned_sales,
            is_first=is_first,
            is_last=is_last,
        )
        closing = available - actual_sales

        results.append(
            DailyInventoryResult(
                date=entry.entry_date,
                opening_stock=opening,
                arrivals=arrivals,
                available_stock=available,
                planned_sales=entry.planned_sales,
                actual_sales=actual_sales,
                closing_stock=closing,
                is_stockout=stockout,
                has_override=entry.entry_date in overrides,
            )
        )
    return results


def calculate_turnover(
    shipment_units: Sequence[ShipmentUnitProjection],
    daily_results: Sequence[DailyInventoryResult],
) -> list[ShipmentTurnoverResult]:
    fifo_queue: deque[dict[str, object]] = deque()
    tracked: dict[int | str, dict[str, object]] = {}

    if daily_results and daily_results[0].opening_stock > 0:
        fifo_queue.append(
            {
                "unit_id": "initial",
                "unit_label": "初始库存",
                "ship_date": None,
                "arrival_date": daily_results[0].date,
                "remaining": daily_results[0].opening_stock,
                "total": daily_results[0].opening_stock,
                "consumption_log": [],
            }
        )

    ordered_units = sorted(shipment_units, key=lambda unit: (unit.arrival_date, unit.ship_date, unit.unit_id))
    arrival_index = 0

    for result in daily_results:
        while arrival_index < len(ordered_units) and ordered_units[arrival_index].arrival_date == result.date:
            unit = ordered_units[arrival_index]
            tracked[unit.unit_id] = {
                "unit_id": unit.unit_id,
                "unit_label": unit.unit_label,
                "ship_date": unit.ship_date,
                "arrival_date": unit.arrival_date,
                "remaining": unit.quantity,
                "total": unit.quantity,
                "consumption_log": [],
            }
            fifo_queue.append(tracked[unit.unit_id])
            arrival_index += 1

        remaining_sales = result.actual_sales
        while remaining_sales > 0 and fifo_queue:
            front = fifo_queue[0]
            consumable = min(remaining_sales, int(front["remaining"]))
            front["remaining"] = int(front["remaining"]) - consumable
            front["consumption_log"].append((result.date, consumable))
            remaining_sales -= consumable
            if int(front["remaining"]) == 0:
                fifo_queue.popleft()

    turnover_results: list[ShipmentTurnoverResult] = []
    for unit in tracked.values():
        consumption_log: list[tuple[date, int]] = unit["consumption_log"]
        sold_pieces = sum(quantity for _, quantity in consumption_log)
        total_turnover_days = sum((sell_date - unit["ship_date"]).days * quantity for sell_date, quantity in consumption_log)
        avg_turnover = round(total_turnover_days / sold_pieces, 1) if sold_pieces else None
        sell_through_date = consumption_log[-1][0] if consumption_log else None

        turnover_results.append(
            ShipmentTurnoverResult(
                unit_id=int(unit["unit_id"]),
                unit_label=str(unit["unit_label"]),
                ship_date=unit["ship_date"],
                arrival_date=unit["arrival_date"],
                total_pieces=int(unit["total"]),
                sold_pieces=sold_pieces,
                remaining_pieces=int(unit["remaining"]),
                avg_turnover_days=avg_turnover,
                fully_sold=int(unit["remaining"]) == 0,
                sell_through_date=sell_through_date,
            )
        )

    return turnover_results


def _normalize_warehouse_config(config: dict[str, WarehouseConfigPayload]) -> dict[str, WarehouseConfigPayload]:
    missing = set(REGION_ORDER) - set(config)
    extra = set(config) - set(REGION_ORDER)
    if missing or extra:
        raise ValueError(f"warehouse_config 必须且只能包含 {', '.join(REGION_ORDER)}")

    allocation_sum = round(sum(item.allocation_pct for item in config.values()), 2)
    if allocation_sum != 100:
        raise ValueError("三仓 allocation_pct 合计必须等于 100")
    return {region: config[region] for region in REGION_ORDER}


def _build_batch_units(batch: ShipmentBatch, config_map: dict[str, WarehouseConfigPayload]) -> list[ShipmentUnit]:
    allocation_map = {region: payload.allocation_pct for region, payload in config_map.items()}
    quantities = calculate_unit_quantities(batch.batch_quantity, allocation_map)
    units: list[ShipmentUnit] = []
    for region in REGION_ORDER:
        config = config_map[region]
        arrival_date = batch.ship_date + timedelta(days=config.transit_days)
        units.append(
            ShipmentUnit(
                region=region,
                quantity=quantities[region],
                transit_days=config.transit_days,
                ship_date=batch.ship_date,
                arrival_date=arrival_date,
                status="pending",
            )
        )
    return units


def _serialize_unit(unit: ShipmentUnit, batch_index: int) -> ShipmentUnitRead:
    return ShipmentUnitRead(
        id=unit.id,
        batch_id=unit.batch_id,
        batch_index=batch_index,
        region=unit.region,
        quantity=unit.quantity,
        transit_days=unit.transit_days,
        ship_date=unit.ship_date,
        arrival_date=unit.arrival_date,
        status=unit.status,
        unit_label=f"{unit.ship_date.month}月{unit.ship_date.day}日-{REGION_LABELS[unit.region]}",
    )


def serialize_shipment_plan(plan: ShipmentPlan) -> ShipmentPlanRead:
    config_map = {
        config.region: WarehouseConfigRead(
            region=config.region,
            region_label=config.region_label,
            allocation_pct=float(config.allocation_pct),
            transit_days=config.transit_days,
        )
        for config in plan.warehouse_configs
    }
    batches: list[ShipmentBatchRead] = []
    flattened_units: list[ShipmentUnitRead] = []
    for batch in plan.batches:
        units = [_serialize_unit(unit, batch.batch_index) for unit in batch.units]
        flattened_units.extend(units)
        batches.append(
            ShipmentBatchRead(
                id=batch.id,
                batch_index=batch.batch_index,
                ship_date=batch.ship_date,
                batch_quantity=batch.batch_quantity,
                units=units,
            )
        )

    return ShipmentPlanRead(
        id=plan.id,
        plan_name=plan.plan_name,
        sku=plan.sku,
        asin=plan.asin,
        total_quantity=plan.total_quantity,
        batch_count=plan.batch_count,
        status=plan.status,
        notes=plan.notes,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        warehouse_config=config_map,
        batches=batches,
        shipment_units=flattened_units,
    )


def serialize_sales_plan(plan: SalesPlan) -> SalesPlanRead:
    return SalesPlanRead(
        id=plan.id,
        plan_name=plan.plan_name,
        sku=plan.sku,
        asin=plan.asin,
        start_date=plan.start_date,
        end_date=plan.end_date,
        initial_inventory=plan.initial_inventory,
        shipment_plan_id=plan.shipment_plan_id,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        entries=[
            {
                "id": entry.id,
                "entry_date": entry.entry_date,
                "planned_sales": entry.planned_sales,
                "actual_sales": entry.actual_sales,
                "is_stockout": entry.is_stockout,
                "opening_stock": entry.opening_stock,
                "closing_stock": entry.closing_stock,
                "arrivals": entry.arrivals,
            }
            for entry in plan.entries
        ],
        overrides=[
            InventoryOverrideRead(
                id=override.id,
                override_date=override.override_date,
                override_value=override.override_value,
                reason=override.reason,
                created_at=override.created_at,
            )
            for override in plan.overrides
        ],
    )


async def _load_shipment_plan(session: AsyncSession, plan_id: int) -> ShipmentPlan | None:
    query = (
        select(ShipmentPlan)
        .options(
            selectinload(ShipmentPlan.warehouse_configs),
            selectinload(ShipmentPlan.batches).selectinload(ShipmentBatch.units),
        )
        .where(ShipmentPlan.id == plan_id)
    )
    return (await session.execute(query)).scalar_one_or_none()


async def _load_sales_plan(session: AsyncSession, plan_id: int) -> SalesPlan | None:
    query = (
        select(SalesPlan)
        .options(
            selectinload(SalesPlan.entries),
            selectinload(SalesPlan.overrides),
            selectinload(SalesPlan.shipment_plan)
            .selectinload(ShipmentPlan.batches)
            .selectinload(ShipmentBatch.units),
        )
        .where(SalesPlan.id == plan_id)
    )
    return (await session.execute(query)).scalar_one_or_none()


async def list_shipment_plans(session: AsyncSession) -> list[ShipmentPlanSummary]:
    query = select(ShipmentPlan).order_by(ShipmentPlan.created_at.desc())
    plans = (await session.execute(query)).scalars().all()
    return [ShipmentPlanSummary.model_validate(plan) for plan in plans]


async def get_shipment_plan(session: AsyncSession, plan_id: int) -> ShipmentPlanRead:
    plan = await _load_shipment_plan(session, plan_id)
    if plan is None:
        raise LookupError("发货计划不存在")
    return serialize_shipment_plan(plan)


def _coerce_batch_count(batches: Sequence[ShipmentBatchCreate], declared_batch_count: int) -> None:
    if len(batches) != declared_batch_count:
        raise ValueError("batch_count 与 batches 数量不一致")
    if sum(batch.batch_quantity for batch in batches) <= 0:
        raise ValueError("批次总量必须大于 0")


async def create_shipment_plan(session: AsyncSession, payload: ShipmentPlanCreate) -> ShipmentPlanRead:
    config_map = _normalize_warehouse_config(payload.warehouse_config)
    _coerce_batch_count(payload.batches, payload.batch_count)

    if sum(batch.batch_quantity for batch in payload.batches) != payload.total_quantity:
        raise ValueError("批次数量总和必须等于 total_quantity")

    for batch in payload.batches:
        if not validate_ship_date(batch.ship_date):
            raise ValueError(f"{batch.ship_date} 不是周六")

    plan = ShipmentPlan(
        plan_name=payload.plan_name,
        sku=payload.sku,
        asin=payload.asin,
        total_quantity=payload.total_quantity,
        batch_count=payload.batch_count,
        status=payload.status,
        notes=payload.notes,
    )

    for region in REGION_ORDER:
        config = config_map[region]
        plan.warehouse_configs.append(
            WarehouseConfig(
                region=region,
                region_label=REGION_LABELS[region],
                allocation_pct=Decimal(str(config.allocation_pct)),
                transit_days=config.transit_days,
            )
        )

    for batch_payload in payload.batches:
        batch = ShipmentBatch(
            batch_index=batch_payload.batch_index,
            ship_date=batch_payload.ship_date,
            batch_quantity=batch_payload.batch_quantity,
        )
        batch.units.extend(_build_batch_units(batch, config_map))
        plan.batches.append(batch)

    session.add(plan)
    await session.commit()
    fresh_plan = await _load_shipment_plan(session, plan.id)
    return serialize_shipment_plan(fresh_plan)


async def update_shipment_plan(session: AsyncSession, plan_id: int, payload: ShipmentPlanUpdate) -> ShipmentPlanRead:
    plan = await _load_shipment_plan(session, plan_id)
    if plan is None:
        raise LookupError("发货计划不存在")

    if payload.plan_name is not None:
        plan.plan_name = payload.plan_name
    if payload.sku is not None:
        plan.sku = payload.sku
    if payload.asin is not None:
        plan.asin = payload.asin
    if payload.status is not None:
        plan.status = payload.status
    if payload.notes is not None:
        plan.notes = payload.notes

    current_batches = [
        ShipmentBatchCreate(batch_index=batch.batch_index, ship_date=batch.ship_date, batch_quantity=batch.batch_quantity)
        for batch in plan.batches
    ]
    current_config = {
        config.region: WarehouseConfigPayload(
            allocation_pct=float(config.allocation_pct),
            transit_days=config.transit_days,
        )
        for config in plan.warehouse_configs
    }

    rebuild_batches = payload.batches is not None or payload.warehouse_config is not None
    batches_to_use = payload.batches or current_batches
    config_to_use = payload.warehouse_config or current_config

    if rebuild_batches:
        config_map = _normalize_warehouse_config(config_to_use)
        for batch in batches_to_use:
            if not validate_ship_date(batch.ship_date):
                raise ValueError(f"{batch.ship_date} 不是周六")

        plan.total_quantity = sum(batch.batch_quantity for batch in batches_to_use)
        plan.batch_count = len(batches_to_use)
        plan.warehouse_configs.clear()
        plan.batches.clear()
        await session.flush()

        for region in REGION_ORDER:
            config = config_map[region]
            plan.warehouse_configs.append(
                WarehouseConfig(
                    region=region,
                    region_label=REGION_LABELS[region],
                    allocation_pct=Decimal(str(config.allocation_pct)),
                    transit_days=config.transit_days,
                )
            )

        for batch_payload in batches_to_use:
            batch = ShipmentBatch(
                batch_index=batch_payload.batch_index,
                ship_date=batch_payload.ship_date,
                batch_quantity=batch_payload.batch_quantity,
            )
            batch.units.extend(_build_batch_units(batch, config_map))
            plan.batches.append(batch)
    else:
        if payload.total_quantity is not None and payload.total_quantity != plan.total_quantity:
            raise ValueError("更新 total_quantity 时必须同步提供 batches")
        if payload.batch_count is not None and payload.batch_count != plan.batch_count:
            raise ValueError("更新 batch_count 时必须同步提供 batches")

    await session.commit()
    fresh_plan = await _load_shipment_plan(session, plan.id)
    return serialize_shipment_plan(fresh_plan)


async def delete_shipment_plan(session: AsyncSession, plan_id: int) -> None:
    plan = await _load_shipment_plan(session, plan_id)
    if plan is None:
        raise LookupError("发货计划不存在")
    await session.delete(plan)
    await session.commit()


async def list_sales_plans(session: AsyncSession) -> list[SalesPlanSummary]:
    query = select(SalesPlan).order_by(SalesPlan.created_at.desc())
    plans = (await session.execute(query)).scalars().all()
    return [SalesPlanSummary.model_validate(plan) for plan in plans]


async def create_sales_plan(session: AsyncSession, payload: SalesPlanCreate) -> SalesPlanRead:
    if payload.start_date > payload.end_date:
        raise ValueError("start_date 不能晚于 end_date")

    if payload.shipment_plan_id is not None:
        shipment_plan = await session.get(ShipmentPlan, payload.shipment_plan_id)
        if shipment_plan is None:
            raise LookupError("关联的发货计划不存在")

    plan = SalesPlan(
        plan_name=payload.plan_name,
        sku=payload.sku,
        asin=payload.asin,
        start_date=payload.start_date,
        end_date=payload.end_date,
        initial_inventory=payload.initial_inventory,
        shipment_plan_id=payload.shipment_plan_id,
    )
    for entry_date in iter_dates(payload.start_date, payload.end_date):
        plan.entries.append(DailySalesEntry(entry_date=entry_date, planned_sales=0))

    session.add(plan)
    await session.commit()
    fresh_plan = await _load_sales_plan(session, plan.id)
    return serialize_sales_plan(fresh_plan)


async def get_sales_plan(session: AsyncSession, plan_id: int) -> SalesPlanRead:
    plan = await _load_sales_plan(session, plan_id)
    if plan is None:
        raise LookupError("销售规划不存在")
    return serialize_sales_plan(plan)


async def update_sales_plan(session: AsyncSession, plan_id: int, payload: SalesPlanUpdate) -> SalesPlanRead:
    plan = await _load_sales_plan(session, plan_id)
    if plan is None:
        raise LookupError("销售规划不存在")

    if payload.plan_name is not None:
        plan.plan_name = payload.plan_name
    if payload.sku is not None:
        plan.sku = payload.sku
    if payload.asin is not None:
        plan.asin = payload.asin
    if payload.initial_inventory is not None:
        plan.initial_inventory = payload.initial_inventory

    new_start = payload.start_date or plan.start_date
    new_end = payload.end_date or plan.end_date
    if new_start > new_end:
        raise ValueError("start_date 不能晚于 end_date")

    if payload.shipment_plan_id is not None:
        shipment_plan = await session.get(ShipmentPlan, payload.shipment_plan_id)
        if shipment_plan is None:
            raise LookupError("关联的发货计划不存在")
        plan.shipment_plan_id = payload.shipment_plan_id

    if new_start != plan.start_date or new_end != plan.end_date:
        existing = {entry.entry_date: entry for entry in plan.entries}
        plan.start_date = new_start
        plan.end_date = new_end
        plan.entries = [
            existing.get(entry_date, DailySalesEntry(entry_date=entry_date, planned_sales=0))
            for entry_date in iter_dates(new_start, new_end)
        ]

    await session.commit()
    fresh_plan = await _load_sales_plan(session, plan.id)
    return serialize_sales_plan(fresh_plan)


async def delete_sales_plan(session: AsyncSession, plan_id: int) -> None:
    plan = await _load_sales_plan(session, plan_id)
    if plan is None:
        raise LookupError("销售规划不存在")
    await session.delete(plan)
    await session.commit()


async def upsert_sales_entries(session: AsyncSession, sales_plan_id: int, entries: dict[date, int]) -> SalesPlanRead:
    plan = await _load_sales_plan(session, sales_plan_id)
    if plan is None:
        raise LookupError("销售规划不存在")

    existing = {entry.entry_date: entry for entry in plan.entries}
    for entry_date, planned_sales in entries.items():
        if entry_date < plan.start_date or entry_date > plan.end_date:
            raise ValueError(f"{entry_date} 超出规划日期范围")
        if entry_date in existing:
            existing[entry_date].planned_sales = planned_sales
        else:
            plan.entries.append(DailySalesEntry(entry_date=entry_date, planned_sales=planned_sales))

    await session.commit()
    fresh_plan = await _load_sales_plan(session, plan.id)
    return serialize_sales_plan(fresh_plan)


async def upsert_inventory_override(
    session: AsyncSession,
    sales_plan_id: int,
    payload: InventoryOverrideWrite,
) -> SalesPlanRead:
    plan = await _load_sales_plan(session, sales_plan_id)
    if plan is None:
        raise LookupError("销售规划不存在")
    if payload.override_date < plan.start_date or payload.override_date > plan.end_date:
        raise ValueError("override_date 超出规划日期范围")

    existing = next((item for item in plan.overrides if item.override_date == payload.override_date), None)
    if existing is None:
        plan.overrides.append(
            InventoryOverride(
                override_date=payload.override_date,
                override_value=payload.override_value,
                reason=payload.reason,
            )
        )
    else:
        existing.override_value = payload.override_value
        existing.reason = payload.reason

    await session.commit()
    fresh_plan = await _load_sales_plan(session, plan.id)
    return serialize_sales_plan(fresh_plan)


async def delete_inventory_override(session: AsyncSession, sales_plan_id: int, override_date: date) -> SalesPlanRead:
    plan = await _load_sales_plan(session, sales_plan_id)
    if plan is None:
        raise LookupError("销售规划不存在")
    override = next((item for item in plan.overrides if item.override_date == override_date), None)
    if override is None:
        raise LookupError("库存校正不存在")
    await session.delete(override)
    await session.commit()
    fresh_plan = await _load_sales_plan(session, plan.id)
    return serialize_sales_plan(fresh_plan)


def _project_units(plan: SalesPlan) -> list[ShipmentUnitProjection]:
    if plan.shipment_plan is None:
        return []
    projections: list[ShipmentUnitProjection] = []
    for batch in plan.shipment_plan.batches:
        for unit in batch.units:
            projections.append(
                ShipmentUnitProjection(
                    unit_id=unit.id,
                    unit_label=f"{unit.ship_date.month}月{unit.ship_date.day}日-{REGION_LABELS[unit.region]}",
                    ship_date=unit.ship_date,
                    arrival_date=unit.arrival_date,
                    quantity=unit.quantity,
                )
            )
    return projections


async def calculate_sales_plan(session: AsyncSession, sales_plan_id: int) -> CalculationResponse:
    plan = await _load_sales_plan(session, sales_plan_id)
    if plan is None:
        raise LookupError("销售规划不存在")

    ordered_entries = sorted(plan.entries, key=lambda item: item.entry_date)
    projections = [
        DailyEntryProjection(entry_date=entry.entry_date, planned_sales=entry.planned_sales)
        for entry in ordered_entries
    ]
    overrides = {override.override_date: override.override_value for override in plan.overrides}
    units = _project_units(plan)
    arrivals_map = build_arrivals_map(units)
    daily_results = calculate_inventory(
        initial_inventory=plan.initial_inventory,
        daily_entries=projections,
        overrides=overrides,
        arrivals_map=arrivals_map,
    )

    arrival_details_map: dict[date, list[ArrivalDetail]] = defaultdict(list)
    for unit in units:
        arrival_details_map[unit.arrival_date].append(ArrivalDetail(unit_label=unit.unit_label, quantity=unit.quantity))

    entry_by_date = {entry.entry_date: entry for entry in ordered_entries}
    response_rows: list[DailyInventoryResultRead] = []
    for result in daily_results:
        entry = entry_by_date[result.date]
        entry.actual_sales = result.actual_sales
        entry.is_stockout = result.is_stockout
        entry.opening_stock = result.opening_stock
        entry.closing_stock = result.closing_stock
        entry.arrivals = result.arrivals

        response_rows.append(
            DailyInventoryResultRead(
                date=result.date,
                opening_stock=result.opening_stock,
                arrivals=result.arrivals,
                available_stock=result.available_stock,
                planned_sales=result.planned_sales,
                actual_sales=result.actual_sales,
                closing_stock=result.closing_stock,
                is_stockout=result.is_stockout,
                has_override=result.has_override,
                arrival_details=arrival_details_map.get(result.date, []),
            )
        )

    await session.commit()

    summary = CalculationSummary(
        total_days=len(response_rows),
        total_planned_sales=sum(item.planned_sales for item in response_rows),
        total_actual_sales=sum(item.actual_sales for item in response_rows),
        stockout_days=sum(1 for item in response_rows if item.is_stockout),
        stockout_dates=[item.date for item in response_rows if item.is_stockout],
        ending_inventory=response_rows[-1].closing_stock if response_rows else plan.initial_inventory,
    )

    return CalculationResponse(
        sales_plan_id=plan.id,
        calculation_date=datetime.now(timezone.utc),
        summary=summary,
        daily_data=response_rows,
    )


async def get_chart_data(session: AsyncSession, sales_plan_id: int) -> list[ChartDataPoint]:
    calculation = await calculate_sales_plan(session, sales_plan_id)
    return [
        ChartDataPoint(
            date=row.date,
            opening_stock=row.opening_stock,
            planned_sales=row.planned_sales,
            actual_sales=row.actual_sales,
            arrivals=row.arrivals,
            is_stockout=row.is_stockout,
            has_override=row.has_override,
        )
        for row in calculation.daily_data
    ]


async def get_turnover_analysis(session: AsyncSession, sales_plan_id: int) -> list[TurnoverRead]:
    plan = await _load_sales_plan(session, sales_plan_id)
    if plan is None:
        raise LookupError("销售规划不存在")
    calculation = await calculate_sales_plan(session, sales_plan_id)
    units = _project_units(plan)
    turnover_results = calculate_turnover(
        units,
        [
            DailyInventoryResult(
                date=row.date,
                opening_stock=row.opening_stock,
                arrivals=row.arrivals,
                available_stock=row.available_stock,
                planned_sales=row.planned_sales,
                actual_sales=row.actual_sales,
                closing_stock=row.closing_stock,
                is_stockout=row.is_stockout,
                has_override=row.has_override,
            )
            for row in calculation.daily_data
        ],
    )
    return [TurnoverRead(**result.__dict__) for result in turnover_results]


async def get_stockout_warnings(session: AsyncSession, sales_plan_id: int) -> list[StockoutWarningRead]:
    calculation = await calculate_sales_plan(session, sales_plan_id)
    warnings: list[StockoutWarningRead] = []
    for row in calculation.daily_data:
        if not row.is_stockout:
            continue
        warnings.append(
            StockoutWarningRead(
                date=row.date,
                planned_sales=row.planned_sales,
                available_stock=row.available_stock,
                shortage=max(row.planned_sales - row.available_stock, 0),
            )
        )
    return warnings

