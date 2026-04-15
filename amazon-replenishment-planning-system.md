# Amazon 补货与销售规划系统 — 开发文档

> **文档版本**: v1.0  
> **创建日期**: 2026-04-15  
> **目标平台**: Linux (Docker-ready)  
> **技术栈**: Python (FastAPI) + React + PostgreSQL + Redis

---

## 1. 系统概述

### 1.1 项目背景

本系统为亚马逊 FBA 卖家设计，用于管理多仓发货计划、销售预测与库存规划。系统核心解决以下痛点：

- 美西/美中/美东三仓分仓发货的批次管理与物流时效追踪
- 基于销量预测的库存周转分析与断货预警
- 多批次货件的生命周期追踪与周转效率评估

### 1.2 系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│                     Frontend (React)                    │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ 发货规划  │ │ 销售/库存规划 │ │   图表 & 周转分析     │ │
│  └──────────┘ └──────────────┘ └──────────────────────┘ │
└───────────────────────┬─────────────────────────────────┘
                        │ REST API (JSON)
┌───────────────────────┴─────────────────────────────────┐
│                  Backend (FastAPI)                       │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ 发货服务  │ │  库存计算引擎 │ │   周转分析服务        │ │
│  └──────────┘ └──────────────┘ └──────────────────────┘ │
└───────────────────────┬─────────────────────────────────┘
                        │
         ┌──────────────┴──────────────┐
         │        PostgreSQL           │
         │  (持久化存储: 发货/库存/销售) │
         └──────────────┬──────────────┘
                        │
                ┌───────┴───────┐
                │    Redis      │
                │ (计算缓存)     │
                └───────────────┘
```

### 1.3 技术选型说明

| 层级 | 技术 | 理由 |
|------|------|------|
| 前端 | React 18 + TypeScript | 组件化开发、类型安全、生态成熟 |
| 图表 | Recharts | 轻量、React 原生集成、满足库存/销量折线图需求 |
| UI 框架 | Ant Design | 中后台场景成熟、表格/表单/日期选择器开箱即用 |
| 后端 | Python FastAPI | 异步高性能、自动生成 API 文档、类型提示友好 |
| 数据库 | PostgreSQL 16 | 关系型数据、JSON 支持、时间序列查询优化 |
| 缓存 | Redis | 库存计算结果缓存、减少重复计算 |
| 容器化 | Docker + docker-compose | 后期封装目标，当前先以标准 Linux 部署为主 |

---

## 2. 数据模型设计

### 2.1 ER 关系图

```
ShipmentPlan (发货计划)
  ├── 1:N ── ShipmentBatch (发货批次)
  │            └── 1:3 ── ShipmentUnit (货件, 每批次固定三仓)
  │
  └── 1:1 ── WarehouseConfig (仓库配置)

SalesPlan (销售/库存规划)
  ├── 属性: initial_inventory (首个期初库存)
  ├── 1:N ── DailySalesEntry (每日销量条目)
  └── 1:N ── InventoryOverride (库存校正记录)

ShipmentUnit ──关联── DailySalesEntry (通过到货日期影响库存)
```

### 2.2 数据表定义

#### 2.2.1 `warehouse_config` — 仓库配置

```sql
CREATE TABLE warehouse_config (
    id              SERIAL PRIMARY KEY,
    plan_id         INTEGER NOT NULL,          -- 关联到发货计划
    region          VARCHAR(10) NOT NULL,      -- 'west' | 'central' | 'east'
    region_label    VARCHAR(50) NOT NULL,      -- '美西' | '美中' | '美东'
    allocation_pct  DECIMAL(5,2) NOT NULL,     -- 货物分配比例, 如 40.00 表示 40%
    transit_days    INTEGER NOT NULL,          -- 物流时效(天)
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),

    CONSTRAINT chk_region CHECK (region IN ('west', 'central', 'east')),
    CONSTRAINT chk_allocation CHECK (allocation_pct >= 0 AND allocation_pct <= 100)
);

