import { useMemo, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, Area } from "recharts";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  ConfigProvider,
  DatePicker,
  Divider,
  Input,
  InputNumber,
  Layout,
  Menu,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography
} from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import {
  buildShipmentUnitPreview,
  calculateInventoryPreview,
  createBatch,
  defaultSalesEntries,
  defaultShipmentDraft,
  nthUpcomingSaturday,
  sampleArrivals,
  sampleChartData,
  sampleTurnoverCards
} from "./mockData";
import type { BatchDraft, DailySalesDraft, InventoryDayView, ShipmentDraft, ShipmentUnitPreview } from "./types";

const { Header, Sider, Content } = Layout;
const { Title, Paragraph, Text } = Typography;

function ShipmentPage() {
  const [draft, setDraft] = useState<ShipmentDraft>(defaultShipmentDraft);

  const allocationTotal = useMemo(
    () =>
      Object.values(draft.warehouse_config).reduce(
        (total, item) => total + item.allocation_pct,
        0
      ),
    [draft.warehouse_config]
  );
  const previewUnits = useMemo(() => buildShipmentUnitPreview(draft), [draft]);
  const batchTotal = useMemo(
    () => draft.batches.reduce((total, batch) => total + batch.batch_quantity, 0),
    [draft.batches]
  );

  const updateBatch = (targetId: string, patch: Partial<BatchDraft>) => {
    setDraft((current) => ({
      ...current,
      batches: current.batches.map((batch) =>
        batch.id === targetId ? { ...batch, ...patch } : batch
      )
    }));
  };

  const setSaturday = (targetId: string, value: Dayjs | null) => {
    if (!value) return;
    const next = value.day() === 6 ? value : value.day(6).isAfter(value, "day") ? value.day(6) : value.add(1, "week").day(6);
    updateBatch(targetId, { ship_date: next.format("YYYY-MM-DD") });
  };

  return (
    <Space direction="vertical" size={20} style={{ width: "100%" }}>
      <div>
        <Title level={2}>发货规划</Title>
        <Paragraph type="secondary">
          先用前端状态把发货计划、三仓配置和货件预览串起来。后续直接切到后端
          `/api/v1/shipment-plans` 接口即可。
        </Paragraph>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <Card className="glass-card" title="计划基础信息">
            <Row gutter={[12, 12]}>
              <Col span={24}>
                <Text>计划名称</Text>
                <Input
                  value={draft.plan_name}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, plan_name: event.target.value }))
                  }
                />
              </Col>
              <Col xs={24} md={12}>
                <Text>SKU</Text>
                <Input
                  value={draft.sku}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, sku: event.target.value }))
                  }
                />
              </Col>
              <Col xs={24} md={12}>
                <Text>ASIN</Text>
                <Input
                  value={draft.asin}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, asin: event.target.value }))
                  }
                />
              </Col>
              <Col xs={24} md={12}>
                <Text>总发货量</Text>
                <InputNumber
                  min={0}
                  style={{ width: "100%" }}
                  value={draft.total_quantity}
                  onChange={(value) =>
                    setDraft((current) => ({
                      ...current,
                      total_quantity: Number(value ?? current.total_quantity)
                    }))
                  }
                />
              </Col>
              <Col xs={24} md={12}>
                <Text>批次数</Text>
                <InputNumber style={{ width: "100%" }} value={draft.batches.length} disabled />
              </Col>
            </Row>
          </Card>
        </Col>

        <Col xs={24} xl={10}>
          <Card className="glass-card" title="仓库配置">
            <Space direction="vertical" style={{ width: "100%" }} size={12}>
              {(["west", "central", "east"] as const).map((region) => (
                <div key={region} className="warehouse-row">
                  <div>
                    <Text strong>{region === "west" ? "美西" : region === "central" ? "美中" : "美东"}</Text>
                  </div>
                  <InputNumber
                    min={0}
                    max={100}
                    addonAfter="%"
                    value={draft.warehouse_config[region].allocation_pct}
                    onChange={(value) =>
                      setDraft((current) => ({
                        ...current,
                        warehouse_config: {
                          ...current.warehouse_config,
                          [region]: {
                            ...current.warehouse_config[region],
                            allocation_pct: Number(value ?? 0)
                          }
                        }
                      }))
                    }
                  />
                  <InputNumber
                    min={1}
                    addonAfter="天"
                    value={draft.warehouse_config[region].transit_days}
                    onChange={(value) =>
                      setDraft((current) => ({
                        ...current,
                        warehouse_config: {
                          ...current.warehouse_config,
                          [region]: {
                            ...current.warehouse_config[region],
                            transit_days: Number(value ?? 1)
                          }
                        }
                      }))
                    }
                  />
                </div>
              ))}
              <Alert
                type={allocationTotal === 100 ? "success" : "error"}
                message={`分配比例合计 ${allocationTotal}%`}
                description={allocationTotal === 100 ? "可以提交。" : "必须调整到 100% 才能保存计划。"}
                showIcon
              />
            </Space>
          </Card>
        </Col>
      </Row>

      <Card
        className="glass-card"
        title="批次管理"
        extra={
          <Space>
            <Button onClick={() => setDraft(defaultShipmentDraft)}>重置示例</Button>
            <Button
              type="primary"
              onClick={() =>
                setDraft((current) => {
                  const nextIndex = current.batches.length + 1;
                  return {
                    ...current,
                    batch_count: nextIndex,
                    batches: [...current.batches, createBatch(nextIndex)]
                  };
                })
              }
            >
              新增批次
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          {draft.batches.map((batch, index) => (
            <div key={batch.id} className="batch-card">
              <div className="batch-card__header">
                <div>
                  <Text strong>{`批次 ${batch.batch_index}`}</Text>
                  <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                    只允许选择周六发货，预计到货会随仓库时效自动联动。
                  </Paragraph>
                </div>
                <Button
                  danger
                  ghost
                  disabled={draft.batches.length <= 1}
                  onClick={() =>
                    setDraft((current) => ({
                      ...current,
                      batch_count: current.batches.length - 1,
                      batches: current.batches
                        .filter((item) => item.id !== batch.id)
                        .map((item, itemIndex) => ({ ...item, batch_index: itemIndex + 1 }))
                    }))
                  }
                >
                  删除
                </Button>
              </div>

              <Row gutter={[12, 12]}>
                <Col xs={24} md={12}>
                  <Text>发货日期</Text>
                  <div className="date-stack">
                    <DatePicker
                      style={{ width: "100%" }}
                      value={dayjs(batch.ship_date)}
                      disabledDate={(current) => !!current && current.day() !== 6}
                      onChange={(value) => setSaturday(batch.id, value)}
                    />
                    <Space wrap>
                      {[0, 1, 2].map((offset) => (
                        <Button
                          key={offset}
                          size="small"
                          onClick={() =>
                            updateBatch(batch.id, {
                              ship_date: nthUpcomingSaturday(offset).format("YYYY-MM-DD")
                            })
                          }
                        >
                          {offset === 0 ? "本周六" : offset === 1 ? "下周六" : "两周后周六"}
                        </Button>
                      ))}
                    </Space>
                  </div>
                </Col>
                <Col xs={24} md={12}>
                  <Text>批次数量</Text>
                  <InputNumber
                    min={1}
                    style={{ width: "100%" }}
                    value={batch.batch_quantity}
                    onChange={(value) =>
                      updateBatch(batch.id, { batch_quantity: Number(value ?? batch.batch_quantity) })
                    }
                  />
                </Col>
              </Row>

              <Divider />

              <Row gutter={[12, 12]}>
                {previewUnits
                  .filter((unit) => unit.batch_index === batch.batch_index)
                  .map((unit) => (
                    <Col xs={24} md={8} key={unit.key}>
                      <Card size="small" className="unit-preview">
                        <Text strong>{unit.region_label}</Text>
                        <div>{unit.quantity} 件</div>
                        <Text type="secondary">
                          {unit.transit_days} 天 / 到货 {dayjs(unit.arrival_date).format("MM/DD")}
                        </Text>
                      </Card>
                    </Col>
                  ))}
              </Row>
              {index !== draft.batches.length - 1 ? <Divider /> : null}
            </div>
          ))}
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={7}>
          <Card className="glass-card">
            <Statistic title="批次合计" value={batchTotal} suffix="件" />
            <Statistic title="计划总量" value={draft.total_quantity} suffix="件" />
            <Statistic title="预览货件数" value={previewUnits.length} suffix="个" />
          </Card>
        </Col>
        <Col xs={24} xl={17}>
          <Card className="glass-card" title="货件预览">
            {batchTotal !== draft.total_quantity ? (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message="批次总量与计划总量不一致"
                description="保存到后端前需要先对齐两者，避免校验失败。"
              />
            ) : null}
            <Table<ShipmentUnitPreview>
              rowKey="key"
              pagination={false}
              dataSource={previewUnits}
              columns={[
                { title: "批次", dataIndex: "batch_index" },
                { title: "仓库", dataIndex: "region_label" },
                { title: "数量", dataIndex: "quantity" },
                { title: "发货日期", dataIndex: "ship_date" },
                { title: "物流时效", dataIndex: "transit_days", render: (value) => `${value} 天` },
                { title: "预计到货", dataIndex: "arrival_date" }
              ]}
            />
          </Card>
        </Col>
      </Row>
    </Space>
  );
}

