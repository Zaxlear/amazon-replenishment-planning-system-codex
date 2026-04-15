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

配置会优先读取仓库根目录的 `.env`，因此即使你在 `backend/` 目录里启动 `uvicorn`，也不会丢失根目录环境变量。

默认不会在启动时自动建表。
如果你希望在开发环境启动时自动执行 `Base.metadata.create_all()`，显式设置：

```bash
AUTO_INIT_MODELS=true uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
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

## Debian 上看到 `ConnectionRefusedError: [Errno 111]`

这不是 FastAPI 本身的问题，而是 PostgreSQL 连接被拒绝了，常见原因只有两类：

- `DATABASE_URL` 仍然指向默认的 `localhost:5432`，但本机 PostgreSQL 没启动。
- PostgreSQL 在别的主机或端口上运行，`DATABASE_URL` 配错了。

可以先检查：

```bash
echo $DATABASE_URL
ss -ltn | grep 5432
systemctl status postgresql
```

如果只是想先让 API 进程起来，不要开启 `AUTO_INIT_MODELS=true`。如果数据库本身不可达，依赖数据库的接口仍然会在请求时失败。

## 下一步建议

1. 安装依赖并连接真实 PostgreSQL / Redis。
2. 增加 Alembic 迁移。
3. 把前端 mock 数据切换到真实 API。
4. 补充 Docker 与初始化脚本。
