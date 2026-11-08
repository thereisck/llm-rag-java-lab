#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
W01 · 探 bge-large-zh-v1.5 的实际输入上限（按字符）

背景：check_embed.py 里 800 字文本被服务端 400 拒绝（code 20015），
不是静默截断，是硬失败。所以要找到"多少字以内一定成功"，
再回头数 276 个 chunk 里有多少条超线。

产出：一条 字符数 → 是否成功 / prompt_tokens 的对照表。
"""
import json
import os
import re
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DOC = os.path.join(ROOT, "90天AI工程破局计划.md")

LENGTHS = [100, 200, 300, 400, 450, 480, 500, 512, 550, 600, 700, 800]


def load_env():
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
    for k in ("SILICONFLOW_API_KEY", "EMBED_BASE_URL", "EMBED_MODEL"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def embed(base, key, model, texts):
    body = json.dumps({"model": model, "input": texts}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/embeddings",
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            err = {"message": "unparsable"}
        return None, "%s %s" % (e.code, err.get("code", ""))
    except urllib.error.URLError as e:
        return None, "网络 %s" % e.reason


def main():
    env = load_env()
    key = env["SILICONFLOW_API_KEY"]
    base = env.get("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
    model = env.get("EMBED_MODEL", "BAAI/bge-large-zh-v1.5")

    with open(DOC, "r", encoding="utf-8") as f:
        body = re.sub(r"\s+", " ", f.read())

    print("model = %s\n" % model)
    print("%8s %10s %14s  %s" % ("字符数", "结果", "prompt_tokens", "字/token"))
    print("-" * 52)
    ok_max = 0
    for n in LENGTHS:
        payload, err = embed(base, key, model, [body[:n]])
        if err:
            print("%8d %10s %14s  %s" % (n, "FAIL", "-", err))
        else:
            tok = (payload.get("usage") or {}).get("prompt_tokens")
            ratio = ("%.2f" % (n / tok)) if tok else "-"
            print("%8d %10s %14d  %s" % (n, "OK", tok, ratio))
            ok_max = max(ok_max, n)

    print("\n最大成功长度（本表内）= %d 字" % ok_max)


if __name__ == "__main__":
    main()
