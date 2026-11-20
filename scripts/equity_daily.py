#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
申万菱信权益类重点产品「盘后净值播报」数据生成器

净值来源：天天基金 F10 历史净值接口（每只基金独立取，含各自的净值日期 FSRQ）
        https://api.fund.eastmoney.com/f10/lsjz

产出：
  equity-data.json                 页面读取的数据文件
  equity.html                     同一文件内更新内联数据块（file:// 直接打开也能看）
  output/equity_daily_summary.txt  当日播报纯文本（仅留档，不推送）

口径规则：
  1. 每只基金用自己的 FSRQ 作为净值日期，不借用批量接口的全局 showday。
  2. 取不到 / 字段为空 = 净值未出，用 null 表示，绝不按 0 处理、不沿用前一日。
  3. 历史列表按各基金 FSRQ 的日期并集对齐，某只基金当日无记录则显示「—」。
  4. 页面展示的数值全部为接口返回的原始字段，不做任何反推或估算。
"""

import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "equity-data.json")
HTML_PATH = os.path.join(BASE_DIR, "equity.html")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
SUMMARY_PATH = os.path.join(OUTPUT_DIR, "equity_daily_summary.txt")

# 产品清单：6 组 × A/C = 12 只
# 2026-11-19 定稿：移除中证A500指增、移除全球新能源(QDII)，新增行业轮动
# 2026-11-20 追加：全球新能源(QDII) 回归第 6 组，按 B 方案展示
TARGET_GROUPS = [
    ("新能源汽车", "001156", "022739"),
    ("智能驱动",   "005825", "015159"),
    ("数字产业",   "018048", "018049"),
    ("新经济",     "310358", "022735"),
    ("行业轮动",   "005009", "015157"),
    ("全球新能源", "017071", "017072"),
]

# QDII 产品：业务口径确认其展示前一期披露净值属正常，不计入「当日未披露」告警
QDII_GROUPS = {"全球新能源"}

F10_URL = "https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex={page}&pageSize={size}"
PAGE_SIZE = 20          # 该接口单次最多返回 20 条，pageSize 调大也不会多给
PAGES = 2               # 取 2 页 = 40 条净值记录（约 40 个交易日）
MAX_HISTORY_DAYS = 40   # 历史列表最多展示 40 个日期
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://fundf10.eastmoney.com/",
}
CTX = ssl._create_unverified_context()


def bj_now():
    return datetime.now(timezone(timedelta(hours=8)))


def fetch_history(code):
    """取单只基金的历史净值（分 2 页，单次上限 20 条）。"""
    rows = []
    for page in range(1, PAGES + 1):
        url = F10_URL.format(code=code, page=page, size=PAGE_SIZE)
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20, context=CTX) as resp:
            payload = json.loads(resp.read().decode("utf-8", "ignore"))
        part = (payload.get("Data") or {}).get("LSJZList") or []
        rows.extend(part)
        if len(part) < PAGE_SIZE:
            break
    return rows


def normalize(row):
    """把一条 F10 原始记录转成页面字段；空值一律记为空，不补 0。"""
    nav_date = (row.get("FSRQ") or "").strip()
    nav = (row.get("DWJZ") or "").strip()
    change = (row.get("JZZZL") or "").strip()
    available = bool(nav_date and nav and change)
    return {
        "nav_date": nav_date or None,
        "nav": nav if nav else None,
        "change": change if change else None,
        "available": available,
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ---- 抓取 ----------------------------------------------------------
    funds = {}          # code -> {name, rows(按日期索引)}
    failures = []
    for group_name, code_a, code_c in TARGET_GROUPS:
        for code, share in ((code_a, "A"), (code_c, "C")):
            try:
                rows = fetch_history(code)
                by_date = {}
                for r in rows:
                    item = normalize(r)
                    if item["nav_date"]:
                        by_date[item["nav_date"]] = item
                funds[code] = {
                    "code": code,
                    "share": share,
                    "group": group_name,
                    "by_date": by_date,
                }
                print(f"  {code} {group_name}{share}: 取回 {len(by_date)} 条净值，"
                      f"最新 {max(by_date) if by_date else '无'}")
            except Exception as exc:
                failures.append((code, group_name, share, type(exc).__name__))
                funds[code] = {"code": code, "share": share, "group": group_name,
                               "by_date": {}}
                print(f"  {code} {group_name}{share}: 抓取失败 {type(exc).__name__} {exc}")

    # ---- 组装当日卡片：每只基金用自己的最新净值日期 --------------------
    groups = []
    for group_name, code_a, code_c in TARGET_GROUPS:
        shares = {}
        for share, code in (("a", code_a), ("c", code_c)):
            by_date = funds[code]["by_date"]
            latest_date = max(by_date) if by_date else None
            item = dict(by_date[latest_date]) if latest_date else normalize({})
            item["code"] = code
            shares[share] = item
        groups.append({"name": group_name, "is_qdii": group_name in QDII_GROUPS,
                       "a": shares["a"], "c": shares["c"]})

    # ---- 组装历史列表：日期并集，逐只按自己的 FSRQ 对齐 -----------------
    all_dates = set()
    for f in funds.values():
        all_dates.update(f["by_date"].keys())
    dates = sorted(all_dates, reverse=True)[:MAX_HISTORY_DAYS]

    records = []
    for d in dates:
        row_groups = []
        for group_name, code_a, code_c in TARGET_GROUPS:
            shares = {}
            for share, code in (("a", code_a), ("c", code_c)):
                item = funds[code]["by_date"].get(d)
                if item is None:
                    item = normalize({})
                else:
                    item = dict(item)
                item["code"] = code
                shares[share] = item
            row_groups.append({"name": group_name, "is_qdii": group_name in QDII_GROUPS,
                               "a": shares["a"], "c": shares["c"]})
        records.append({"date": d, "groups": row_groups})

    today_str = bj_now().strftime("%Y-%m-%d")
    today_published_count = sum(
        1 for g in groups for s in ("a", "c")
        if g[s]["available"] and g[s]["nav_date"] == today_str
    )
    # QDII 按前一期披露净值展示属正常口径，只统计非 QDII 产品是否出齐
    a_share_total = sum(2 for name, _, _ in TARGET_GROUPS if name not in QDII_GROUPS)
    a_share_published_count = sum(
        1 for g in groups for s in ("a", "c")
        if not g["is_qdii"] and g[s]["available"] and g[s]["nav_date"] == today_str
    )
    meta = {
        "title": "权益净值播报",
        "source": "天天基金 F10 历史净值接口 api.fund.eastmoney.com/f10/lsjz",
        "note": "各基金净值日期以自身披露为准；空白表示净值未出，未按 0 处理。",
        "generated_at": bj_now().strftime("%Y-%m-%d %H:%M:%S") + " (北京时间)",
        "update_note": "工作日 19:45–21:15 云端自动更新",
        "group_count": len(TARGET_GROUPS),
        "fund_count": len(TARGET_GROUPS) * 2,
        "latest_date": dates[0] if dates else None,
        "is_today_published": bool(dates) and dates[0] == today_str,
        "today_published_count": today_published_count,
        "qdii_groups": sorted(QDII_GROUPS),
        "a_share_fund_count": a_share_total,
        "a_share_published_count": a_share_published_count,
        "history_days": len(records),
        "fetch_failures": [{"code": c, "group": g, "share": s, "error": e}
                           for c, g, s, e in failures],
    }
    data = {"meta": meta, "groups": groups, "records": records}

    # ---- 自洽性校验（数值全部从上面的生成结果回读） --------------------
    checks = []
    expected_funds = len(TARGET_GROUPS) * 2
    checks.append((f"产品组数={len(TARGET_GROUPS)}", len(groups) == len(TARGET_GROUPS)))
    checks.append((f"基金只数={expected_funds}",
                   sum(1 for g in groups for _ in ("a", "c")) == expected_funds))
    checks.append(("QDII 组标记数=1", sum(1 for g in groups if g["is_qdii"]) == 1))
    checks.append(("A股只数+QDII只数=总只数", a_share_total + 2 == expected_funds))
    checks.append(("历史每条组数一致", all(len(r["groups"]) == len(groups) for r in records)))
    checks.append(("历史有数据", len(records) > 0))
    checks.append(("今日已披露只数在 0~总数之间",
                   0 <= today_published_count <= len(groups) * 2))
    checks.append(("当日卡片字段完整", all(g["a"].get("code") and g["c"].get("code")
                                       for g in groups)))
    checks.append(("无 0 填充缺失", all(
        (x["change"] is not None or not x["available"])
        for g in groups for x in (g["a"], g["c"]))))

    # ---- 落盘 ----------------------------------------------------------
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 把数据内联进 HTML，保证 file:// 双击也能看到内容
    if os.path.exists(HTML_PATH):
        with open(HTML_PATH, "r", encoding="utf-8") as f:
            html = f.read()
        inline = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        pattern = r'(<script id="inline-data"[^>]*>)[\s\S]*?(</script>)'
        new_html, n = re.subn(pattern, lambda m: m.group(1) + inline + m.group(2),
                              html, count=1)
        if n == 1:
            with open(HTML_PATH, "w", encoding="utf-8") as f:
                f.write(new_html)
            # 同步写一份 index.html 作为静态托管根路径入口：
            # 避免平台生成无 <title> 的跳转壳，微信分享才拿得到「权益净值播报」
            with open(os.path.join(BASE_DIR, "index.html"), "w", encoding="utf-8") as f:
                f.write(new_html)
            print("  已更新 equity.html / index.html 内联数据块")
        else:
            print("  ⚠️ 未找到 HTML 内联数据占位块，跳过注入")

    # 纯文本留档（不推送、不发钉钉）
    lines = [f"净值播报 | 最新净值日期 {meta['latest_date'] or '无'}",
             f"今日已披露(全口径) {today_published_count} / {len(groups) * 2} 只",
             f"A股产品今日已披露(告警口径) {a_share_published_count} / {a_share_total} 只",
             f"数据来源：{meta['source']}", ""]
    for g in groups:
        pair = []
        for share in ("a", "c"):
            x = g[share]
            val = f"{float(x['change']):+.2f}%" if x["available"] else "净值未出"
            pair.append(f"{share.upper()} {x['code']} 单位净值 {x['nav'] or '—'} / {val}"
                        f"（净值日期 {x['nav_date'] or '—'}）")
        lines.append(f"【{g['name']}】{' [QDII]' if g['is_qdii'] else ''} " + " | ".join(pair))
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ---- 关键数字 · 汇报请直接引用本段 ---------------------------------
    print("\n" + "=" * 62)
    print("关键数字 · 汇报请直接引用本段")
    print(f"产品组数: {len(groups)}")
    print(f"基金只数: {sum(1 for g in groups for _ in ('a', 'c'))}")
    print(f"最新净值日期(日期并集): {meta['latest_date']}")
    print(f"今日已披露净值只数(全口径): {today_published_count} / {len(groups) * 2}")
    print(f"A股产品今日已披露(告警口径): {a_share_published_count} / {a_share_total}")
    print(f"历史交易日数: {len(records)}")
    missing = sum(1 for g in groups for x in (g["a"], g["c"]) if not x["available"])
    print(f"各基金最新一期缺失格数: {missing}")
    print(f"抓取失败只数: {len(failures)}")
    for g in groups:
        a, c = g["a"], g["c"]
        av = f"{a['change']}%" if a["available"] else "未出"
        cv = f"{c['change']}%" if c["available"] else "未出"
        tag = " [QDII]" if g["is_qdii"] else ""
        print(f"  {g['name']}{tag}: A {a['code']} {a['nav'] or '—'} {av} | "
              f"C {c['code']} {c['nav'] or '—'} {cv}"
              f" | 净值日期 {a['nav_date'] or '—'} / {c['nav_date'] or '—'}")
    print("自洽性校验: " + ("PASS" if all(ok for _, ok in checks) else "FAIL"))
    for label, ok in checks:
        print(f"  [{'OK' if ok else 'NG'}] {label}")
    print("=" * 62)

    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
