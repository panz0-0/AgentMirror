# fitMirror Backend

Python API 服务，使用 [uv](https://docs.astral.sh/uv/) 管理依赖与虚拟环境。

完整文档见仓库根目录 [README.md](../README.md)。

## 快速启动

```bash
# 安装 uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync
cp .env.example .env   # 配置 MYSQL_* 与 LLM Key

# 首次：建表并导入演示数据（需 MySQL 已启动）
# 推荐 — 完整演示环境（含客服会话、出图记录，配合仓库 storage/）:
uv run python scripts/restore_demo_environment.py

# 或 — 仅基础 SKU + 知识库:
# uv run python scripts/init_mysql.py

# 启动 API
uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

虚拟环境位于本目录下的 `.venv/`。数据库仅支持 **MySQL**。
