#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
W01 语料切分器：把 Obsidian 库里的真实 md 切成 chunk，生成可直接灌库的 SQL。
切分策略：按 markdown 标题层级切（W02 会拿这个当对照组之一）。
输出：
  实验/seed/seed_chunks.sql   插入 documents 的语句
  实验/seed/chunk_index.tsv   chunk 清单，用来挑题、标 expected_chunk_id
"""
import os, re, json, csv, sys

ROOT = r"D:\个人知识库\破局"
OUT = os.path.join(ROOT, "实验", "seed")
os.makedirs(OUT, exist_ok=True)

# 只用非实验、非模板的真实文档当语料
SKIP_DIRS = {".workbuddy", "实验", "模板", ".obsidian", "00-Inbox"}

MAX_LEN = 800   # 单 chunk 上限（字符）
MIN_LEN = 40    # 太碎的丢掉


def collect():
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".md"):
                files.append(os.path.join(dirpath, fn))
    return sorted(files)


def strip_frontmatter(text):
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return text


def split_by_heading(text, doc_title):
    """返回 [(heading_path, body)]"""
    lines = text.split("\n")
    cur_h2, cur_h3 = "", ""
    buf = []
    out = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            path = " > ".join([p for p in (doc_title, cur_h2, cur_h3) if p])
            out.append((path, body))

    for ln in lines:
        m2 = re.match(r"^##\s+(?!#)(.*)$", ln)
        m3 = re.match(r"^###\s+(.*)$", ln)
        if m2:
            flush(); buf = []
            cur_h2, cur_h3 = m2.group(1).strip(), ""
        elif m3:
            flush(); buf = []
            cur_h3 = m3.group(1).strip()
        else:
            buf.append(ln)
    flush()
    return out


def split_long(body):
    """超过 MAX_LEN 的按空行分段再贪心拼接"""
    if len(body) <= MAX_LEN:
        return [body]
    paras = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(p) > MAX_LEN:                      # 单段落就超长，硬切
            if cur:
                chunks.append(cur); cur = ""
            for i in range(0, len(p), MAX_LEN):
                chunks.append(p[i:i + MAX_LEN])
            continue
        if len(cur) + len(p) + 2 <= MAX_LEN:
            cur = (cur + "\n\n" + p).strip()
        else:
            if cur:
                chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)
    return chunks


def esc(s):
    return s.replace("'", "''")


def main():
    rows = []          # (chunk_no, doc_title, heading_path, content)
    chunk_no = 0
    docs = []
    for path in collect():
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        title = os.path.splitext(os.path.basename(path))[0]
        body = strip_frontmatter(raw)
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        docs.append({"doc_title": title, "path": rel})
        for hpath, sec in split_by_heading(body, title):
            for piece in split_long(sec):
                if len(piece) < MIN_LEN:
                    continue
                chunk_no += 1
                rows.append((chunk_no, title, hpath, piece, rel))

    sql = ["SET client_encoding = 'UTF8';", "TRUNCATE documents RESTART IDENTITY;"]
    for no, title, hpath, piece, rel in rows:
        meta = json.dumps({"doc": title, "section": hpath, "path": rel,
                           "chunk": no}, ensure_ascii=False)
        sql.append(
            "INSERT INTO documents (content, metadata) VALUES "
            "(E'%s', '%s'::jsonb);" % (esc(piece), esc(meta))
        )
    with open(os.path.join(OUT, "seed_chunks.sql"), "w", encoding="utf-8") as f:
        f.write("\n".join(sql) + "\n")

    with open(os.path.join(OUT, "chunk_index.tsv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["chunk_id", "doc", "section", "chars", "preview"])
        for no, title, hpath, piece, rel in rows:
            w.writerow([no, title, hpath, len(piece),
                        piece[:70].replace("\n", " ")])

    print("docs=%d chunks=%d avg_len=%d" % (
        len(docs), len(rows), sum(len(r[3]) for r in rows) // max(len(rows), 1)))


if __name__ == "__main__":
    main()
