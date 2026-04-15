# Amazon Replenishment Planning System

首版已按需求文档启动，当前仓库包含：

- `backend/`: FastAPI + SQLAlchemy 异步后端，已落发货计划、销售规划、库存计算、周转分析的首版领域代码与 API。
- `frontend/`: React + TypeScript + Ant Design 管理台骨架，已完成发货规划、销售规划、图表面板、周转分析 4 个页面的首版交互。
- 根目录配置：`.env.example`、`Makefile`、`.gitignore`。

## 当前实现范围

### 后端

- 发货计划 CRUD
- 三仓配置校验与货件自动拆分
- 销售规划 CRUD
- 逐日库存计算、override 正向传播、断货检测
- 周转分析与图表数据接口
- 纯算法单元测试骨架

### 前端

- 基础布局与路由
- 发货计划编辑器与货件预览
- 销量批量设置与库存明细演示
- 库存/销量趋势图
- 周转分析列表

## 本地启动

### 1. 准备环境变量

```bash
cp .env.example .env
```

### 2. 启动后端

```bash
cd backend
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

## API 基础路径

- `/api/v1/shipment-plans`
- `/api/v1/sales-plans`
- `/api/v1/sales-plans/{id}/calculate`
- `/api/v1/sales-plans/{id}/chart-data`
- `/api/v1/sales-plans/{id}/turnover`
- `/api/v1/sales-plans/{id}/stockout-warnings`

## 下一步建议

1. 安装依赖并连接真实 PostgreSQL / Redis。
2. 增加 Alembic 迁移。
3. 把前端 mock 数据切换到真实 API。
4. 补充 Docker 与初始化脚本。
