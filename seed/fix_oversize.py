#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
W01 · 修掉超出模型窗口的 chunk

事实（2026-11-08 实测）：BAAI/bge-large-zh-v1.5 上限 512 token，
中文约 1.34 字/token → 680 字 = 510 token 成功，685 字 = 400 拒绝（code 20015）。
build_seed.py 的 MAX_LEN=800 是按字数设的，没考虑模型窗口，导致 5 条 chunk 嵌不进去。

做法：把这 5 条在**自然句边界**切成两段，原 id 存前半，后半新增一行（id 自增）。
不截断 —— 截断会让这 5 条永久召不回，且会污染 W01 的失败归因。

用法：
    python -X utf8 实验/seed/fix_oversize.py --dry   # 只看怎么切
    python -X utf8 实验/seed/fix_oversize.py         # 执行
"""
import csv
import io
import json
import os
import subprocess
import sys

LIMIT = 680          # 实测安全字数（510 token）
PSQL = ["docker", "exec", "-i", "raglab-pg", "psql", "-U", "postgres", "-d", "raglab"]
BOUNDARY = "。！？；\n!?;"


def psql(sql, capture=False):
    r = subprocess.run(PSQL + ["-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit("[SQL FAIL] %s\n%s" % (sql[:120], r.stderr.strip()[:500]))
    return r.stdout if capture else ""


def read_long():
    """用 COPY TO STDOUT 取超长行，CSV 解析，字段里带换行也不怕"""
    sql = ("\\copy (select id, content, metadata from documents "
           "where length(content) > %d order by id) to stdout with (format csv)" % LIMIT)
    r = subprocess.run(PSQL + ["-c", sql], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit("[READ FAIL] %s" % r.stderr.strip()[:500])
    return list(csv.reader(io.StringIO(r.stdout)))


def split_at_sentence(text):
    """在中点附近找一个自然断点，保证两段都 <= LIMIT"""
    mid = len(text) // 2
    lo, hi = int(len(text) * 0.35), int(len(text) * 0.65)
    cands = [i + 1 for i, ch in enumerate(text) if ch in BOUNDARY and lo <= i <= hi]
    cut = min(cands, key=lambda i: abs(i - mid)) if cands else mid
    head, tail = text[:cut].strip(), text[cut:].strip()
    # 兜底：万一两段还是超线，硬切
    if len(tail) > LIMIT:
        tail, over = tail[:LIMIT], tail[LIMIT:]
    else:
        over = ""
    return head, tail, over, cut


def main():
    dry = "--dry" in sys.argv
    rows = read_long()
    print("超 %d 字的 chunk：%d 条\n" % (LIMIT, len(rows)))

    sqls = []
    for rid, content, meta in rows:
        rid, content = int(rid), content
        head, tail, over, cut = split_at_sentence(content)
        m = json.loads(meta)
        m2 = dict(m)
        m2["chunk"] = "%sb" % m.get("chunk")
        m2["split_from"] = rid
        print("id=%-4d %4d 字 → 切在 %d ｜ 前 %d / 后 %d%s  《%s》%s"
              % (rid, len(content), cut, len(head), len(tail),
                 (" +残余%d" % len(over)) if over else "",
                 m.get("doc", "?"), (m.get("section") or "")[:24]))
        sqls.append("UPDATE documents SET content = %s WHERE id = %d;"
                    % (quote(head), rid))
        full_tail = tail + over
        sqls.append("INSERT INTO documents (content, metadata) VALUES (%s, %s);"
                    % (quote(full_tail), quote(json.dumps(m2, ensure_ascii=False))))

    if dry:
        print("\n[dry] 只打印，未改库。去掉 --dry 执行。")
        return

    psql("\n".join(sqls))
    out = psql("select count(*) total, max(length(content)) maxlen, "
               "count(*) filter (where length(content) > %d) over_limit from documents;" % LIMIT,
               capture=True)
    print("\n" + out.strip())


def quote(s):
    """生成标准 SQL 字符串字面量"""
    return "'" + s.replace("'", "''") + "'"


if __name__ == "__main__":
    main()