function SalesPage() {
  const [entries, setEntries] = useState<DailySalesDraft[]>(defaultSalesEntries);
  const [initialInventory, setInitialInventory] = useState(500);
  const [rangeValue, setRangeValue] = useState<[Dayjs | null, Dayjs | null]>([
    dayjs(defaultSalesEntries[0].date),
    dayjs(defaultSalesEntries[6].date)
  ]);
  const [rangeSales, setRangeSales] = useState(55);

  const inventoryRows = useMemo(
    () =>
      calculateInventoryPreview(initialInventory, entries, sampleArrivals, {
        [entries[8].date]: 620
      }),
    [entries, initialInventory]
  );

  const stockoutDays = inventoryRows.filter((row) => row.is_stockout).length;

  const applyRange = () => {
    if (!rangeValue[0] || !rangeValue[1]) return;
    setEntries((current) =>
      current.map((entry) => {
        const currentDate = dayjs(entry.date);
        if (
          currentDate.isBefore(rangeValue[0]!, "day") ||
          currentDate.isAfter(rangeValue[1]!, "day")
        ) {
          return entry;
        }
        return { ...entry, planned_sales: rangeSales };
      })
    );
  };

  return (
    <Space direction="vertical" size={20} style={{ width: "100%" }}>
      <div>
        <Title level={2}>销售与库存规划</Title>
        <Paragraph type="secondary">
          页面先基于同一套库存引擎规则做前端演示，后续可直接替换为后端
          `/calculate`、`/overrides` 等接口响应。
        </Paragraph>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card className="glass-card" title="基础设置">
            <Space direction="vertical" style={{ width: "100%" }}>
              <div>
                <Text>首日期初库存</Text>
                <InputNumber
                  min={0}
                  style={{ width: "100%" }}
                  value={initialInventory}
                  onChange={(value) => setInitialInventory(Number(value ?? 0))}
                />
              </div>
              <Alert
                type="info"
                showIcon
                message="示例中已预置 1 个库存校正"
                description={`${entries[8].date} 的期初库存被校正为 620，用于演示 override 正向传播。`}
              />
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card className="glass-card" title="批量设置销量">
            <Row gutter={[12, 12]}>
              <Col xs={24} md={12}>
                <Text>日期范围</Text>
                <DatePicker.RangePicker
                  style={{ width: "100%" }}
                  value={rangeValue}
                  onChange={(value) =>
                    setRangeValue(value ?? [rangeValue[0], rangeValue[1]])
                  }
                />
              </Col>
              <Col xs={24} md={6}>
                <Text>统一日销</Text>
                <InputNumber
                  min={0}
                  style={{ width: "100%" }}
                  value={rangeSales}
                  onChange={(value) => setRangeSales(Number(value ?? 0))}
                />
              </Col>
              <Col xs={24} md={6} className="align-end">
                <Button type="primary" block onClick={applyRange}>
                  应用到日期范围
                </Button>
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card className="glass-card">
            <Statistic title="总计划销量" value={inventoryRows.reduce((sum, row) => sum + row.planned_sales, 0)} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="glass-card">
            <Statistic title="断货天数" value={stockoutDays} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="glass-card">
            <Statistic title="期末库存" value={inventoryRows[inventoryRows.length - 1]?.closing_stock ?? 0} />
          </Card>
        </Col>
      </Row>

      <Card className="glass-card" title="每日库存明细">
        <Table<InventoryDayView>
          rowKey="date"
          pagination={{ pageSize: 8 }}
          dataSource={inventoryRows}
          columns={[
            {
              title: "日期",
              dataIndex: "date"
            },
            {
              title: "规划销量",
              dataIndex: "planned_sales",
              render: (value: number, row: InventoryDayView) => (
                <InputNumber
                  min={0}
                  value={value}
                  onChange={(nextValue) =>
                    setEntries((current) =>
                      current.map((entry) =>
                        entry.date === row.date
                          ? { ...entry, planned_sales: Number(nextValue ?? 0) }
                          : entry
                      )
                    )
                  }
                />
              )
            },
            { title: "期初库存", dataIndex: "opening_stock" },
            { title: "到货量", dataIndex: "arrivals" },
            { title: "可用库存", dataIndex: "available_stock" },
            { title: "实际消耗", dataIndex: "actual_sales" },
            { title: "期末库存", dataIndex: "closing_stock" },
            {
              title: "状态",
              dataIndex: "is_stockout",
              render: (value: boolean, row) =>
                value ? (
                  <Tag color="error">断货</Tag>
                ) : row.has_override ? (
                  <Tag color="processing">有校正</Tag>
                ) : (
                  <Tag color="success">正常</Tag>
                )
            }
          ]}
        />
      </Card>
    </Space>
  );
}

