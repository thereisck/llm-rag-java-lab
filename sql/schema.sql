-- W01 建表：向量列 + 评测集
-- 起容器：见 README
-- 注意：pgvector 镜像里的 CREATE EXTENSION 只对初始化那一刻的空库生效，
--       docker rm 重建容器或换数据卷之后必须重新执行本文件。

CREATE EXTENSION IF NOT EXISTS vector;

-- 语料分块。embedding 维度与 embedding 模型绑定，换模型必须 ALTER COLUMN。
CREATE TABLE documents (
  id        bigserial PRIMARY KEY,
  content   text NOT NULL,
  metadata  jsonb NOT NULL DEFAULT '{}'::jsonb,
  embedding vector(1024)
);

-- 评测集：一行一个标准答案
--   expected_chunk_id  标准答案落在哪个 chunk —— W01/W02 的 Evaluator 只读这个
--   expected_doc_id    文档级命中，W02 重新切分、chunk id 整体位移之后才启用
CREATE TABLE eval_set (
  id                  bigserial PRIMARY KEY,
  question            text NOT NULL,
  expected_doc_id     bigint,
  expected_chunk_id   bigint,
  note                text
);

-- 向量索引用到再建。W01 基线刻意用 seq scan，建了索引 W03/W04 的数字就不可比。
-- CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);
