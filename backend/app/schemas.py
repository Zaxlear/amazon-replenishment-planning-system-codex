from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class WarehouseConfigPayload(BaseModel):
    allocation_pct: float = Field(ge=0, le=100)
    transit_days: int = Field(gt=0)


class WarehouseConfigRead(WarehouseConfigPayload):
    region: str
    region_label: str


class ShipmentBatchCreate(BaseModel):
    batch_index: int = Field(ge=1)
    ship_date: date
    batch_quantity: int = Field(gt=0)


class ShipmentUnitRead(ORMModel):
    id: int
    batch_id: int
    batch_index: int
    region: str
    quantity: int
    transit_days: int
    ship_date: date
    arrival_date: date
    status: str
    unit_label: str


class ShipmentBatchRead(ORMModel):
    id: int
    batch_index: int
    ship_date: date
    batch_quantity: int
    units: list[ShipmentUnitRead]


class ShipmentPlanCreate(BaseModel):
    plan_name: str
    sku: str | None = None
    asin: str | None = None
    total_quantity: int = Field(gt=0)
    batch_count: int = Field(gt=0)
    status: str = "draft"
    notes: str | None = None
    warehouse_config: dict[str, WarehouseConfigPayload]
    batches: list[ShipmentBatchCreate]


class ShipmentPlanUpdate(BaseModel):
    plan_name: str | None = None
    sku: str | None = None
    asin: str | None = None
    total_quantity: int | None = Field(default=None, gt=0)
    batch_count: int | None = Field(default=None, gt=0)
    status: str | None = None
    notes: str | None = None
    warehouse_config: dict[str, WarehouseConfigPayload] | None = None
    batches: list[ShipmentBatchCreate] | None = None


class ShipmentPlanSummary(ORMModel):
    id: int
    plan_name: str
    sku: str | None
    asin: str | None
    total_quantity: int
    batch_count: int
    status: str
    created_at: datetime
    updated_at: datetime


class ShipmentPlanRead(ShipmentPlanSummary):
    notes: str | None
    warehouse_config: dict[str, WarehouseConfigRead]
    batches: list[ShipmentBatchRead]
    shipment_units: list[ShipmentUnitRead]


class SalesPlanCreate(BaseModel):
    plan_name: str
    sku: str | None = None
    asin: str | None = None
    start_date: date
    end_date: date
    initial_inventory: int = Field(ge=0, default=0)
    shipment_plan_id: int | None = None


class SalesPlanUpdate(BaseModel):
    plan_name: str | None = None
    sku: str | None = None
    asin: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    initial_inventory: int | None = Field(default=None, ge=0)
    shipment_plan_id: int | None = None


class DailySalesEntryWrite(BaseModel):
    date: date
    planned_sales: int = Field(ge=0)


class DailySalesRangeWrite(BaseModel):
    start_date: date
    end_date: date
    daily_sales: int = Field(ge=0)


class InventoryOverrideWrite(BaseModel):
    override_date: date
    override_value: int = Field(ge=0)
    reason: str | None = None


class DailySalesEntryRead(ORMModel):
    id: int
    entry_date: date
    planned_sales: int
    actual_sales: int | None
    is_stockout: bool
    opening_stock: int | None
    closing_stock: int | None
    arrivals: int


class InventoryOverrideRead(ORMModel):
    id: int
    override_date: date
    override_value: int
    reason: str | None
    created_at: datetime


class SalesPlanSummary(ORMModel):
    id: int
    plan_name: str
    sku: str | None
    asin: str | None
    start_date: date
    end_date: date
    initial_inventory: int
    shipment_plan_id: int | None
    created_at: datetime
    updated_at: datetime


class SalesPlanRead(SalesPlanSummary):
    entries: list[DailySalesEntryRead]
    overrides: list[InventoryOverrideRead]


class ArrivalDetail(BaseModel):
    unit_label: str
    quantity: int


class DailyInventoryResultRead(BaseModel):
    date: date
    opening_stock: int
    arrivals: int
    available_stock: int
    planned_sales: int
    actual_sales: int
    closing_stock: int
    is_stockout: bool
    has_override: bool
    arrival_details: list[ArrivalDetail] = Field(default_factory=list)


class CalculationSummary(BaseModel):
    total_days: int
    total_planned_sales: int
    total_actual_sales: int
    stockout_days: int
    stockout_dates: list[date]
    ending_inventory: int


class CalculationResponse(BaseModel):
    sales_plan_id: int
    calculation_date: datetime
    summary: CalculationSummary
    daily_data: list[DailyInventoryResultRead]


class ChartDataPoint(BaseModel):
    date: date
    opening_stock: int
    planned_sales: int
    actual_sales: int
    arrivals: int
    is_stockout: bool
    has_override: bool


class TurnoverRead(BaseModel):
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


class StockoutWarningRead(BaseModel):
    date: date
    planned_sales: int
    available_stock: int
    shortage: int