function ChartsPage() {
  return (
    <Space direction="vertical" size={20} style={{ width: "100%" }}>
      <div>
        <Title level={2}>图表面板</Title>
        <Paragraph type="secondary">
          组合图表按文档里的结构展示库存面积、销量柱状、到货折线和断货标记。
        </Paragraph>
      </div>

      <Card className="glass-card" title="库存与销量趋势">
        <div className="chart-shell">
          <ResponsiveContainer width="100%" height={420}>
            <ComposedChart data={sampleChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#cfd7e2" />
              <XAxis dataKey="date" tick={{ fill: "#355070", fontSize: 12 }} />
              <YAxis yAxisId="left" tick={{ fill: "#355070" }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fill: "#355070" }} />
              <Tooltip />
              <Legend />
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="opening_stock"
                fill="#c5d8f7"
                stroke="#2f5d8a"
                name="期初库存"
              />
              <Bar yAxisId="right" dataKey="planned_sales" fill="#588157" name="规划销量" />
              <Bar yAxisId="right" dataKey="actual_sales" fill="#d97b29" name="实际销量" />
              <Line yAxisId="left" type="monotone" dataKey="arrivals" stroke="#b23a48" name="到货量" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </Space>
  );
}

function TurnoverPage() {
  return (
    <Space direction="vertical" size={20} style={{ width: "100%" }}>
      <div>
        <Title level={2}>周转分析</Title>
        <Paragraph type="secondary">
          列表先按文档约定输出货件命名、售罄状态和平均周转天数，方便后续直接映射后端
          `/turnover`。
        </Paragraph>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card className="glass-card">
            <Statistic
              title="已售罄货件"
              value={sampleTurnoverCards.filter((item) => item.fully_sold).length}
            />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="glass-card">
            <Statistic
              title="销售中货件"
              value={sampleTurnoverCards.filter((item) => !item.fully_sold).length}
            />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="glass-card">
            <Statistic
              title="平均周转"
              value={(
                sampleTurnoverCards.reduce((sum, item) => sum + (item.avg_turnover_days ?? 0), 0) /
                sampleTurnoverCards.length
              ).toFixed(1)}
              suffix="天"
            />
          </Card>
        </Col>
      </Row>

      <Card className="glass-card" title="货件周转列表">
        <Table
          rowKey="unit_id"
          pagination={false}
          dataSource={sampleTurnoverCards}
          columns={[
            { title: "货件", dataIndex: "unit_label" },
            { title: "发货", dataIndex: "ship_date" },
            { title: "到货", dataIndex: "arrival_date" },
            { title: "数量", dataIndex: "total_pieces" },
            {
              title: "状态",
              dataIndex: "fully_sold",
              render: (value: boolean) =>
                value ? <Tag color="success">已售罄</Tag> : <Tag color="warning">销售中</Tag>
            },
            {
              title: "已售/剩余",
              render: (_, row) => `${row.sold_pieces}/${row.remaining_pieces}`
            },
            {
              title: "售罄日",
              dataIndex: "sell_through_date",
              render: (value: string | null) => value ?? "进行中"
            },
            {
              title: "平均周转",
              dataIndex: "avg_turnover_days",
              render: (value: number | null) => (value ? `${value} 天` : "待计算")
            }
          ]}
        />
      </Card>
    </Space>
  );
}

