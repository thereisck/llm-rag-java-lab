#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
W01 · embedding 服务连通性与维度校验（零依赖，只用标准库）

用法：
    python -X utf8 实验/seed/check_embed.py

它回答三个问题，答完才允许动 documents 表：
    1. key 通不通（HTTP 200 而不是 401）
    2. 维度是不是 1024（对不上就得 ALTER COLUMN）
    3. 800 字的 chunk 会不会被模型静默截断（bge-large-zh 上限 512 token）

不写库、不改数据，纯读。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DOC = os.path.join(ROOT, "90天AI工程破局计划.md")


def load_env():
    """优先读环境变量，其次读同目录 .env"""
    env = {}
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("SILICONFLOW_API_KEY", "EMBED_BASE_URL", "EMBED_MODEL", "EMBED_DIM"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def embed(base, key, model, texts):
    body = json.dumps({"model": model, "input": texts}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/embeddings",
        data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise SystemExit("[FAIL] HTTP %s\n%s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise SystemExit("[FAIL] 网络不通：%s" % e.reason)
    return payload, (time.perf_counter() - t0) * 1000


def main():
    env = load_env()
    key = env.get("SILICONFLOW_API_KEY", "")
    base = env.get("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
    model = env.get("EMBED_MODEL", "BAAI/bge-large-zh-v1.5")
    want_dim = int(env.get("EMBED_DIM", "1024"))

    if not key or key.startswith("sk-xxx"):
        raise SystemExit(
            "[STOP] 没读到 key。\n"
            "  1) 去 https://cloud.siliconflow.cn/account/ak 新建 API 密钥\n"
            "  2) cp 实验/seed/.env.example 实验/seed/.env\n"
            "  3) 把 .env 里的 sk-xxx 换成真 key（不要提交到 git）"
        )

    print("model =", model)
    print("base  =", base)

    # ---- 用例 1：短查询，只看通不通、维度对不对 ----
    q = "收入到底由什么决定才能算清楚"
    payload, ms = embed(base, key, model, [q])
    vec = payload["data"][0]["embedding"]
    dim = len(vec)
    print("\n[1] 短查询  %.0f ms  dim=%d  usage=%s" % (ms, dim, payload.get("usage")))
    print("    前 3 维: %s" % [round(x, 4) for x in vec[:3]])
    print("    %s" % ("维度对齐 vector(%d) ✓" % want_dim if dim == want_dim
                     else "维度不符！表是 vector(%d)，需 ALTER COLUMN ... TYPE vector(%d)" % (want_dim, dim)))

    # ---- 用例 2：真实长文本，看会不会被截断 ----
    with open(DOC, "r", encoding="utf-8") as f:
        raw = f.read()
    body = re.sub(r"\s+", " ", raw)
    long_text = body[:800]
    print("\n[2] 800 字真实文本（正文第 1~800 字）")
    payload2, ms2 = embed(base, key, model, [long_text])
    usage = payload2.get("usage") or {}
    tok = usage.get("prompt_tokens")
    print("    %.0f ms  usage=%s" % (ms2, usage))
    if tok is not None:
        if tok >= 512:
            print("    ⚠ prompt_tokens=%s ≥ 512：bge-large-zh 上限 512 token，"
                  "尾部已被截断，向量只覆盖前段" % tok)
        else:
            print("    ✓ prompt_tokens=%s < 512，未截断" % tok)

    # ---- 用例 3：批量吞吐，估 276 行的灌库时间 ----
    batch = ["第 %d 条测试" % i for i in range(32)]
    payload3, ms3 = embed(base, key, model, batch)
    n = len(payload3["data"])
    print("\n[3] 批量 %d 条  %.0f ms（%.1f ms/条）" % (n, ms3, ms3 / n))
    print("    276 行预计 %.1f 秒" % (276 * ms3 / n / 1000))

    print("\n结论：通路 %s，维度 %s。" % ("OK", "OK" if dim == want_dim else "不匹配"))


if __name__ == "__main__":
    main()
