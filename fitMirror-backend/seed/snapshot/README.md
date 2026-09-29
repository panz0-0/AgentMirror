# 演示环境快照

本目录包含从作者本地环境导出的 **MySQL 演示数据**，配合仓库内的 `storage/` 目录一起使用。

## 一键恢复（推荐）

```bash
cd fitMirror-backend
cp .env.example .env          # 配置 MySQL 连接
uv sync
uv run python scripts/restore_demo_environment.py
```

将自动：

1. 创建表结构
2. 导入 `demo_db.json`（6 个 SKU、知识库、客服会话、生成任务记录等）
3. 使用仓库内已有的 `storage/`（商品图、AI 生成图、workspace、向量索引）

## 维护者更新快照

本地调试出满意效果后，重新导出并提交：

```bash
uv run python scripts/export_demo_snapshot.py
git add seed/snapshot/demo_db.json storage/
git commit -m "chore: refresh demo snapshot"
```

## 快照内容（当前版本）

| 表 | 说明 |
|----|------|
| `skus` | 6 款演示商品 |
| `sku_artifacts` / `generation_jobs` / `generated_images` | 运营出图流水线记录 |
| `knowledge_docs` | 知识库文档索引 |
| `chat_sessions` / `chat_messages` | 客服演示会话 |
| `user_profiles` | 用户身材数据 |
