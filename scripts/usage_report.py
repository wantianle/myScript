#!/usr/bin/env python3
"""
Usage cost report with correct pricing.

Sources:
    usage_daily_rollups  — per-model token counts from cc-switch
    model_pricing        — correct $/1M rates (already updated)

Usage:
    python3 usage_report.py              # show daily + monthly summary
    python3 usage_report.py --month 6    # filter by month
    python3 usage_report.py --update-db  # also fix total_cost_usd in db
    python3 usage_report.py --csv        # machine-readable output
"""

import sqlite3
import sys
import os
from collections import defaultdict

DB = os.path.expanduser("~/.cc-switch/cc-switch.db")

def load_pricing(db):
    rows = db.execute(
        "SELECT model_id, input_cost_per_million, output_cost_per_million, "
        "cache_read_cost_per_million, cache_creation_cost_per_million "
        "FROM model_pricing"
    ).fetchall()
    return {r[0]: (float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows}


def calc_cost(price, in_tok, out_tok, cache_read_tok, cache_creation_tok):
    pin, pout, pcr, pcc = price
    if cache_read_tok > in_tok:
        non_cache = in_tok
    else:
        non_cache = in_tok - cache_read_tok
    return (non_cache / 1_000_000) * pin \
        + (cache_read_tok / 1_000_000) * pcr \
        + (cache_creation_tok / 1_000_000) * pcc \
        + (out_tok / 1_000_000) * pout


def fmt(n):
    return f"{n:,.0f}"


def main():
    dry = "--dry-run" in sys.argv
    update = "--update-db" in sys.argv
    csv_out = "--csv" in sys.argv
    month_filter = None
    for i, a in enumerate(sys.argv):
        if a == "--month" and i + 1 < len(sys.argv):
            month_filter = sys.argv[i + 1]

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    db = conn.cursor()

    pricing = load_pricing(db)

    rows = db.execute(
        "SELECT date, app_type, model, input_tokens, output_tokens, "
        "cache_read_tokens, cache_creation_tokens, total_cost_usd, request_count "
        "FROM usage_daily_rollups ORDER BY date"
    ).fetchall()

    daily = defaultdict(lambda: {"models": {}, "total_in": 0, "total_out": 0,
                                  "total_cache": 0,
                                  "old_cost": 0, "real_cost": 0, "reqs": 0})
    monthly = defaultdict(lambda: {"old": 0, "real": 0, "total_in": 0, "total_out": 0})
    grand_old = 0
    grand_real = 0

    for r in rows:
        if month_filter and not r["date"].startswith(f"2026-{int(month_filter):02d}"):
            continue

        model = r["model"]
        price = pricing.get(model)
        if price is None:
            continue

        d = r["date"]
        in_t = r["input_tokens"]
        out_t = r["output_tokens"]
        cache_r = r["cache_read_tokens"]
        cache_c = r["cache_creation_tokens"]
        old = float(r["total_cost_usd"])
        real = calc_cost(price, in_t, out_t, cache_r, cache_c)

        daily[d]["models"][model] = daily[d]["models"].get(model, {"in": 0, "out": 0, "cache": 0, "old": 0, "real": 0})
        daily[d]["models"][model]["in"] += in_t
        daily[d]["models"][model]["out"] += out_t
        daily[d]["models"][model]["cache"] += cache_r
        daily[d]["models"][model]["old"] += old
        daily[d]["models"][model]["real"] += real

        daily[d]["total_in"] += in_t
        daily[d]["total_out"] += out_t
        daily[d]["total_cache"] += cache_r
        daily[d]["old_cost"] += old
        daily[d]["real_cost"] += real
        daily[d]["reqs"] += r["request_count"]

        mon = d[:7]
        monthly[mon]["old"] += old
        monthly[mon]["real"] += real
        monthly[mon]["total_in"] += in_t
        monthly[mon]["total_out"] += out_t

        grand_old += old
        grand_real += real

        if update and not dry:
            db.execute(
                "UPDATE usage_daily_rollups SET total_cost_usd = ? "
                "WHERE date = ? AND app_type = ? AND model = ? "
                "AND COALESCE(request_model,'') = COALESCE(?,'') "
                "AND COALESCE(pricing_model,'') = COALESCE(?,'')",
                (str(round(real, 6)), r["date"], r["app_type"], r["model"],
                 r["request_model"] or "", r["pricing_model"] or "")
            )

    if update and not dry:
        conn.commit()

    if csv_out:
        print("date,model,app,input_tokens,output_tokens,cache_read,old_cost,real_cost")
        for d in sorted(daily):
            info = daily[d]
            for model, m in info["models"].items():
                print(f"{d},{model},,{fmt(m['in'])},{fmt(m['out'])},{fmt(m['cache'])},{m['old']:.4f},{m['real']:.4f}")
        return

    # --- pretty print ---
    print(f"{'Date':>12}  {'Model':20s}  {'Input':>12s}  {'Output':>10s}  {'Cache':>10s}  {'Old $':>8s}  {'Real $':>8s}  {'Diff':>8s}")
    print("-" * 104)
    for d in sorted(daily):
        info = daily[d]
        first = True
        for model, m in sorted(info["models"].items()):
            diff = m["real"] - m["old"]
            sign = "+" if diff > 0 else ""
            print(f"{d if first else '':>12}  {model:20s}  {fmt(m['in']):>12s}  {fmt(m['out']):>10s}  {fmt(m['cache']):>10s}  "
                  f"${m['old']:>7.2f}  ${m['real']:>7.2f}  {sign}{diff:>7.2f}")
            first = False
        # day total
        dt = info["real_cost"] - info["old_cost"]
        sign = "+" if dt > 0 else ""
        print(f"{'':>12}  {'[day total]':20s}  {fmt(info['total_in']):>12s}  {fmt(info['total_out']):>10s}  "
              f"{fmt(info['total_cache']):>10s}  "
              f"${info['old_cost']:>7.2f}  ${info['real_cost']:>7.2f}  {sign}{dt:>7.2f}")
        print()

    print("=" * 104)
    print(f"{'Month':>12}  {'Input (M)':>12s}  {'Output (M)':>12s}  {'Old $':>10s}  {'Real $':>10s}  {'Diff':>8s}")
    print("-" * 72)
    for mon in sorted(monthly):
        m = monthly[mon]
        diff = m["real"] - m["old"]
        sign = "+" if diff > 0 else ""
        print(f"{mon:>12}  {m['total_in']/1e6:>12.1f}  {m['total_out']/1e6:>12.1f}  "
              f"${m['old']:>9.2f}  ${m['real']:>9.2f}  {sign}{diff:>7.2f}")

    gd = grand_real - grand_old
    sign = "+" if gd > 0 else ""
    print(f"{'TOTAL':>12}  {'':>12s}  {'':>12s}  ${grand_old:>9.2f}  ${grand_real:>9.2f}  {sign}{gd:>7.2f}")

    if update and dry:
        print("\n[--dry-run: no changes written]")

    conn.close()


if __name__ == "__main__":
    main()
