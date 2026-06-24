#!/usr/bin/env python3
"""Recalculate total_cost_usd in cc-switch usage_daily_rollups using model_pricing rates.

Usage:
    python3 recalc_cost.py          # Recalculate all rows
    python3 recalc_cost.py --dry-run # Preview changes only
"""

import sqlite3
import sys
import os

DB_PATH = os.path.expanduser("~/.cc-switch/cc-switch.db")


def get_pricing(db):
    """Read model_pricing table, return {model_id: {input, output}}."""
    cur = db.execute(
        "SELECT model_id, input_cost_per_million, output_cost_per_million "
        "FROM model_pricing"
    )
    return {
        row[0]: {
            "input": float(row[1]),
            "output": float(row[2]),
        }
        for row in cur.fetchall()
    }


def recalc_cost(pricing, input_tokens, output_tokens, model):
    """Calculate cost: (tokens / 1M) * price_per_1M."""
    if model not in pricing:
        return None
    p = pricing[model]
    in_cost = (input_tokens / 1_000_000) * p["input"]
    out_cost = (output_tokens / 1_000_000) * p["output"]
    return round(in_cost + out_cost, 6)


def main():
    dry_run = "--dry-run" in sys.argv

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    db = conn.cursor()

    pricing = get_pricing(db)

    # Fetch all rows that need recalculation
    rows = db.execute(
        "SELECT date, app_type, provider_id, model, request_model, pricing_model, "
        "input_tokens, output_tokens, total_cost_usd "
        "FROM usage_daily_rollups "
        "ORDER BY date DESC, model"
    ).fetchall()

    updated = 0
    skipped = 0
    total_old = 0.0
    total_new = 0.0

    for row in rows:
        model = row["model"]
        old_cost = float(row["total_cost_usd"])
        new_cost = recalc_cost(pricing, row["input_tokens"], row["output_tokens"], model)

        if new_cost is None:
            skipped += 1
            continue

        total_old += old_cost
        total_new += new_cost

        if dry_run:
            print(
                f"{row['date']}  {model:20s}  "
                f"in={row['input_tokens']:>12,}  out={row['output_tokens']:>10,}  "
                f"${old_cost:>8.4f} → ${new_cost:>8.4f}"
            )
        else:
            db.execute(
                "UPDATE usage_daily_rollups SET total_cost_usd = ? "
                "WHERE date = ? AND app_type = ? AND provider_id = ? "
                "AND model = ? AND request_model = ? AND pricing_model = ?",
                (str(new_cost), row["date"], row["app_type"], row["provider_id"],
                 row["model"], row["request_model"], row["pricing_model"]),
            )
        updated += 1

    if not dry_run:
        conn.commit()
        print(f"Updated {updated} rows. Skipped {skipped} (no pricing).")
    else:
        print(f"\nWould update {updated} rows. Skipped {skipped} (no pricing).")

    print(f"Total cost: ${total_old:.4f} → ${total_new:.4f} ({(1 - total_new/total_old)*100:.0f}% off)" if total_old > 0 else "")
    conn.close()


if __name__ == "__main__":
    main()
