# fitMirror 首次推送到 Gitee 笔记

> 仓库地址：https://gitee.com/yuyu_666/fit-mirror  
> 记录时间：2026-07-12

本文记录将本地 `fitMirror` 项目首次开源推送到 Gitee 的完整步骤，包括：**保护 API Key**、**上传演示数据**、**初始化脚本**。

---

## 一、推送前准备

### 1. 确认本地环境

- 项目路径：`D:\Project\python\fitMirror`
- 后端：`fitMirror-backend/`（uv + MySQL）
- 前端：`frontend/`（Vue 3 + Vite）
- 本地配置：`fitMirror-backend/.env`（含 API Key，**绝不提交**）

### 2. 在 Gitee 创建空仓库

1. 登录 [Gitee](https://gitee.com)
2. 新建仓库，名称例如：`fit-mirror`
3. 得到远程地址：

```
https://gitee.com/yuyu_666/fit-mirror.git
```

---

## 二、配置 `.gitignore`（不上传敏感信息）

原则：**只忽略敏感和可再生的文件，不动本地 `.env`**。

根目录 `.gitignore` 关键规则：

```gitignore
# 敏感配置（本地 .env 保持原样，不提交）
.env
.env.*
!.env.example
**/.env
**/.env.local

fitMirror-backend/.venv/
fitMirror-backend/.env
frontend/node_modules/
frontend/dist/
.idea/
```

**要提交：**

- `fitMirror-backend/.env.example`（Key 留空，作模板）
- `fitMirror-backend/storage/`（演示图片、生成图、workspace）
- `fitMirror-backend/seed/snapshot/demo_db.json`（MySQL 演示数据快照）
- 源码、README、`docs/images/` 示例截图

**不要提交：**

- `fitMirror-backend/.env`（真实 API Key）
- `.venv/`、`node_modules/`
- 本地 IDE 配置

---

## 三、准备演示环境数据（可选但推荐）

为了让别人 clone 后开箱即用，额外做了两件事：

### 1. 导出 MySQL 快照

```bash
cd fitMirror-backend
uv run python scripts/export_demo_snapshot.py
```

生成文件：`seed/snapshot/demo_db.json`

包含：SKU、知识库、客服会话、出图任务、用户身材等表数据。

### 2. 保留 `storage/` 目录

`storage/` 约 80MB，含：

| 目录 | 内容 |
|------|------|
| `uploads/` | 商品图、客服聊天图片 |
| `generated/` | AI 生成主图 |
| `workspaces/` | 运营分析缓存 |
| `vectors/` | 知识库向量索引 |
| `knowledge/` | 知识库文件副本 |

恢复脚本（给别人用）：

```bash
uv run python scripts/restore_demo_environment.py
```

---

## 四、Git 初始化与首次提交

项目最初不是 Git 仓库，需先初始化：

```powershell
cd D:\Project\python\fitMirror

# 初始化
git init
git checkout -b main

# 暂存所有文件（.gitignore 会自动排除 .env 等）
git add -A

# 检查：确认 .env 不在列表里
git status
# 应只看到 .env.example，不应有 fitMirror-backend/.env

# 首次提交
git commit -m "Initial open-source release: fitMirror AI customer service and ops workspace"
```

> **Windows 提示**：若 `git commit` 报 `unknown option trailer`，可用完整路径：
>
> ```powershell
> & "C:\Program Files\Git\mingw64\bin\git.exe" commit -m "提交说明"
> ```

---

## 五、关联远程并推送

```powershell
git remote add origin https://gitee.com/yuyu_666/fit-mirror.git

# 首次推送
git push -u origin main
```

推送成功后访问：https://gitee.com/yuyu_666/fit-mirror

---

## 六、第二次推送（补充演示数据）

后续补充 `storage/` + MySQL 快照 + 恢复脚本后，再次提交：

```powershell
cd D:\Project\python\fitMirror

git add -A
git status   # 再次确认无 .env

git commit -m "Add demo storage snapshot and restore script for full local experience"
git push origin main
```

---

## 七、别人如何克隆体验

```bash
git clone https://gitee.com/yuyu_666/fit-mirror.git
cd fit-mirror/fitMirror-backend

uv sync
cp .env.example .env
# 编辑 .env：填 MYSQL_* 和 LLM API Key

# MySQL 建库
# CREATE DATABASE fitmirror CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# 一键恢复演示环境
uv run python scripts/restore_demo_environment.py

# 启动
uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
cd ../frontend
npm install
npm run dev
# 打开 http://localhost:5173/chat
```

---

## 八、日常更新推送流程

```powershell
cd D:\Project\python\fitMirror

# 1. 若有新演示数据，先导出
cd fitMirror-backend
uv run python scripts/export_demo_snapshot.py
cd ..

# 2. 提交推送
git add -A
git status                    # 每次推送前检查 .env 未入列
git commit -m "描述本次改动"
git push origin main
```

---

## 九、安全检查清单

推送前逐项确认：

- [ ] `git status` 中没有 `fitMirror-backend/.env`
- [ ] `git status` 中没有 `**/.env`（除 `.env.example`）
- [ ] 代码 / JSON / MD 中无 `sk-` 开头的真实 Key
- [ ] README 里用的是占位符 `your_key`，不是真实 Key

本地验证命令：

```powershell
git ls-files | findstr "\.env"
# 应只输出：fitMirror-backend/.env.example
```

---

## 十、本次推送文件概览

| 类别 | 说明 |
|------|------|
| 源码 | `fitMirror-backend/app/`、`frontend/src/` |
| 文档 | `README.md`、`docs/images/` 三张截图 |
| 配置模板 | `fitMirror-backend/.env.example` |
| 演示存储 | `fitMirror-backend/storage/`（约 160 文件） |
| 数据库快照 | `fitMirror-backend/seed/snapshot/demo_db.json` |
| 脚本 | `restore_demo_environment.py`、`export_demo_snapshot.py` |
| 许可 | `LICENSE`（MIT） |

---

## 十一、常见问题

### Q：端口 8000 被占用，推送后别人拉代码要不要管？

不用。那是本地运行问题，与 Git 无关。别人 clone 后自己起服务即可。

### Q：`.env` 会被改掉吗？

不会。`.gitignore` 只阻止 Git 跟踪，不会修改本地文件。

### Q：storage 太大，推送很慢？

正常。首次约 80MB，Gitee 可接受。之后只有增量变更。

### Q：如何刷新演示快照？

```bash
cd fitMirror-backend
uv run python scripts/export_demo_snapshot.py
git add seed/snapshot/demo_db.json storage/
git commit -m "chore: refresh demo snapshot"
git push
```

---

## 十二、相关链接

- Gitee 仓库：https://gitee.com/yuyu_666/fit-mirror
- GitHub 仓库：https://github.com/15170719135/fit-mirror
- 项目 README：仓库根目录 `README.md`
- 快照说明：`fitMirror-backend/seed/snapshot/README.md`

---

## 十三、同时推送到 GitHub

Gitee 已作为 `origin`，GitHub 建议单独加为 `github` 远程：

```powershell
cd D:\Project\python\fitMirror

# 添加 GitHub 远程（只需一次）
git remote add github https://github.com/15170719135/fit-mirror.git

# 推送到 GitHub（需登录，见下方说明）
git push -u github main
```

### GitHub 登录说明

GitHub 已不支持账号密码推送，需使用 **Personal Access Token (PAT)**：

1. 打开 GitHub → Settings → Developer settings → Personal access tokens
2. 生成 Token，勾选 `repo` 权限
3. 执行 `git push -u github main` 时：
   - **Username**：你的 GitHub 用户名
   - **Password**：粘贴 Token（不是登录密码）

### 日常双端同步

```powershell
git push origin main    # Gitee
git push github main    # GitHub
```

或一次推两个：

```powershell
git push origin main; git push github main
```