function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: "#2f5d8a",
          colorSuccess: "#588157",
          colorWarning: "#d97b29",
          colorError: "#b23a48",
          borderRadius: 18,
          fontFamily: "'IBM Plex Sans', 'Noto Sans SC', sans-serif"
        }
      }}
    >
      <AntdApp>
        <Layout className="app-shell">
          <Sider width={280} breakpoint="lg" collapsedWidth={0} className="app-sider">
            <div className="brand-block">
              <div className="brand-mark">ARP</div>
              <div>
                <div className="brand-title">Amazon Replenishment</div>
                <div className="brand-subtitle">Planning System</div>
              </div>
            </div>
            <Menu
              theme="light"
              mode="inline"
              selectedKeys={[location.pathname]}
              items={[
                { key: "/shipments", label: "发货规划" },
                { key: "/sales", label: "销售规划" },
                { key: "/charts", label: "图表面板" },
                { key: "/turnover", label: "周转分析" }
              ]}
              onClick={({ key }) => navigate(key)}
            />
          </Sider>
          <Layout>
            <Header className="app-header">
              <div>
                <Text strong>阶段进度</Text>
                <div className="header-copy">Phase 1 基础框架已启动，页面先使用 mock 数据验证交互。</div>
              </div>
            </Header>
            <Content className="app-content">
              <Routes>
                <Route path="/" element={<Navigate to="/shipments" replace />} />
                <Route path="/shipments" element={<ShipmentPage />} />
                <Route path="/sales" element={<SalesPage />} />
                <Route path="/charts" element={<ChartsPage />} />
                <Route path="/turnover" element={<TurnoverPage />} />
              </Routes>
            </Content>
          </Layout>
        </Layout>
      </AntdApp>
    </ConfigProvider>
  );
}

export default AppShell;
