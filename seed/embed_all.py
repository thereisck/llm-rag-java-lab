#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
W01 · 把 documents.embedding 灌满

模型：BAAI/bge-large-zh-v1.5（1024 维，对齐 vector(1024)）
只处理 embedding IS NULL 的行，可重复跑（断点续传）。

用法：
    python -X utf8 实验/seed/embed_all.py            # 全部灌
    python -X utf8 实验/seed/embed_all.py --limit 32 # 先试 32 条
"""
import csv
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ["docker", "exec", "-i", "raglab-pg", "psql", "-U", "postgres", "-d", "raglab"]
BATCH = 16


def load_env():
    env = {}
    path = os.path.join(HERE, ".env")
    for line in open(path, encoding="utf-8-sig"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def psql(sql, capture=False):
    r = subprocess.run(PSQL + ["-v", "ON_ERROR_STOP=1", "-f", "-"],
                       input=sql, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("[SQL FAIL] %s" % r.stderr.strip()[:800])
    return r.stdout if capture else ""


def pending(limit=None):
    lim = (" limit %d" % limit) if limit else ""
    sql = ("\\copy (select id, content from documents where embedding is null "
           "order by id%s) to stdout with (format csv)" % lim)
    r = subprocess.run(PSQL + ["-c", sql], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("[READ FAIL] %s" % r.stderr.strip()[:500])
    return [(int(a), b) for a, b in csv.reader(io.StringIO(r.stdout))]


def embed(base, key, model, texts):
    body = json.dumps({"model": model, "input": texts}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/embeddings", data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    env = load_env()
    key = env["SILICONFLOW_API_KEY"]
    base = env.get("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
    model = env.get("EMBED_MODEL", "BAAI/bge-large-zh-v1.5")

    rows = pending(limit)
    print("待灌 %d 条（model=%s，batch=%d）" % (len(rows), model, BATCH))
    if not rows:
        print("没有 NULL 行，已灌满。")
        return

    t0 = time.perf_counter()
    stat = {"done": 0, "tokens": 0, "truncated": [], "dead": []}

    def write(chunk, data):
        sqls = []
        for (rid, _), d in zip(chunk, data):
            lit = "[" + ",".join("%.6f" % x for x in d["embedding"]) + "]"
            sqls.append("UPDATE documents SET embedding = '%s'::vector WHERE id = %d;" % (lit, rid))
        psql("\n".join(sqls))
        stat["done"] += len(chunk)
        print("  %4d/%d  %.1fs  token=%d" % (stat["done"], len(rows),
                                             time.perf_counter() - t0, stat["tokens"]))

    def run(chunk):
        """失败即二分：400 只说明这一批里有人超窗口，bisect 到单条再截断"""
        texts = [t for _, t in chunk]
        try:
            payload = embed(base, key, model, texts)
            data = sorted(payload["data"], key=lambda d: d["index"])
            stat["tokens"] += (payload.get("usage") or {}).get("total_tokens", 0)
            write(chunk, data)
            return
        except urllib.error.HTTPError as e:
            if e.code != 400:
                print("  HTTP %s，跳过 %s" % (e.code, [r for r, _ in chunk]))
                stat["dead"].extend([r for r, _ in chunk])
                return
            e.read()
        except Exception as e:
            print("  异常 %s，跳过 %s" % (e, [r for r, _ in chunk]))
            stat["dead"].extend([r for r, _ in chunk])
            return

        if len(chunk) > 1:
            mid = len(chunk) // 2
            run(chunk[:mid])
            run(chunk[mid:])
            return

        # 单条仍 400：这条的 token 密度高，逐步砍短
        rid, text = chunk[0]
        n = len(text)
        for keep in (int(n * 0.8), int(n * 0.6), int(n * 0.45), int(n * 0.3)):
            try:
                payload = embed(base, key, model, [text[:keep]])
                d = payload["data"][0]
                stat["tokens"] += (payload.get("usage") or {}).get("total_tokens", 0)
                lit = "[" + ",".join("%.6f" % x for x in d["embedding"]) + "]"
                psql("UPDATE documents SET embedding = '%s'::vector WHERE id = %d;"
                     % (lit, rid))
                stat["done"] += 1
                stat["truncated"].append((rid, n, keep))
                print("  id=%d 超窗口，按 %d/%d 字截断后入库" % (rid, keep, n))
                return
            except urllib.error.HTTPError:
                continue
        stat["dead"].append(rid)

    for i in range(0, len(rows), BATCH):
        run(rows[i:i + BATCH])

    print("\n完成 %d 条，截断 %d 条，彻底失败 %d 条，耗时 %.1fs，token=%d"
          % (stat["done"], len(stat["truncated"]), len(stat["dead"]),
             time.perf_counter() - t0, stat["tokens"]))
    if stat["truncated"]:
        print("截断明细（id, 原字数, 实际嵌入字数）：%s" % stat["truncated"])
    if stat["dead"]:
        print("失败 id：%s" % stat["dead"])

    out = psql("select count(*) total, count(embedding) with_vec, "
               "round(avg(length(content))) avg_len from documents;", capture=True)
    print(out.strip())


if __name__ == "__main__":
    main()
