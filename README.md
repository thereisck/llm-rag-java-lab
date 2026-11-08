# 向量检索 + SQL 过滤的混合召回实验（Java / Spring Boot）

每周一个可复现的实验，跑出一组真数字。**Java 团队的 LLM 应用上线手册**的代码仓库。

## 技术栈

| 层 | 选型 | 为什么 |
|---|---|---|
| 向量库 | PostgreSQL 18 + pgvector 0.8.7 | 混合检索里「先 SQL 过滤再向量召回」在 pg 里最顺，MySQL 底子迁移成本最低 |
| Embedding | `BAAI/bge-large-zh-v1.5`（1024 维，硅基流动） | 中文效果好、512 token 窗口足够单段检索 |
| 应用层 | Spring Boot 3 + LangChain4j | 企业存量系统的主场，不是 Python |

## 目录

```
seed/    语料切分、向量灌库、口径校验脚本（Python，数据准备用，不属于应用层）
sql/     建表与索引
data/    语料与评测集（含个人文本，不进库）
```

## 快速开始

```bash
docker run -d --name raglab-pg -p 5432:5432 -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=raglab -v raglab_pgdata:/var/lib/postgresql \
  --restart unless-stopped pgvector/pgvector:pg18

psql -h localhost -U postgres -d raglab -f sql/schema.sql

cp seed/.env.example seed/.env      # 填 SILICONFLOW_API_KEY
python -X utf8 seed/check_embed.py  # 先验维度和窗口，再灌库
python -X utf8 seed/build_seed.py
python -X utf8 seed/embed_all.py
```

## 一个已经踩过的坑

切分上限**不能按字数设**。中文约 **1.34 字/token**，bge 系列 512 token 窗口 ≈ 680 字，685 字直接 400（code 20015）拒绝，不是静默截断。详见 `seed/probe_token_limit.py`。

## 进度

| 周 | 实验 | 状态 |
|---|---|---|
| W01 | 建立检索评测基线与基线数字 | 进行中 |
| W02–W12 | 切分 / 混合检索 / 重排 / 成本 / 可靠性 | 待开始 |
