from __future__ import annotations

import logging
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, init_models
from app.schemas import (
    CalculationResponse,
    ChartDataPoint,
    DailySalesEntryWrite,
    DailySalesRangeWrite,
    MessageResponse,
    SalesPlanCreate,
    SalesPlanRead,
    SalesPlanSummary,
    SalesPlanUpdate,
    ShipmentPlanCreate,
    ShipmentPlanRead,
    ShipmentPlanSummary,
    ShipmentPlanUpdate,
    StockoutWarningRead,
    TurnoverRead,
    WarehouseConfigPayload,
    InventoryOverrideWrite,
)
from app.services import (
    create_sales_plan,
    create_shipment_plan,
    delete_inventory_override,
    delete_sales_plan,
    delete_shipment_plan,
    get_chart_data,
    get_sales_plan,
    get_shipment_plan,
    get_stockout_warnings,
    get_turnover_analysis,
    list_sales_plans,
    list_shipment_plans,
    update_sales_plan,
    update_shipment_plan,
    upsert_inventory_override,
    upsert_sales_entries,
    calculate_sales_plan,
)

settings = get_settings()
logger = logging.getLogger(__name__)
app = FastAPI(title="Amazon Replenishment Planning System", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    if settings.AUTO_INIT_MODELS:
        try:
            await init_models()
            logger.info("Database schema initialization completed.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Database schema initialization failed.")
            raise RuntimeError(
                "AUTO_INIT_MODELS=true but database initialization failed. "
                "Check DATABASE_URL or disable AUTO_INIT_MODELS."
            ) from exc


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/shipment-plans", response_model=ShipmentPlanRead, status_code=status.HTTP_201_CREATED)
async def create_shipment_plan_endpoint(
    payload: ShipmentPlanCreate,
    session: AsyncSession = Depends(get_db),
) -> ShipmentPlanRead:
    try:
        return await create_shipment_plan(session, payload)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.get("/api/v1/shipment-plans", response_model=list[ShipmentPlanSummary])
async def list_shipment_plans_endpoint(session: AsyncSession = Depends(get_db)) -> list[ShipmentPlanSummary]:
    return await list_shipment_plans(session)


@app.get("/api/v1/shipment-plans/{plan_id}", response_model=ShipmentPlanRead)
async def get_shipment_plan_endpoint(plan_id: int, session: AsyncSession = Depends(get_db)) -> ShipmentPlanRead:
    try:
        return await get_shipment_plan(session, plan_id)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.put("/api/v1/shipment-plans/{plan_id}", response_model=ShipmentPlanRead)
async def update_shipment_plan_endpoint(
    plan_id: int,
    payload: ShipmentPlanUpdate,
    session: AsyncSession = Depends(get_db),
) -> ShipmentPlanRead:
    try:
        return await update_shipment_plan(session, plan_id, payload)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.delete("/api/v1/shipment-plans/{plan_id}", response_model=MessageResponse)
async def delete_shipment_plan_endpoint(plan_id: int, session: AsyncSession = Depends(get_db)) -> MessageResponse:
    try:
        await delete_shipment_plan(session, plan_id)
        return MessageResponse(message="发货计划已删除")
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.put("/api/v1/shipment-plans/{plan_id}/warehouse-config", response_model=ShipmentPlanRead)
async def update_warehouse_config_endpoint(
    plan_id: int,
    payload: dict[str, WarehouseConfigPayload],
    session: AsyncSession = Depends(get_db),
) -> ShipmentPlanRead:
    try:
        return await update_shipment_plan(session, plan_id, ShipmentPlanUpdate(warehouse_config=payload))
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.post("/api/v1/sales-plans", response_model=SalesPlanRead, status_code=status.HTTP_201_CREATED)
async def create_sales_plan_endpoint(
    payload: SalesPlanCreate,
    session: AsyncSession = Depends(get_db),
) -> SalesPlanRead:
    try:
        return await create_sales_plan(session, payload)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.get("/api/v1/sales-plans", response_model=list[SalesPlanSummary])
async def list_sales_plans_endpoint(session: AsyncSession = Depends(get_db)) -> list[SalesPlanSummary]:
    return await list_sales_plans(session)


@app.get("/api/v1/sales-plans/{plan_id}", response_model=SalesPlanRead)
async def get_sales_plan_endpoint(plan_id: int, session: AsyncSession = Depends(get_db)) -> SalesPlanRead:
    try:
        return await get_sales_plan(session, plan_id)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.put("/api/v1/sales-plans/{plan_id}", response_model=SalesPlanRead)
async def update_sales_plan_endpoint(
    plan_id: int,
    payload: SalesPlanUpdate,
    session: AsyncSession = Depends(get_db),
) -> SalesPlanRead:
    try:
        return await update_sales_plan(session, plan_id, payload)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.delete("/api/v1/sales-plans/{plan_id}", response_model=MessageResponse)
async def delete_sales_plan_endpoint(plan_id: int, session: AsyncSession = Depends(get_db)) -> MessageResponse:
    try:
        await delete_sales_plan(session, plan_id)
        return MessageResponse(message="销售规划已删除")
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.post("/api/v1/sales-plans/{plan_id}/entries", response_model=SalesPlanRead)
async def upsert_sales_entries_endpoint(
    plan_id: int,
    payload: list[DailySalesEntryWrite],
    session: AsyncSession = Depends(get_db),
) -> SalesPlanRead:
    try:
        return await upsert_sales_entries(session, plan_id, {item.date: item.planned_sales for item in payload})
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.put("/api/v1/sales-plans/{plan_id}/entries/{entry_date}", response_model=SalesPlanRead)
async def update_single_sales_entry_endpoint(
    plan_id: int,
    entry_date: date,
    payload: DailySalesEntryWrite,
    session: AsyncSession = Depends(get_db),
) -> SalesPlanRead:
    try:
        return await upsert_sales_entries(session, plan_id, {entry_date: payload.planned_sales})
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.post("/api/v1/sales-plans/{plan_id}/entries/batch", response_model=SalesPlanRead)
async def upsert_sales_range_endpoint(
    plan_id: int,
    payload: DailySalesRangeWrite,
    session: AsyncSession = Depends(get_db),
) -> SalesPlanRead:
    try:
        if payload.start_date > payload.end_date:
            raise ValueError("start_date 不能晚于 end_date")
        return await upsert_sales_entries(
            session,
            plan_id,
            {current_date: payload.daily_sales for current_date in _iter_dates(payload.start_date, payload.end_date)},
        )
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


def _iter_dates(start_date: date, end_date: date) -> list[date]:
    values: list[date] = []
    current = start_date
    while current <= end_date:
        values.append(current)
        current = current.fromordinal(current.toordinal() + 1)
    return values


@app.post("/api/v1/sales-plans/{plan_id}/overrides", response_model=SalesPlanRead)
async def upsert_override_endpoint(
    plan_id: int,
    payload: InventoryOverrideWrite,
    session: AsyncSession = Depends(get_db),
) -> SalesPlanRead:
    try:
        return await upsert_inventory_override(session, plan_id, payload)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.delete("/api/v1/sales-plans/{plan_id}/overrides/{override_date}", response_model=SalesPlanRead)
async def delete_override_endpoint(
    plan_id: int,
    override_date: date,
    session: AsyncSession = Depends(get_db),
) -> SalesPlanRead:
    try:
        return await delete_inventory_override(session, plan_id, override_date)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.get("/api/v1/sales-plans/{plan_id}/calculate", response_model=CalculationResponse)
async def calculate_sales_plan_endpoint(
    plan_id: int,
    session: AsyncSession = Depends(get_db),
) -> CalculationResponse:
    try:
        return await calculate_sales_plan(session, plan_id)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.get("/api/v1/sales-plans/{plan_id}/chart-data", response_model=list[ChartDataPoint])
async def chart_data_endpoint(plan_id: int, session: AsyncSession = Depends(get_db)) -> list[ChartDataPoint]:
    try:
        return await get_chart_data(session, plan_id)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.get("/api/v1/sales-plans/{plan_id}/turnover", response_model=list[TurnoverRead])
async def turnover_endpoint(plan_id: int, session: AsyncSession = Depends(get_db)) -> list[TurnoverRead]:
    try:
        return await get_turnover_analysis(session, plan_id)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)


@app.get("/api/v1/sales-plans/{plan_id}/stockout-warnings", response_model=list[StockoutWarningRead])
async def stockout_warnings_endpoint(
    plan_id: int,
    session: AsyncSession = Depends(get_db),
) -> list[StockoutWarningRead]:
    try:
        return await get_stockout_warnings(session, plan_id)
    except Exception as exc:  # noqa: BLE001
        _raise_service_error(exc)