-- 同一计划下三仓比例之和必须为 100
-- 通过应用层校验实现
```

#### 2.2.2 `shipment_plan` — 发货计划

```sql
CREATE TABLE shipment_plan (
    id              SERIAL PRIMARY KEY,
    plan_name       VARCHAR(200) NOT NULL,
    sku             VARCHAR(100),              -- 关联 SKU
    asin            VARCHAR(20),               -- 关联 ASIN
    total_quantity  INTEGER NOT NULL,          -- 总发货数量
    batch_count     INTEGER NOT NULL DEFAULT 1,-- 批次数量
    status          VARCHAR(20) DEFAULT 'draft', -- draft | confirmed | in_transit | completed
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
```

#### 2.2.3 `shipment_batch` — 发货批次

```sql
CREATE TABLE shipment_batch (
    id              SERIAL PRIMARY KEY,
    plan_id         INTEGER NOT NULL REFERENCES shipment_plan(id) ON DELETE CASCADE,
    batch_index     INTEGER NOT NULL,          -- 批次序号 (1, 2, 3...)
    ship_date       DATE NOT NULL,             -- 发货日期 (必须为周六)
    batch_quantity  INTEGER NOT NULL,          -- 该批次总发货量
    created_at      TIMESTAMP DEFAULT NOW(),

    CONSTRAINT chk_saturday CHECK (EXTRACT(DOW FROM ship_date) = 6),
    UNIQUE(plan_id, batch_index)
);
```

#### 2.2.4 `shipment_unit` — 货件 (最小物流单位)

```sql
CREATE TABLE shipment_unit (
    id              SERIAL PRIMARY KEY,
    batch_id        INTEGER NOT NULL REFERENCES shipment_batch(id) ON DELETE CASCADE,
    region          VARCHAR(10) NOT NULL,      -- 'west' | 'central' | 'east'
    quantity        INTEGER NOT NULL,          -- 该仓发货数量
    transit_days    INTEGER NOT NULL,          -- 该货件的物流时效
    ship_date       DATE NOT NULL,             -- 发货日期 (继承自批次)
    arrival_date    DATE NOT NULL,             -- 预计到货日 = ship_date + transit_days
    status          VARCHAR(20) DEFAULT 'pending', -- pending | shipped | arrived
    created_at      TIMESTAMP DEFAULT NOW(),

    CONSTRAINT chk_region CHECK (region IN ('west', 'central', 'east'))
);

-- 索引: 按到货日期查询 (库存计算核心)
CREATE INDEX idx_shipment_unit_arrival ON shipment_unit(arrival_date);
```

#### 2.2.5 `sales_plan` — 销售/库存规划

```sql
CREATE TABLE sales_plan (
    id                  SERIAL PRIMARY KEY,
    plan_name           VARCHAR(200) NOT NULL,
    sku                 VARCHAR(100),
    asin                VARCHAR(20),
    start_date          DATE NOT NULL,            -- 规划开始日期
    end_date            DATE NOT NULL,            -- 规划结束日期
    initial_inventory   INTEGER NOT NULL DEFAULT 0, -- 首个期初库存
    shipment_plan_id    INTEGER REFERENCES shipment_plan(id), -- 关联发货计划
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
```

#### 2.2.6 `daily_sales_entry` — 每日销量条目

```sql
CREATE TABLE daily_sales_entry (
    id              SERIAL PRIMARY KEY,
    sales_plan_id   INTEGER NOT NULL REFERENCES sales_plan(id) ON DELETE CASCADE,
    entry_date      DATE NOT NULL,
    planned_sales   INTEGER NOT NULL DEFAULT 0,  -- 规划销量
    actual_sales    INTEGER,                     -- 实际消耗量 (由引擎计算, 受库存限制)
    is_stockout     BOOLEAN DEFAULT FALSE,       -- 是否断货
    opening_stock   INTEGER,                     -- 期初库存 (引擎计算)
    closing_stock   INTEGER,                     -- 期末库存 (引擎计算)
    arrivals        INTEGER DEFAULT 0,           -- 当日到货量
    created_at      TIMESTAMP DEFAULT NOW(),

    UNIQUE(sales_plan_id, entry_date)
);

CREATE INDEX idx_daily_sales_date ON daily_sales_entry(sales_plan_id, entry_date);
```

#### 2.2.7 `inventory_override` — 库存校正记录

```sql
CREATE TABLE inventory_override (
    id              SERIAL PRIMARY KEY,
    sales_plan_id   INTEGER NOT NULL REFERENCES sales_plan(id) ON DELETE CASCADE,
    override_date   DATE NOT NULL,
    override_value  INTEGER NOT NULL,            -- 校正后的期初库存值
    reason          TEXT,                         -- 校正原因
    created_at      TIMESTAMP DEFAULT NOW(),

    UNIQUE(sales_plan_id, override_date)
);
```

---

## 3. 核心业务逻辑

### 3.1 发货计划模块

#### 3.1.1 发货日期约束

发货时间固定为**每周六**。前端提供日期选择器组件，仅允许选择周六日期。

**日期选择器行为规范：**

- 日历面板中非周六日期置灰且不可点击
- 默认选中距今最近的下一个周六
- 支持手动输入日期，输入后自动校验是否为周六，若不是则提示并自动修正为最近的周六
- 支持快捷选择："本周六"、"下周六"、"两周后周六"

```python
# 后端校验逻辑
from datetime import date

def validate_ship_date(ship_date: date) -> bool:
    """校验发货日期是否为周六 (weekday() == 5)"""
    return ship_date.weekday() == 5

def next_saturday(from_date: date) -> date:
    """获取距 from_date 最近的下一个周六"""
    days_ahead = 5 - from_date.weekday()  # 5 = Saturday
    if days_ahead <= 0:
        days_ahead += 7
    return from_date + timedelta(days=days_ahead)
```

#### 3.1.2 分仓发货与批次逻辑

每次发货计划包含 N 个批次，每个批次必须包含美西、美中、美东三个货件，即：

```
发货计划
├── 批次 1 (ship_date: 2026-04-18)
│   ├── 货件 1-1: 美西, 400件, 物流15天 → 到货 2026-05-03
│   ├── 货件 1-2: 美中, 350件, 物流18天 → 到货 2026-05-06
│   └── 货件 1-3: 美东, 250件, 物流22天 → 到货 2026-05-10
├── 批次 2 (ship_date: 2026-04-25)
│   ├── 货件 2-1: 美西, 400件, 物流15天 → 到货 2026-05-10
│   ├── 货件 2-2: 美中, 350件, 物流18天 → 到货 2026-05-13
│   └── 货件 2-3: 美东, 250件, 物流22天 → 到货 2026-05-17
└── 批次 3 (ship_date: 2026-05-02)
    ├── 货件 3-1: 美西, 400件, 物流15天 → 到货 2026-05-17
    ├── 货件 3-2: 美中, 350件, 物流18天 → 到货 2026-05-20
    └── 货件 3-3: 美东, 250件, 物流22天 → 到货 2026-05-24
```

**总货件数 = 批次数 × 3**

**货件数量计算：**

```python
def calculate_unit_quantities(
    batch_quantity: int,
    allocation: dict  # {'west': 40, 'central': 35, 'east': 25}
) -> dict:
    """
    根据分配比例计算每仓发货量。
    使用 largest remainder method 确保整数分配总和等于 batch_quantity。
    """
    raw = {r: batch_quantity * pct / 100 for r, pct in allocation.items()}
    floored = {r: int(v) for r, v in raw.items()}
    remainder = batch_quantity - sum(floored.values())
    
    # 按小数部分降序分配余量
    decimals = sorted(raw.keys(), key=lambda r: raw[r] - floored[r], reverse=True)
    for i in range(remainder):
        floored[decimals[i]] += 1
    
    return floored  # 例: {'west': 400, 'central': 350, 'east': 250}
```

#### 3.1.3 仓库配置的自定义能力

每次发货计划允许独立配置：

| 配置项 | 说明 | 默认值 | 约束 |
|--------|------|--------|------|
| 美西分配比例 | 该仓在每次发货中的货物占比 | 40% | 三仓合计 = 100% |
| 美中分配比例 | | 35% | |
| 美东分配比例 | | 25% | |
| 美西物流时效 | 从发货到 FBA 可售的天数 | 15天 | 正整数 |
| 美中物流时效 | | 18天 | |
| 美东物流时效 | | 22天 | |

前端应提供一个直观的配置面板，当分配比例之和不等于 100% 时实时提示并阻止提交。每个批次可以选择是否继承计划级的仓库配置或独立覆写。

---

### 3.2 销售/库存规划模块

#### 3.2.1 核心概念

| 术语 | 定义 |
|------|------|
| 期初库存 (Opening Stock) | 当天开始时的可用库存量 |
| 期末库存 (Closing Stock) | 当天结束时的剩余库存 = 期初库存 - 实际消耗量 |
| 规划销量 (Planned Sales) | 用户输入的预期每日销量 |
| 实际消耗量 (Actual Sales) | 系统计算: min(规划销量, 期初库存) |
| 到货量 (Arrivals) | 当日到达并入库的货件总量 |
| 断货 (Stockout) | 当期初库存为 0，或规划销量 ≥ 期初库存时标记 |

#### 3.2.2 销量输入方式

系统支持两种销量输入模式：

**模式 A：逐日输入**

用户直接为特定日期设置销量。

```json
{ "date": "2026-05-01", "planned_sales": 50 }
```

**模式 B：时间段批量输入**

用户选择一个日期范围并设定统一日销量，系统自动展开为逐日记录。

```json
{
    "start_date": "2026-05-01",
    "end_date": "2026-05-31",
    "daily_sales": 50
}
```

展开后生成 31 条 `daily_sales_entry` 记录，每天销量均为 50。后续用户可对个别日期做微调。

#### 3.2.3 库存计算引擎 (核心算法)

库存计算采用**逐日正向迭代**方式，从规划起始日开始按天推算。

```python
def calculate_inventory(
    sales_plan: SalesPlan,
    daily_entries: list[DailySalesEntry],
    overrides: dict[date, int],         # date -> override_value
    arrivals_map: dict[date, int],      # date -> 当日到货总量
) -> list[DailyResult]:
    """
    核心库存计算引擎。
    
    计算规则:
    1. 首日期初库存 = sales_plan.initial_inventory
    2. 若某日存在库存校正 (override)，则该日期初库存 = override 值
    3. 当日到货量在 "期初库存" 之后、"销售消耗" 之前 计入
       即: 可用库存 = 期初库存 + 当日到货量
    4. 实际消耗 = min(规划销量, 可用库存)
    5. 期末库存 = 可用库存 - 实际消耗
    6. 次日期初库存 = 当日期末库存 (若次日无 override)
    """
    results = []
    total_days = len(daily_entries)

    for i, entry in enumerate(daily_entries):
        current_date = entry.entry_date
        is_first_day = (i == 0)
        is_last_day = (i == total_days - 1)

        # --- Step 1: 确定期初库存 ---
        if is_first_day:
            opening = sales_plan.initial_inventory
        elif current_date in overrides:
            opening = overrides[current_date]
        else:
            opening = results[i - 1].closing_stock

        # --- Step 2: 加入当日到货 ---
        arrivals = arrivals_map.get(current_date, 0)
        available = opening + arrivals

        # --- Step 3: 计算实际消耗与断货判定 ---
        planned = entry.planned_sales
        actual_sales = min(planned, available)

        # 断货判定逻辑 (见 3.2.4 节详细说明)
        is_stockout = False
        if opening == 0 or planned >= (opening + arrivals):
            # 排除首日和最后一天的特殊情况
            if is_first_day and opening == 0 and arrivals == 0:
                is_stockout = False  # 首日期初为0不算断货
            elif is_last_day and planned == available and available > 0:
                is_stockout = False  # 最后一天刚好消耗完不算断货
            elif is_last_day and opening == 0 and arrivals == 0:
                is_stockout = False  # 最后一天期初为0不算断货
            else:
                is_stockout = True

        # --- Step 4: 计算期末库存 ---
        closing = available - actual_sales

        results.append(DailyResult(
            date=current_date,
            opening_stock=opening,
            arrivals=arrivals,
            available_stock=available,
            planned_sales=planned,
            actual_sales=actual_sales,
            closing_stock=closing,
            is_stockout=is_stockout,
        ))

    return results
```

#### 3.2.4 断货判定规则（详细说明）

断货判定需要区分正常情况和异常情况：

**判定为断货的条件：**

- 当天期初库存为 0（含到货后仍为 0），且不是首日或末日
- 当天规划销量 ≥ 当天可用库存（期初 + 到货），且不是末日恰好消耗完

**不判定为断货的特殊情况：**

- **首日**：期初库存为 0 不算断货（规划的起点，尚未开始消耗）
- **末日**：期初库存为 0 不算断货（规划的终点，属于刚好消耗完）
- **末日**：规划销量恰好等于当天期初库存（+ 到货）不算断货（刚好清零）

**断货时的处理方式：**

当判定断货时，实际消耗量设为 `min(planned_sales, available_stock)`，即最多消耗到 0。前端应以醒目标记（红色高亮、图标提示）标识断货日期。

```python
# 断货判定伪代码 (精简版)
def check_stockout(
    opening: int, arrivals: int, planned: int,
    is_first: bool, is_last: bool
) -> bool:
    available = opening + arrivals
    
    # 首日期初为0: 不算断货
    if is_first and available == 0:
        return False
    
    # 末日: 期初为0 或刚好消耗完, 不算断货
    if is_last:
        if available == 0:
            return False
        if planned == available and available > 0:
            return False
    
    # 常规断货判定
    if available == 0:
        return True
    if planned >= available:
        return True
    
    return False
```

#### 3.2.5 库存校正 (Override) 机制

允许用户在任意日期强制覆写期初库存，以修正规划与实际之间的偏差。

**校正行为规范：**

1. 校正值直接替换该日的期初库存
2. 校正日之后的所有日期按新值重新计算（正向传播）
3. 校正日之前的记录不受影响
4. 支持多日分别校正，各自独立生效
5. 校正记录保留审计日志（who/when/原值/新值/原因）

**示例场景：**

```
假设 5月10日 按规划计算的期初库存 = 3000，实际盘点 = 3005

用户操作: 校正 5月10日 期初库存为 3005

影响链:
  5/10 期初: 3005 (校正值)
  5/10 销量: 50 → 期末: 2955
  5/11 到货: 500 → 期初: 2955 + 500(这里取消,到货在可用库存里体现) 
  
  更准确的影响链:
  5/10 期初: 3005 (校正值), 到货: 0, 可用: 3005, 销量: 50, 期末: 2955
  5/11 期初: 2955, 到货: 500, 可用: 3455, 销量: 50, 期末: 3405
  5/12 期初: 3405, ...
```

#### 3.2.6 到货量与发货计划的联动

到货量来源于发货计划中各货件的 `arrival_date`。引擎在计算前先汇总每日到货：

```python
def build_arrivals_map(shipment_units: list[ShipmentUnit]) -> dict[date, int]:
    """
    将所有货件的到货数据汇总为 {date: total_quantity} 映射。
    同一天可能有多个货件到达（来自不同批次/不同仓）。
    """
    arrivals = defaultdict(int)
    for unit in shipment_units:
        arrivals[unit.arrival_date] += unit.quantity
    return dict(arrivals)
```

---

### 3.3 库存周转时间分析模块

#### 3.3.1 概念定义

**库存周转时间 (Inventory Turnover Duration)** 衡量一批货件从发货到完全售罄所经历的时间。

- 计算起点：货件的**发货日期** (ship_date)
- 计算终点：货件中**最后一件商品被售出**的日期
- 单件商品的周转时间 = 售出日期 - 发货日期
- 货件的库存周转时间 = 该货件中所有单件商品周转时间的**算术平均值**

#### 3.3.2 周转时间计算算法

核心思路：按照 FIFO（先进先出）原则，依到货时间顺序消耗库存，跟踪每批货件中各件商品的售出日期。

```python
def calculate_turnover(
    shipment_units: list[ShipmentUnit],  # 按 arrival_date 排序
    daily_results: list[DailyResult],     # 按 date 排序的每日计算结果
) -> list[ShipmentTurnover]:
    """
    计算每个货件的库存周转时间。
    
    FIFO 消耗规则:
    - 先到的货优先被消耗
    - 期初库存（非来自货件的原始库存）最先被消耗
    - 每个货件内部不再区分单件，只追踪 "剩余数量" 和 "每天消耗了多少"
    """
    # 构建货件队列 (FIFO)
    # 原始期初库存视为一个特殊的 "虚拟货件"，排在所有真实货件之前
    fifo_queue = deque()
    
    # 虚拟货件: 初始库存
    if daily_results and daily_results[0].opening_stock > 0:
        fifo_queue.append({
            'unit_id': None,  # 虚拟货件
            'ship_date': None,
            'remaining': daily_results[0].opening_stock,
            'consumption_log': []  # [(date, qty), ...]
        })
    
    # 按到货日期排序的真实货件
    units_by_arrival = sorted(shipment_units, key=lambda u: u.arrival_date)
    arrival_index = 0
    
    for day_result in daily_results:
        current_date = day_result.date
        
        # 将当天到货的货件加入队列
        while (arrival_index < len(units_by_arrival) and 
               units_by_arrival[arrival_index].arrival_date == current_date):
            unit = units_by_arrival[arrival_index]
            fifo_queue.append({
                'unit_id': unit.id,
                'ship_date': unit.ship_date,
                'remaining': unit.quantity,
                'consumption_log': []
            })
            arrival_index += 1
        
        # 按 FIFO 消耗当日销量
        remaining_sales = day_result.actual_sales
        while remaining_sales > 0 and fifo_queue:
            front = fifo_queue[0]
            consume = min(remaining_sales, front['remaining'])
            front['remaining'] -= consume
            front['consumption_log'].append((current_date, consume))
            remaining_sales -= consume
            
            if front['remaining'] == 0:
                fifo_queue.popleft()
    
    # 计算每个货件的平均周转时间
    results = []
    for unit_data in all_completed_units:
        if unit_data['unit_id'] is None:
            continue  # 跳过虚拟货件
        
        ship_date = unit_data['ship_date']
        total_turnover_days = 0
        total_pieces = 0
        
        for sell_date, qty in unit_data['consumption_log']:
            days = (sell_date - ship_date).days
            total_turnover_days += days * qty
            total_pieces += qty
        
        avg_turnover = total_turnover_days / total_pieces if total_pieces > 0 else None
        
        results.append(ShipmentTurnover(
            unit_id=unit_data['unit_id'],
            ship_date=ship_date,
            total_pieces=total_pieces,
            avg_turnover_days=round(avg_turnover, 1) if avg_turnover else None,
            fully_sold=(unit_data['remaining'] == 0),
            sell_through_date=unit_data['consumption_log'][-1][0] if unit_data['consumption_log'] else None,
        ))
    
    return results
```

#### 3.3.3 周转时间展示格式

每个货件的展示信息：

```
┌─────────────────────────────────────────────────────────────────┐
│ 货件: 4月18日-美西  │ 发货: 04/18  │ 到货: 05/03  │ 数量: 400  │
│ 状态: 已售罄        │ 售罄日: 06/15 │ 平均周转: 48.3天        │
├─────────────────────────────────────────────────────────────────┤
│ 货件: 4月18日-美中  │ 发货: 04/18  │ 到货: 05/06  │ 数量: 350  │
│ 状态: 已售罄        │ 售罄日: 06/22 │ 平均周转: 52.1天        │
├─────────────────────────────────────────────────────────────────┤
│ 货件: 4月18日-美东  │ 发货: 04/18  │ 到货: 05/10  │ 数量: 250  │
│ 状态: 销售中        │ 已售: 180/250 │ 当前平均周转: 41.6天    │
└─────────────────────────────────────────────────────────────────┘
```

命名规范：`{月}月{日}日-{仓库}`，如 "4月18日-美西"。

---

## 4. API 设计

### 4.1 API 端点总览

基础路径: `/api/v1`

#### 发货计划相关

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/shipment-plans` | 创建发货计划 |
| GET | `/shipment-plans` | 获取发货计划列表 |
| GET | `/shipment-plans/{id}` | 获取发货计划详情（含批次和货件） |
| PUT | `/shipment-plans/{id}` | 更新发货计划 |
| DELETE | `/shipment-plans/{id}` | 删除发货计划 |
| POST | `/shipment-plans/{id}/batches` | 新增发货批次 |
| PUT | `/shipment-plans/{id}/batches/{batch_id}` | 更新批次信息 |
| DELETE | `/shipment-plans/{id}/batches/{batch_id}` | 删除批次 |
| PUT | `/shipment-plans/{id}/warehouse-config` | 更新仓库配置 |

#### 销售/库存规划相关

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/sales-plans` | 创建销售规划 |
| GET | `/sales-plans` | 获取销售规划列表 |
| GET | `/sales-plans/{id}` | 获取规划详情 |
| PUT | `/sales-plans/{id}` | 更新规划基础信息 |
| DELETE | `/sales-plans/{id}` | 删除规划 |
| POST | `/sales-plans/{id}/entries` | 批量录入销量数据 |
| PUT | `/sales-plans/{id}/entries/{date}` | 更新指定日期的销量 |
| POST | `/sales-plans/{id}/entries/batch` | 按时间段批量设置销量 |
| POST | `/sales-plans/{id}/overrides` | 新增库存校正 |
| DELETE | `/sales-plans/{id}/overrides/{date}` | 取消库存校正 |
| GET | `/sales-plans/{id}/calculate` | 触发库存计算并返回每日明细 |

#### 图表与分析

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/sales-plans/{id}/chart-data` | 获取图表数据（期初库存 + 销量折线） |
| GET | `/sales-plans/{id}/turnover` | 获取货件周转时间分析 |
| GET | `/sales-plans/{id}/stockout-warnings` | 获取断货预警列表 |

### 4.2 关键 API 请求/响应示例

#### 创建发货计划

**Request:**

```json
POST /api/v1/shipment-plans
{
    "plan_name": "2026年5月振动甩脂机补货",
    "sku": "HOMESY-VP-001",
    "asin": "B0XXXXXXXX",
    "total_quantity": 3000,
    "batch_count": 3,
    "warehouse_config": {
        "west":    { "allocation_pct": 40, "transit_days": 15 },
        "central": { "allocation_pct": 35, "transit_days": 18 },
        "east":    { "allocation_pct": 25, "transit_days": 22 }
    },
    "batches": [
        { "batch_index": 1, "ship_date": "2026-04-18", "batch_quantity": 1000 },
        { "batch_index": 2, "ship_date": "2026-04-25", "batch_quantity": 1000 },
        { "batch_index": 3, "ship_date": "2026-05-02", "batch_quantity": 1000 }
    ]
}
```

**Response:**

```json
{
    "id": 1,
    "plan_name": "2026年5月振动甩脂机补货",
    "status": "draft",
    "total_quantity": 3000,
    "batch_count": 3,
    "shipment_units": [
        {
            "id": 1, "batch_index": 1, "region": "west",
            "quantity": 400, "ship_date": "2026-04-18",
            "transit_days": 15, "arrival_date": "2026-05-03"
        },
        {
            "id": 2, "batch_index": 1, "region": "central",
            "quantity": 350, "ship_date": "2026-04-18",
            "transit_days": 18, "arrival_date": "2026-05-06"
        },
        // ... 共 9 个货件
    ]
}
```

#### 库存计算结果

**Response:**

```json
GET /api/v1/sales-plans/1/calculate
{
    "sales_plan_id": 1,
    "calculation_date": "2026-04-15T10:30:00Z",
    "summary": {
        "total_days": 60,
        "total_planned_sales": 3000,
        "total_actual_sales": 2850,
        "stockout_days": 3,
        "stockout_dates": ["2026-06-08", "2026-06-09", "2026-06-10"],
        "ending_inventory": 150
    },
    "daily_data": [
        {
            "date": "2026-05-01",
            "opening_stock": 500,
            "arrivals": 0,
            "available_stock": 500,
            "planned_sales": 50,
            "actual_sales": 50,
            "closing_stock": 450,
            "is_stockout": false,
            "has_override": false
        },
        {
            "date": "2026-05-03",
            "opening_stock": 400,
            "arrivals": 400,
            "available_stock": 800,
            "planned_sales": 50,
            "actual_sales": 50,
            "closing_stock": 750,
            "is_stockout": false,
            "has_override": false,
            "arrival_details": [
                { "unit_label": "4月18日-美西", "quantity": 400 }
            ]
        }
        // ...
    ]
}
```

---

## 5. 前端设计

### 5.1 页面结构

```
App
├── 📦 发货规划 (/shipments)
│   ├── 发货计划列表
│   └── 发货计划编辑器
│       ├── 基础信息 (名称/SKU/ASIN/总量)
│       ├── 仓库配置面板
│       ├── 批次管理器
│       └── 货件预览表格
│
├── 📊 销售/库存规划 (/sales)
│   ├── 规划列表
│   └── 规划编辑器
│       ├── 基础信息 + 首日期初库存
│       ├── 销量输入区 (逐日/批量)
│       ├── 库存校正工具
│       ├── 每日库存明细表
│       └── 断货预警提示栏
│
├── 📈 图表面板 (/charts)
│   ├── 期初库存折线图
│   ├── 销量柱状图
│   ├── 到货标记线
│   └── 断货区域高亮
│
└── 🔄 周转分析 (/turnover)
    ├── 货件周转时间列表
    └── 周转时间对比图
```

### 5.2 核心组件设计

#### 5.2.1 周六日期选择器 (`SaturdayDatePicker`)

```typescript
interface SaturdayDatePickerProps {
    value: string | null;          // ISO date string
    onChange: (date: string) => void;
    minDate?: string;              // 最早可选日期
    maxDate?: string;              // 最晚可选日期
    quickSelects?: boolean;        // 是否显示快捷选项
}

// 行为规范:
// 1. 日历面板：非周六日期 disabled + 灰色
// 2. 快捷按钮：本周六 / 下周六 / 两周后周六
// 3. 输入校验：手动输入非周六日期时，
//    自动修正为最近的下一个周六并 toast 提示
// 4. 国际化：支持中/英日期格式
```

#### 5.2.2 仓库配置面板 (`WarehouseConfigPanel`)

```typescript
interface WarehouseConfig {
    west:    { allocation_pct: number; transit_days: number };
    central: { allocation_pct: number; transit_days: number };
    east:    { allocation_pct: number; transit_days: number };
}

// UI 布局:
// ┌────────────────────────────────────────────────┐
// │ 仓库配置                                       │
// ├──────────┬──────────────┬───────────────────────┤
// │ 仓库     │ 分配比例 (%)  │ 物流时效 (天)         │
// ├──────────┼──────────────┼───────────────────────┤
// │ 🟦 美西  │ [__40__]     │ [__15__]              │
// │ 🟨 美中  │ [__35__]     │ [__18__]              │
// │ 🟥 美东  │ [__25__]     │ [__22__]              │
// ├──────────┼──────────────┼───────────────────────┤
// │ 合计     │ 100% ✅       │                      │
// │          │ (非100%时红色警告并阻止保存)           │
// └──────────┴──────────────┴───────────────────────┘
//
// 交互: 滑块 + 数字输入框联动，修改一个仓的比例时
//       其余两仓不自动调整（让用户手动平衡）
```

#### 5.2.3 批次管理器 (`BatchManager`)

```typescript
interface BatchManagerProps {
    batches: ShipmentBatch[];
    warehouseConfig: WarehouseConfig;
    onBatchChange: (batches: ShipmentBatch[]) => void;
}

// UI 布局:
// ┌─────────────────────────────────────────────────────────────┐
// │ 发货批次 (3批)                           [+ 新增批次]       │
// ├─────────────────────────────────────────────────────────────┤
// │ 批次 1                                                     │
// │ 发货日期: [📅 2026-04-18 (周六)]  数量: [___1000___]       │
// │ ┌──────────────────────────────────────────────────────┐   │
// │ │ 美西: 400件 → 预计到货 05/03                         │   │
// │ │ 美中: 350件 → 预计到货 05/06                         │   │
// │ │ 美东: 250件 → 预计到货 05/10                         │   │
// │ └──────────────────────────────────────────────────────┘   │
// ├─────────────────────────────────────────────────────────────┤
// │ 批次 2                                                     │
// │ 发货日期: [📅 2026-04-25 (周六)]  数量: [___1000___]       │
// │ ...                                                        │
// └─────────────────────────────────────────────────────────────┘
```

#### 5.2.4 销量输入组件 (`SalesInputPanel`)

```typescript
// 支持两种输入模式的 Tab 切换

// Tab 1: 逐日输入
// ┌─────────────────────────────────────┐
// │ 日期         │ 规划销量              │
// │ 2026-05-01   │ [___50___]           │
// │ 2026-05-02   │ [___50___]           │
// │ ...          │ ...                   │
// └─────────────────────────────────────┘

// Tab 2: 批量输入
// ┌─────────────────────────────────────┐
// │ 开始日期: [📅 2026-05-01]           │
// │ 结束日期: [📅 2026-05-31]           │
// │ 每日销量: [___50___]                │
// │              [应用到选定日期范围]     │
// └─────────────────────────────────────┘
```

#### 5.2.5 库存校正组件 (`InventoryOverrideControl`)

```typescript
// 在每日库存明细表中，期初库存列可直接点击编辑
// 编辑后弹出确认对话框:
//
// ┌─────────────────────────────────────────┐
// │ 校正期初库存                             │
// │                                         │
// │ 日期: 2026-05-10                        │
// │ 原计算值: 3000                           │
// │ 校正为:   [___3005___]                   │
// │ 原因(选填): [实际盘点差异___]              │
// │                                         │
// │ ⚠️ 校正后将影响 5/10 之后所有日期的库存    │
// │    计算。                                │
// │                                         │
// │         [取消]     [确认校正]             │
// └─────────────────────────────────────────┘
//
// 已校正日期在表格中以蓝色背景标记，
// 悬停显示校正详情（原值、校正值、原因、时间）
```

### 5.3 图表设计

#### 5.3.1 主图表 — 库存与销量趋势图

使用 Recharts 组合图表：

```typescript
interface ChartDataPoint {
    date: string;
    openingStock: number;        // 期初库存 - 面积图
    plannedSales: number;        // 规划销量 - 柱状图
    actualSales: number;         // 实际消耗 - 柱状图 (叠加)
    isStockout: boolean;         // 断货标记
    arrivals: number;            // 到货量 - 标记点
    hasOverride: boolean;        // 是否有校正
}

// 图表元素:
// 1. Y轴左: 库存数量
// 2. Y轴右: 销量
// 3. 面积图: 期初库存变化趋势 (浅蓝填充)
// 4. 柱状图: 每日销量 (绿色)
// 5. 到货标记: 垂直虚线 + 标注到货量
// 6. 断货区域: 红色半透明背景覆盖断货日期范围
// 7. 校正标记: 蓝色菱形标记在校正日期的库存折线上
// 8. Tooltip: 悬停显示完整日数据
```

**图表交互:**

- 支持日期范围缩放（brush 组件）
- 点击到货标记可查看货件详情
- 断货区域悬停显示断货天数和影响销量

---

## 6. 项目目录结构

```
amazon-replenishment-planner/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI 入口
│   │   ├── config.py                  # 配置管理 (环境变量)
│   │   ├── database.py                # 数据库连接 & Session
│   │   │
│   │   ├── models/                    # SQLAlchemy ORM 模型
│   │   │   ├── __init__.py
│   │   │   ├── shipment.py            # ShipmentPlan, Batch, Unit
│   │   │   ├── sales.py               # SalesPlan, DailySalesEntry
│   │   │   ├── warehouse.py           # WarehouseConfig
│   │   │   └── override.py            # InventoryOverride
│   │   │
│   │   ├── schemas/                   # Pydantic 请求/响应模型
│   │   │   ├── __init__.py
│   │   │   ├── shipment.py
│   │   │   ├── sales.py
│   │   │   └── common.py
│   │   │
│   │   ├── services/                  # 业务逻辑层
│   │   │   ├── __init__.py
│   │   │   ├── shipment_service.py    # 发货计划 CRUD + 货件生成
│   │   │   ├── inventory_engine.py    # 库存计算引擎 (核心)
│   │   │   ├── turnover_service.py    # 周转时间计算
│   │   │   └── warehouse_service.py   # 仓库配置管理
│   │   │
│   │   ├── routers/                   # API 路由
│   │   │   ├── __init__.py
│   │   │   ├── shipment.py
│   │   │   ├── sales.py
│   │   │   └── analysis.py            # 图表数据 + 周转分析
│   │   │
│   │   └── utils/
│   │       ├── date_utils.py          # 周六校验、日期计算
│   │       └── allocation.py          # 分仓数量分配算法
│   │
│   ├── alembic/                       # 数据库迁移
│   │   ├── versions/
│   │   └── env.py
│   │
│   ├── tests/
│   │   ├── test_inventory_engine.py   # 库存引擎单元测试 (重点)
│   │   ├── test_turnover.py
│   │   ├── test_shipment.py
│   │   └── test_date_utils.py
│   │
│   ├── requirements.txt
│   ├── alembic.ini
│   └── pyproject.toml
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   │
│   │   ├── components/
│   │   │   ├── shipment/
│   │   │   │   ├── SaturdayDatePicker.tsx
│   │   │   │   ├── WarehouseConfigPanel.tsx
│   │   │   │   ├── BatchManager.tsx
│   │   │   │   └── ShipmentUnitPreview.tsx
│   │   │   │
│   │   │   ├── sales/
│   │   │   │   ├── SalesInputPanel.tsx
│   │   │   │   ├── InventoryOverrideControl.tsx
│   │   │   │   ├── DailyInventoryTable.tsx
│   │   │   │   └── StockoutWarning.tsx
│   │   │   │
│   │   │   ├── charts/
│   │   │   │   ├── InventoryChart.tsx
│   │   │   │   └── TurnoverChart.tsx
│   │   │   │
│   │   │   └── common/
│   │   │       ├── Layout.tsx
│   │   │       └── ErrorBoundary.tsx
│   │   │
│   │   ├── pages/
│   │   │   ├── ShipmentPlanPage.tsx
│   │   │   ├── SalesPlanPage.tsx
│   │   │   ├── ChartDashboard.tsx
│   │   │   └── TurnoverAnalysis.tsx
│   │   │
│   │   ├── services/
│   │   │   └── api.ts                 # Axios API 封装
│   │   │
│   │   ├── types/
│   │   │   ├── shipment.ts
│   │   │   ├── sales.ts
│   │   │   └── chart.ts
│   │   │
│   │   └── utils/
│   │       ├── dateUtils.ts
│   │       └── formatting.ts
│   │
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── docker/                            # Docker 相关 (预留)
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   └── nginx/
│       └── default.conf
│
├── scripts/
│   ├── init_db.sh                     # 数据库初始化
│   ├── seed_data.py                   # 测试数据填充
│   └── backup_db.sh                   # 数据库备份
│
├── .env.example                       # 环境变量模板
├── .gitignore
├── Makefile                           # 常用命令快捷方式
└── README.md
```

---

## 7. Docker 容器化预备

当前阶段以标准 Linux 部署为主，但目录结构和配置管理已为 Docker 化做好准备。

### 7.1 配置管理原则

所有配置通过环境变量注入，不硬编码：

```python
# backend/app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/replenishment"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # 应用
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = False
    
    # CORS (前端地址)
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    
    class Config:
        env_file = ".env"
```

### 7.2 预留 Docker Compose 结构

```yaml
# docker/docker-compose.yml (预留，暂不启用)
version: '3.8'

services:
  backend:
    build:
      context: ../backend
      dockerfile: ../docker/Dockerfile.backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/replenishment
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis

  frontend:
    build:
      context: ../frontend
      dockerfile: ../docker/Dockerfile.frontend
    ports:
      - "3000:80"
    depends_on:
      - backend

  db:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=replenishment
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

### 7.3 当前部署方式 (非 Docker)

```bash
# 1. 安装依赖
cd backend && pip install -r requirements.txt
cd frontend && npm install

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际值

# 3. 初始化数据库
bash scripts/init_db.sh

# 4. 运行数据库迁移
cd backend && alembic upgrade head

# 5. 启动后端
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 6. 启动前端 (开发模式)
cd frontend && npm run dev

# 生产模式: npm run build → 使用 nginx 托管静态文件
```

---

## 8. 测试策略

### 8.1 重点测试用例 — 库存计算引擎

库存计算引擎是整个系统的核心，需要覆盖以下场景：

```python
class TestInventoryEngine:
    
    def test_basic_daily_calculation(self):
        """基本场景: 期初500, 日销50, 无到货, 10天消耗到0"""
        
    def test_arrivals_increase_stock(self):
        """到货补充: 期初100, 日销50, 第3天到货400, 库存不断"""
        
    def test_stockout_detection(self):
        """断货检测: 库存耗尽后标记断货, 实际消耗不超过可用量"""
        
    def test_first_day_zero_not_stockout(self):
        """首日特殊: 期初为0不算断货"""
        
    def test_last_day_exact_consumption_not_stockout(self):
        """末日特殊: 刚好消耗完不算断货"""
        
    def test_last_day_zero_not_stockout(self):
        """末日特殊: 期初为0不算断货"""
        
    def test_override_propagation(self):
        """校正传播: 校正某日期初库存后, 后续日期正确重新计算"""
        
    def test_multiple_overrides(self):
        """多次校正: 多个校正点各自独立, 互不干扰"""
        
    def test_override_with_arrivals(self):
        """校正+到货: 校正值3005, 次日到货500, 次日可用3505"""
        
    def test_multiple_arrivals_same_day(self):
        """同日多到货: 同一天多个货件到达, 数量正确汇总"""
        
    def test_sales_exceeds_stock(self):
        """超额销售: 规划销量100但库存仅30, 实际消耗30"""
        
    def test_empty_plan(self):
        """边界: 空规划, 无销量条目"""
        
    def test_zero_initial_inventory(self):
        """边界: 期初库存为0, 纯靠到货补充"""
```

### 8.2 周转时间计算测试

```python
class TestTurnoverCalculation:
    
    def test_fifo_consumption_order(self):
        """FIFO: 先到的货优先消耗"""
        
    def test_initial_stock_consumed_first(self):
        """原始库存在所有货件之前被消耗"""
        
    def test_average_turnover_calculation(self):
        """平均周转: 货件400件, 分10天卖完, 验证平均值"""
        
    def test_partially_sold_unit(self):
        """部分售出: 货件未售罄时标记为销售中"""
        
    def test_multiple_batches_interleaved(self):
        """多批次交叉: 多批货件到货日期交叉时的FIFO正确性"""
```

---

## 9. 开发路线图

### Phase 1 — 基础框架与发货管理 (Week 1-2)

- 搭建后端 FastAPI 项目骨架
- 搭建前端 React 项目骨架
- 实现数据库模型与迁移
- 实现发货计划 CRUD
- 实现仓库配置面板
- 实现周六日期选择器
- 实现批次管理器

### Phase 2 — 库存计算核心 (Week 3-4)

- 实现库存计算引擎
- 实现销量输入（逐日 + 批量）
- 实现库存校正机制
- 实现断货检测与预警
- 编写库存引擎单元测试（高覆盖率）

### Phase 3 — 图表与分析 (Week 5-6)

- 实现库存/销量趋势图
- 实现周转时间计算服务
- 实现周转时间展示模块
- 图表交互优化（缩放、tooltip、标记）

### Phase 4 — 集成与打磨 (Week 7-8)

- 前后端联调
- 错误处理与边界情况处理
- 性能优化（Redis 缓存库存计算结果）
- UI 打磨与响应式适配
- 编写 Docker 配置文件
- 部署文档与运维说明

---

## 10. 附录

### 附录 A — 环境变量清单

```env
# .env.example

# 数据库
DATABASE_URL=postgresql+asyncpg://postgres:yourpassword@localhost:5432/replenishment
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10

# Redis
REDIS_URL=redis://localhost:6379/0

# 应用
APP_HOST=0.0.0.0
APP_PORT=8000
APP_ENV=development    # development | production
DEBUG=true
LOG_LEVEL=INFO

# CORS
CORS_ORIGINS=["http://localhost:5173"]

# 安全
SECRET_KEY=your-secret-key-here
```

### 附录 B — 关键术语表

| 术语 | 英文 | 说明 |
|------|------|------|
| 发货计划 | Shipment Plan | 一次完整的发货行动，包含多个批次 |
| 发货批次 | Shipment Batch | 同一天发出的一批货物 |
| 货件 | Shipment Unit | 最小物流单位，对应一个仓库的一次发货 |
| 分仓 | Warehouse Split | 将货物按比例分配到不同地区仓库 |
| 期初库存 | Opening Stock | 某日开始时的可用库存 |
| 期末库存 | Closing Stock | 某日结束时的剩余库存 |
| 库存校正 | Inventory Override | 强制覆写某日的期初库存值 |
| 断货 | Stockout | 库存不足以满足当日销量需求 |
| 库存周转时间 | Inventory Turnover Duration | 从发货到售罄的平均天数 |
| FIFO | First In, First Out | 先进先出，先到的货优先消耗 |

### 附录 C — 依赖版本清单

**后端 (Python 3.11+):**

```
fastapi>=0.110.0
uvicorn>=0.29.0
sqlalchemy>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0
pydantic>=2.6.0
pydantic-settings>=2.2.0
redis>=5.0.0
httpx>=0.27.0    # 测试用
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

**前端 (Node 20+):**

```json
{
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "typescript": "^5.4.0",
    "vite": "^5.4.0",
    "antd": "^5.16.0",
    "recharts": "^2.12.0",
    "axios": "^1.7.0",
    "dayjs": "^1.11.0",
    "react-router-dom": "^6.23.0"
}
```
