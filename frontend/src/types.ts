export type Region = "west" | "central" | "east";

export interface WarehouseConfigState {
  allocation_pct: number;
  transit_days: number;
}

export interface BatchDraft {
  id: string;
  batch_index: number;
  ship_date: string;
  batch_quantity: number;
}

export interface ShipmentDraft {
  plan_name: string;
  sku: string;
  asin: string;
  total_quantity: number;
  batch_count: number;
  warehouse_config: Record<Region, WarehouseConfigState>;
  batches: BatchDraft[];
}

export interface ShipmentUnitPreview {
  key: string;
  batch_index: number;
  region: Region;
  region_label: string;
  quantity: number;
  ship_date: string;
  transit_days: number;
  arrival_date: string;
}

export interface DailySalesDraft {
  date: string;
  planned_sales: number;
}

export interface InventoryDayView {
  date: string;
  opening_stock: number;
  arrivals: number;
  available_stock: number;
  planned_sales: number;
  actual_sales: number;
  closing_stock: number;
  is_stockout: boolean;
  has_override: boolean;
}

export interface TurnoverCard {
  unit_id: number;
  unit_label: string;
  ship_date: string;
  arrival_date: string;
  total_pieces: number;
  sold_pieces: number;
  remaining_pieces: number;
  avg_turnover_days: number | null;
  fully_sold: boolean;
  sell_through_date: string | null;
}

