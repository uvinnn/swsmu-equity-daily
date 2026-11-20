#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把最新净值快照推送到独立 Pages 仓库 uvinnn/swsmu-equity-daily。

用途：本地定时任务兜底；云端 Actions 未启用或失败时，仍保证 GitHub Pages 链接每日更新。
仅写 equity-data.json / equity.html / index.html / 播报留档，不写 workflow 文件。

口径：只在 self-check PASS 后由调用方运行；不在本脚本内改写或推算任何净值数字。
"""

import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_PATH = r"C:/Users/admin/WorkBuddy/swsmu-debt-daily/.github_token"
REPO = "/repos/uvinnn/swsmu-equity-daily"
API = "https://api.github.com"
FILES = [
    "equity-data.json",
    "equity.html",
    "index.html",
    "output/equity_daily_summary.txt",
]
CTX = ssl._create_unverified_context()


def api(path, method="GET", payload=None, token=""):
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "equity-pages-push",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
        return json.loads(resp.read().decode())


def main():
    token = open(TOKEN_PATH, encoding="utf-8").read().strip()
    # 先确认数据自洽（本脚本不重算净值，只读取生成结果）
    meta = json.load(open(os.path.join(BASE_DIR, "equity-data.json"), encoding="utf-8"))["meta"]
    print("待推送快照:", meta["generated_at"], "|", meta["group_count"], "组 /", meta["fund_count"], "只")

    changed = 0
    for rel in FILES:
        path = os.path.join(BASE_DIR, rel)
        raw = open(path, "rb").read()
        content = base64.b64encode(raw).decode()
        url = REPO + "/contents/" + urllib.parse.quote(rel, safe="/")
        try:
            cur = api(url + "?ref=main", token=token)
            sha = cur.get("sha")
            # 内容未变则跳过，避免无意义提交
            if cur.get("content") and base64.b64decode(cur["content"].replace("\n", "")) == raw:
                print("  跳过(无变化):", rel)
                continue
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            sha = None
        body = {
            "message": "chore: 净值快照 " + meta["generated_at"],
            "content": content,
            "branch": "main",
        }
        if sha:
            body["sha"] = sha
        r = api(url, "PUT", body, token)
        changed += 1
        print("  已更新:", rel, "| commit", r["commit"]["sha"][:10])

    print("推送完成 | 更新文件数:", changed, "/", len(FILES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
