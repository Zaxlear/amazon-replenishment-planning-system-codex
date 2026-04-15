from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ShipmentPlan(Base):
    __tablename__ = "shipment_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100))
    asin: Mapped[str | None] = mapped_column(String(20))
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
    )

    warehouse_configs: Mapped[list[WarehouseConfig]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="WarehouseConfig.region",
    )
    batches: Mapped[list[ShipmentBatch]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="ShipmentBatch.batch_index",
    )
    sales_plans: Mapped[list[SalesPlan]] = relationship(back_populates="shipment_plan")


class WarehouseConfig(Base):
    __tablename__ = "warehouse_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("shipment_plan.id", ondelete="CASCADE"), nullable=False)
    region: Mapped[str] = mapped_column(String(10), nullable=False)
    region_label: Mapped[str] = mapped_column(String(50), nullable=False)
    allocation_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    transit_days: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
    )

    plan: Mapped[ShipmentPlan] = relationship(back_populates="warehouse_configs")


class ShipmentBatch(Base):
    __tablename__ = "shipment_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("shipment_plan.id", ondelete="CASCADE"), nullable=False)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    ship_date: Mapped[date] = mapped_column(Date, nullable=False)
    batch_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    plan: Mapped[ShipmentPlan] = relationship(back_populates="batches")
    units: Mapped[list[ShipmentUnit]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ShipmentUnit.region",
    )


class ShipmentUnit(Base):
    __tablename__ = "shipment_unit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("shipment_batch.id", ondelete="CASCADE"), nullable=False)
    region: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    transit_days: Mapped[int] = mapped_column(Integer, nullable=False)
    ship_date: Mapped[date] = mapped_column(Date, nullable=False)
    arrival_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    batch: Mapped[ShipmentBatch] = relationship(back_populates="units")


Index("idx_shipment_unit_arrival", ShipmentUnit.arrival_date)


class SalesPlan(Base):
    __tablename__ = "sales_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100))
    asin: Mapped[str | None] = mapped_column(String(20))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_inventory: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shipment_plan_id: Mapped[int | None] = mapped_column(ForeignKey("shipment_plan.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
    )

    shipment_plan: Mapped[ShipmentPlan | None] = relationship(back_populates="sales_plans")
    entries: Mapped[list[DailySalesEntry]] = relationship(
        back_populates="sales_plan",
        cascade="all, delete-orphan",
        order_by="DailySalesEntry.entry_date",
    )
    overrides: Mapped[list[InventoryOverride]] = relationship(
        back_populates="sales_plan",
        cascade="all, delete-orphan",
        order_by="InventoryOverride.override_date",
    )


class DailySalesEntry(Base):
    __tablename__ = "daily_sales_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_plan_id: Mapped[int] = mapped_column(ForeignKey("sales_plan.id", ondelete="CASCADE"), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_sales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_sales: Mapped[int | None] = mapped_column(Integer)
    is_stockout: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opening_stock: Mapped[int | None] = mapped_column(Integer)
    closing_stock: Mapped[int | None] = mapped_column(Integer)
    arrivals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    sales_plan: Mapped[SalesPlan] = relationship(back_populates="entries")


Index("idx_daily_sales_date", DailySalesEntry.sales_plan_id, DailySalesEntry.entry_date, unique=True)


class InventoryOverride(Base):
    __tablename__ = "inventory_override"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_plan_id: Mapped[int] = mapped_column(ForeignKey("sales_plan.id", ondelete="CASCADE"), nullable=False)
    override_date: Mapped[date] = mapped_column(Date, nullable=False)
    override_value: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    sales_plan: Mapped[SalesPlan] = relationship(back_populates="overrides")


Index("idx_inventory_override_date", InventoryOverride.sales_plan_id, InventoryOverride.override_date, unique=True)

