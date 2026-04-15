import dayjs, { Dayjs } from "dayjs";

import type {
  BatchDraft,
  DailySalesDraft,
  InventoryDayView,
  Region,
  ShipmentDraft,
  ShipmentUnitPreview,
  TurnoverCard,
  WarehouseConfigState
} from "./types";

export const REGION_LABELS: Record<Region, string> = {
  west: "美西",
  central: "美中",
  east: "美东"
};

export const defaultWarehouseConfig: Record<Region, WarehouseConfigState> = {
  west: { allocation_pct: 40, transit_days: 15 },
  central: { allocation_pct: 35, transit_days: 18 },
  east: { allocation_pct: 25, transit_days: 22 }
};

export function nextSaturday(from = dayjs()): Dayjs {
  const target = from.day() <= 6 ? from.day(6) : from.add(1, "week").day(6);
  return target.isAfter(from, "day") ? target : target.add(1, "week");
}

export function nthUpcomingSaturday(offsetWeeks: number): Dayjs {
  return nextSaturday(dayjs()).add(offsetWeeks, "week");
}

export function calculateUnitQuantities(
  batchQuantity: number,
  allocation: Record<Region, WarehouseConfigState>
): Record<Region, number> {
  const raw = {
    west: (batchQuantity * allocation.west.allocation_pct) / 100,
    central: (batchQuantity * allocation.central.allocation_pct) / 100,
    east: (batchQuantity * allocation.east.allocation_pct) / 100
  };
  const floored = {
    west: Math.floor(raw.west),
    central: Math.floor(raw.central),
    east: Math.floor(raw.east)
  };
  let remainder = batchQuantity - floored.west - floored.central - floored.east;
  const order = (Object.keys(raw) as Region[]).sort(
    (a, b) => raw[b] - Math.floor(raw[b]) - (raw[a] - Math.floor(raw[a]))
  );
  for (let index = 0; index < remainder; index += 1) {
    floored[order[index]] += 1;
  }
  return floored;
}

export function buildShipmentUnitPreview(draft: ShipmentDraft): ShipmentUnitPreview[] {
  return draft.batches.flatMap((batch) => {
    const quantities = calculateUnitQuantities(batch.batch_quantity, draft.warehouse_config);
    return (Object.keys(draft.warehouse_config) as Region[]).map((region) => ({
      key: `${batch.id}-${region}`,
      batch_index: batch.batch_index,
      region,
      region_label: REGION_LABELS[region],
      quantity: quantities[region],
      ship_date: batch.ship_date,
      transit_days: draft.warehouse_config[region].transit_days,
      arrival_date: dayjs(batch.ship_date).add(draft.warehouse_config[region].transit_days, "day").format("YYYY-MM-DD")
    }));
  });
}

export const defaultShipmentDraft: ShipmentDraft = {
  plan_name: "2026年5月振动甩脂机补货",
  sku: "HOMESY-VP-001",
  asin: "B0XXXXXXXX",
  total_quantity: 3000,
  batch_count: 3,
  warehouse_config: defaultWarehouseConfig,
  batches: [
    {
      id: "batch-1",
      batch_index: 1,
      ship_date: nthUpcomingSaturday(0).format("YYYY-MM-DD"),
      batch_quantity: 1000
    },
    {
      id: "batch-2",
      batch_index: 2,
      ship_date: nthUpcomingSaturday(1).format("YYYY-MM-DD"),
      batch_quantity: 1000
    },
    {
      id: "batch-3",
      batch_index: 3,
      ship_date: nthUpcomingSaturday(2).format("YYYY-MM-DD"),
      batch_quantity: 1000
    }
  ]
};

export const defaultSalesEntries: DailySalesDraft[] = Array.from({ length: 21 }, (_, index) => ({
  date: dayjs(defaultShipmentDraft.batches[0].ship_date).add(index, "day").format("YYYY-MM-DD"),
  planned_sales: index < 7 ? 45 : index < 14 ? 52 : 60
}));

export const sampleArrivals: Record<string, number> = buildShipmentUnitPreview(defaultShipmentDraft).reduce<Record<string, number>>(
  (accumulator, unit) => {
    accumulator[unit.arrival_date] = (accumulator[unit.arrival_date] ?? 0) + unit.quantity;
    return accumulator;
  },
  {}
);

export function calculateInventoryPreview(
  initialInventory: number,
  entries: DailySalesDraft[],
  arrivals: Record<string, number>,
  overrides: Record<string, number> = {}
): InventoryDayView[] {
  const rows: InventoryDayView[] = [];
  for (let index = 0; index < entries.length; index += 1) {
    const entry = entries[index];
    const opening_stock =
      index === 0
        ? (overrides[entry.date] ?? initialInventory)
        : (overrides[entry.date] ?? rows[index - 1].closing_stock);
    const arrivalQty = arrivals[entry.date] ?? 0;
    const available_stock = opening_stock + arrivalQty;
    const actual_sales = Math.min(entry.planned_sales, available_stock);
    const closing_stock = available_stock - actual_sales;
    const isFirst = index === 0;
    const isLast = index === entries.length - 1;
    const is_stockout =
      !((isFirst && available_stock === 0) || (isLast && (available_stock === 0 || entry.planned_sales === available_stock))) &&
      (available_stock === 0 || entry.planned_sales >= available_stock);

    rows.push({
      date: entry.date,
      opening_stock,
      arrivals: arrivalQty,
      available_stock,
      planned_sales: entry.planned_sales,
      actual_sales,
      closing_stock,
      is_stockout,
      has_override: entry.date in overrides
    });
  }
  return rows;
}

const previewRows = calculateInventoryPreview(500, defaultSalesEntries, sampleArrivals, {
  [defaultSalesEntries[8].date]: 620
});

export const sampleTurnoverCards: TurnoverCard[] = buildShipmentUnitPreview(defaultShipmentDraft).map((unit, index) => ({
  unit_id: index + 1,
  unit_label: `${dayjs(unit.ship_date).format("M月D日")}-${unit.region_label}`,
  ship_date: unit.ship_date,
  arrival_date: unit.arrival_date,
  total_pieces: unit.quantity,
  sold_pieces: unit.quantity - (index % 3 === 2 ? Math.round(unit.quantity * 0.28) : 0),
  remaining_pieces: index % 3 === 2 ? Math.round(unit.quantity * 0.28) : 0,
  avg_turnover_days: index % 3 === 2 ? 41.6 : 48.3 + index,
  fully_sold: index % 3 !== 2,
  sell_through_date:
    index % 3 === 2 ? null : dayjs(unit.arrival_date).add(32 + index * 4, "day").format("YYYY-MM-DD")
}));

export const sampleChartData = previewRows;

export function createBatch(index: number): BatchDraft {
  return {
    id: `batch-${index}-${Date.now()}`,
    batch_index: index,
    ship_date: nthUpcomingSaturday(index - 1).format("YYYY-MM-DD"),
    batch_quantity: 800
  };
}
