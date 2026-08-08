#!/usr/bin/env python3
"""Query the company AI API /usage endpoint and render a self-contained HTML report.

Credentials are read automatically from:
    GPT:      ~/.codex/auth.json          -> OPENAI_API_KEY
    Claude:   ~/.claude/settings.json     -> env.ANTHROPIC_AUTH_TOKEN

Usage:
    python3 ai_usage_html.py
"""

import json
import sys
import textwrap
import urllib.request
import urllib.error
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

GPT_API_BASE_URL = "https://sub2api.minieye.tech/v1"
CLAUDE_API_BASE_URL = "https://sub2api.minieye.tech/v1"
SCRIPT_DIR = Path(__file__).resolve().parent

# ── helpers ─────────────────────────────────────────────────────────────────

def _api_get(url: str, api_key: str) -> dict:
    """GET *url* with Bearer auth, return parsed JSON."""
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"API HTTP {e.code}: {body}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"API connection error: {e.reason}") from None


def _num(n: Union[int, float]) -> str:
    """Format integer with commas."""
    if isinstance(n, float):
        return f"{n:,.0f}"
    return f"{int(n):,}"


def _usd(n: Union[int, float]) -> str:
    """Format as USD with 2 decimal places."""
    return f"${float(n):,.2f}"


def _tokens_millions(n: Union[int, float]) -> str:
    """Format token usage in millions with 2 decimal places."""
    return f"{float(n) / 1_000_000:.2f}M"


def _pct(part: Union[int, float], whole: Union[int, float]) -> str:
    """Return percentage string."""
    if whole == 0:
        return "—"
    return f"{float(part) / float(whole) * 100:.1f}%"


def _bar_width(value: float, max_val: float, min_pct: float = 2) -> float:
    """Return a percentage width for bar charts (minimum *min_pct*%)."""
    if max_val <= 0:
        return min_pct
    return max(min_pct, value / max_val * 100)


def _parse_iso_date(date_str: str) -> str:
    """Parse ISO date to a friendly label (Mon DD)."""
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%b %d")
    except Exception:
        return date_str


# ── local cost estimation for non-GPT plans ──────────────────────────────────

DEEPSEEK_MULTIPLIER = 1.5

P_DEEPSEEK = {"input": 0.435, "output": 0.87, "cache": 0.003625}
P_KIMI = {"input": 0.95, "output": 4.00, "cache": 0.16}

LOCAL_COST_PLANS = {"deepseek", "kimi"}


def _plan_suffix(data: dict) -> str:
    """Extract plan suffix from planName, e.g. 'default-deepseek' -> 'deepseek'."""
    plan = data.get("planName", "")
    return plan.rsplit("-", 1)[-1].lower() if "-" in plan else ""


def _get_pricing(model_name: str, plan_suffix: str) -> Optional[Dict]:
    """Return pricing dict for a model under *plan_suffix*, or None for server cost."""
    if plan_suffix == "kimi":
        return P_KIMI
    if plan_suffix == "deepseek":
        return P_DEEPSEEK
    return None  # use server cost


def _compute_local_cost(input_tok: int, output_tok: int, cache_tok: int,
                        pricing: dict, plan_suffix: str = "") -> float:
    """Compute local estimated cost from token counts and pricing dict."""
    cost = (input_tok * pricing["input"]
            + output_tok * pricing["output"]
            + cache_tok * pricing["cache"]) / 1_000_000
    if plan_suffix == "deepseek":
        cost *= DEEPSEEK_MULTIPLIER
    return cost


def _card(icon: str, title: str, value: str, sub: str) -> List[str]:
    """Return HTML for a single summary card."""
    sub_html = f'<span class="card-sub">{escape(sub)}</span>' if sub else ""
    return [
        f'<div class="card">'
        f'<div class="card-icon">{escape(icon)}</div>'
        f'<div class="card-title">{escape(title)}</div>'
        f'<div class="card-value">{escape(value)}</div>'
        f'{sub_html}'
        f'</div>',
    ]


def _extract_totals(data: dict, plan_suffix: str = "") -> dict:
    """Extract key numeric totals. Uses local cost for non-GPT plans."""
    usage = data.get("usage", {})
    today = usage.get("today", {})
    total = usage.get("total", {})
    sub = data.get("subscription", {})

    use_local = plan_suffix in LOCAL_COST_PLANS

    def _cost(src: dict) -> float:
        if use_local:
            pricing = _get_pricing("default", plan_suffix)
            if pricing:
                return _compute_local_cost(
                    int(src.get("input_tokens", 0)),
                    int(src.get("output_tokens", 0)),
                    int(src.get("cache_read_tokens", 0)),
                    pricing, plan_suffix,
                )
        return float(src.get("actual_cost", src.get("cost", 0)))

    raw_rem = data.get("remaining")
    remaining = None if raw_rem is None or (isinstance(raw_rem, (int, float)) and raw_rem < 0) else raw_rem

    return {
        "today_cost": _cost(today),
        "total_cost": _cost(total),
        "today_reqs": int(today.get("requests", 0)),
        "total_reqs": int(total.get("requests", 0)),
        "today_in": int(today.get("input_tokens", 0)),
        "today_out": int(today.get("output_tokens", 0)),
        "today_cache": int(today.get("cache_read_tokens", 0)),
        "today_total": int(today.get("total_tokens", 0)),
        "total_in": int(total.get("input_tokens", 0)),
        "total_out": int(total.get("output_tokens", 0)),
        "total_cache": int(total.get("cache_read_tokens", 0)),
        "total_tokens": int(total.get("total_tokens", 0)),
        "remaining": remaining,
        "daily_limit": sub.get("daily_limit_usd", 0) if isinstance(sub, dict) else 0,
        "expires": sub.get("expires_at", "") if isinstance(sub, dict) else "",
    }


def _extract_display(data: dict) -> dict:
    """Extract display fields (strings and non-numeric) from a usage response."""
    sub = data.get("subscription", {})
    return {
        "plan": data.get("planName", "—"),
        "model_names": ", ".join(m.get("model", "?") for m in data.get("model_stats", [])),
        "model_stats": data.get("model_stats", []),
        "daily_usage": data.get("daily_usage", []),
        "sub": sub if isinstance(sub, dict) else {},
        "mode": data.get("mode", "—"),
    }


def _render_subscription(sub: dict) -> List[str]:
    """Return HTML for subscription progress bars."""
    if not sub:
        return []
    rows = [
        ("Daily", sub.get("daily_usage_usd", 0), sub.get("daily_limit_usd", 0)),
        ("Weekly", sub.get("weekly_usage_usd", 0), sub.get("weekly_limit_usd", 0)),
        ("Monthly", sub.get("monthly_usage_usd", 0), sub.get("monthly_limit_usd", 0)),
    ]
    lines = ['<div class="sub-grid">']
    for label, used, limit in rows:
        pct_val = f"{(float(used) / float(limit) * 100):.1f}%" if limit and float(limit) > 0 else "∞"
        bar_pct = min(100, float(used) / float(limit) * 100) if limit and float(limit) > 0 else 0
        lines.append(
            f'<div class="sub-item">'
            f'<div class="sub-label">{escape(label)}</div>'
            f'<div class="sub-bar"><div class="sub-fill" style="width:{bar_pct:.1f}%"></div></div>'
            f'<div class="sub-val">{_usd(used)} / {_usd(limit) if limit else "∞"}</div>'
            f'<div class="sub-pct">{escape(pct_val)}</div>'
            f'</div>'
        )
    lines.append("</div>")
    return lines


def _render_model_table(model_stats: list, plan_suffix: str = "") -> List[str]:
    """Return HTML for the model breakdown table. Local cost for non-GPT plans."""
    if not model_stats:
        return []
    use_local = plan_suffix in LOCAL_COST_PLANS
    lines = [
        '<div class="table-wrap">',
        '<table class="data-table">',
        '<thead><tr><th>Model</th><th>Requests</th><th>Input Tokens</th>'
        '<th>Output Tokens</th><th>Cache Tokens</th><th>Total Tokens</th>'
        '<th>Cost</th></tr></thead><tbody>',
    ]
    for m in model_stats:
        if use_local:
            pricing = _get_pricing(m.get("model", ""), plan_suffix)
            if pricing:
                cost = _compute_local_cost(
                    int(m.get("input_tokens", 0)),
                    int(m.get("output_tokens", 0)),
                    int(m.get("cache_read_tokens", 0)),
                    pricing, plan_suffix,
                )
            else:
                cost = float(m.get("actual_cost", m.get("cost", 0)))
        else:
            cost = float(m.get("actual_cost", m.get("cost", 0)))
        lines.append(
            f"<tr>"
            f"<td><strong>{escape(m.get('model', '?'))}</strong></td>"
            f"<td>{_num(m.get('requests', 0))}</td>"
            f"<td>{_num(m.get('input_tokens', 0))}</td>"
            f"<td>{_num(m.get('output_tokens', 0))}</td>"
            f"<td>{_num(m.get('cache_read_tokens', 0))}</td>"
            f"<td>{_num(m.get('total_tokens', 0))}</td>"
            f"<td class='cost-cell'>{_usd(cost)}</td>"
            f"</tr>"
        )
    lines.append("</tbody></table></div>")
    return lines


def _render_daily_chart(daily_usage: list, plan_suffix: str = "") -> List[str]:
    """Return HTML for daily usage bar chart + detail table. Local cost for non-GPT."""
    if not daily_usage:
        return []
    use_local = plan_suffix in LOCAL_COST_PLANS

    def _day_cost(entry: dict) -> float:
        if use_local:
            pricing = _get_pricing("default", plan_suffix)
            if pricing:
                return _compute_local_cost(
                    int(entry.get("input_tokens", 0)),
                    int(entry.get("output_tokens", 0)),
                    int(entry.get("cache_read_tokens", 0)),
                    pricing, plan_suffix,
                )
        return float(entry.get("actual_cost", entry.get("cost", 0)))

    max_cost = max(_day_cost(d) for d in daily_usage) or 1
    lines = ['<div class="chart">']
    for entry in daily_usage:
        cost = _day_cost(entry)
        w = _bar_width(cost, max_cost)
        date_label = _parse_iso_date(entry.get("date", ""))
        lines.append(
            f'<div class="chart-row">'
            f'<span class="chart-label">{escape(date_label)}</span>'
            f'<div class="chart-track"><span class="chart-bar" style="width:{w:.1f}%"></span></div>'
            f'<span class="chart-val">{_tokens_millions(entry.get("total_tokens", 0))}</span>'
            f'</div>'
        )
    lines.append("</div>")

    lines.append('<div class="table-wrap" style="margin-top:24px">')
    lines.append('<table class="data-table">')
    lines.append(
        '<thead><tr><th>Date</th><th>Req</th><th>Input</th><th>Output</th>'
        '<th>Cache</th><th>Total Tokens</th><th>Cost</th></tr></thead><tbody>'
    )
    for entry in daily_usage:
        cost = _day_cost(entry)
        lines.append(
            f"<tr>"
            f"<td><strong>{escape(entry.get('date', '?'))}</strong></td>"
            f"<td>{_num(entry.get('requests', 0))}</td>"
            f"<td>{_num(entry.get('input_tokens', 0))}</td>"
            f"<td>{_num(entry.get('output_tokens', 0))}</td>"
            f"<td>{_num(entry.get('cache_read_tokens', 0))}</td>"
            f"<td>{_num(entry.get('total_tokens', 0))}</td>"
            f"<td class='cost-cell'>{_usd(cost)}</td>"
            f"</tr>"
        )
    lines.append("</tbody></table></div>")
    return lines


def _render_combined_cards(all_totals: List[Dict]) -> List[str]:
    """Return HTML for combined summary cards across all providers."""
    tc = sum(t["today_cost"] for t in all_totals)
    tot = sum(t["total_cost"] for t in all_totals)
    tr = sum(t["today_reqs"] for t in all_totals)
    tor = sum(t["total_reqs"] for t in all_totals)
    ti = sum(t["today_in"] for t in all_totals)
    to = sum(t["today_out"] for t in all_totals)
    tcache = sum(t["today_cache"] for t in all_totals)
    ttoday = sum(t["today_total"] for t in all_totals)
    tall_in = sum(t["total_in"] for t in all_totals)
    tall_out = sum(t["total_out"] for t in all_totals)
    tall_cache = sum(t["total_cache"] for t in all_totals)
    tall_tok = sum(t["total_tokens"] for t in all_totals)
    combined_rem = sum(t["remaining"] for t in all_totals
                       if t["remaining"] is not None and t["remaining"] > 0)
    cache_hit = _pct(tcache, tcache + ti) if (tcache + ti) > 0 else "—"

    lines = [
        '<div class="section combined-section">',
        '<h2>🏢 Combined Summary</h2>',
        '<div class="cards">',
        *_card("💰", "Today Cost", _usd(tc), ""),
        *_card("🧾", "Total Cost", _usd(tot), ""),
        *_card("📊", "Today Req", _num(tr), ""),
        *_card("📁", "Total Req", _num(tor), ""),
        *_card("⚡", "Cache Hit", cache_hit, "input tokens from cache today"),
        *_card("🚀", "Today Tok", _num(ttoday),
               f"in={_num(ti)}  out={_num(to)}"),
        *_card("📦", "Total Tok", _num(tall_tok),
               f"in={_num(tall_in)}  out={_num(tall_out)}  cache={_num(tall_cache)}"),
    ]
    if combined_rem > 0:
        all_limits = sum(t["daily_limit"] for t in all_totals if t["daily_limit"])
        sub_text = f"of {_usd(all_limits)} limit" if all_limits else ""
        lines.extend(_card("💵", "Daily Rem", _usd(combined_rem), sub_text))
    lines.append("</div></div>")
    return lines


def _render_one_provider(data: dict, label: str, tag_class: str) -> List[str]:
    """Render a complete provider block: cards, subscription, models, daily usage."""
    d = _extract_display(data)
    plan_name = data.get("planName", "")
    title = plan_name.rsplit("-", 1)[-1] if "-" in plan_name else label
    plan_suffix = _plan_suffix(data)

    pages = []
    pages.append(f'<div class="section provider-section {tag_class}">')
    pages.append(f'<h2>{escape(title)}</h2>')
    pages.append(f'<p class="subtitle">Plan: {escape(d["plan"])} &nbsp;|&nbsp; '
                 f'Models: {escape(d["model_names"])}')
    if plan_suffix in LOCAL_COST_PLANS:
        pages[-1] += ' &nbsp;|&nbsp; <span class="muted">Cost: local estimate</span>'
    pages[-1] += '</p>'

    # summary cards
    t = _extract_totals(data, plan_suffix)
    cache_hit = _pct(t["today_cache"], t["today_cache"] + t["today_in"]) if (t["today_cache"] + t["today_in"]) > 0 else "—"
    pages.append('<div class="cards">')
    pages.extend(_card("💰", "Today Cost", _usd(t["today_cost"]), ""))
    pages.extend(_card("🧾", "Total Cost", _usd(t["total_cost"]), ""))
    pages.extend(_card("📊", "Today Req", _num(t["today_reqs"]), ""))
    pages.extend(_card("📁", "Total Req", _num(t["total_reqs"]), ""))
    pages.extend(_card("⚡", "Cache Hit", cache_hit, "input tokens from cache today"))
    pages.extend(_card("🚀", "Today Tok", _num(t["today_total"]),
                        f"in={_num(t['today_in'])}  out={_num(t['today_out'])}"))
    pages.extend(_card("📦", "Total Tok", _num(t["total_tokens"]),
                        f"in={_num(t['total_in'])}  out={_num(t['total_out'])}  cache={_num(t['total_cache'])}"))
    if t["total_tokens"] > 0:
        unit = t["total_cost"] / t["total_tokens"] * 1_000_000
        pages.extend(_card("💲", "Unit Cost", f"${unit:.3f}/M", ""))
    if t["remaining"] is not None and t["remaining"] > 0:
        sub_text = f"of {_usd(t['daily_limit'])} limit" if t["daily_limit"] else ""
        pages.extend(_card("💵", "Daily Rem", _usd(t["remaining"]), sub_text))
    elif t["daily_limit"] == 0:
        pages.extend(_card("💵", "Daily Rem", "∞", "Unlimited"))
    if t["expires"]:
        pages.extend(_card("📅", "Expires", _parse_iso_date(t["expires"]), escape(t["expires"])))
    pages.append("</div>")

    # subscription
    if d["sub"]:
        pages.append('<h3 style="margin-top:16px">📈 Subscription</h3>')
        pages.extend(_render_subscription(d["sub"]))

    # model breakdown
    if d["model_stats"]:
        pages.append('<h3 style="margin-top:24px">🔬 Model Breakdown</h3>')
        pages.extend(_render_model_table(d["model_stats"], plan_suffix))

    # daily usage
    if d["daily_usage"]:
        pages.append(f'<h3 style="margin-top:24px">📅 Daily Usage '
                     f'<span class="muted">(last {len(d["daily_usage"])} days)</span></h3>')
        pages.extend(_render_daily_chart(d["daily_usage"], plan_suffix))

    pages.append("</div>")  # .provider-section
    return pages


# ── HTML builder ────────────────────────────────────────────────────────────

def _build_html(sections: List[Tuple[Dict, str]], warnings: List[str]) -> str:
    """Generate a self-contained HTML page from provider sections and warnings."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    label = "MinieyeL4"

    pages = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"<title>AI Usage Report — {now_str}</title>",
        "<style>",
        _css(),
        "</style>",
        "</head>",
        "<body>",
    ]

    # header
    pages.append('<div class="header">')
    pages.append(f'<h1>AI Usage Report — <span class="provider-badge">{escape(label)}</span></h1>')
    pages.append(f'<p class="subtitle">Generated: {now_str}</p>')
    pages.append(f'<p class="subtitle" style="font-size:12px;margin-top:2px">价格均为估计，非真实费用仅供参考</p>')
    pages.append("</div>")

    # warnings
    pages.extend(_render_warnings(warnings))

    # combined summary when multiple providers
    if len(sections) > 1:
        all_totals = [_extract_totals(data, _plan_suffix(data)) for data, _ in sections]
        pages.extend(_render_combined_cards(all_totals))

    # each provider section
    for data, sec_label in sections:
        tag_class = sec_label.lower().replace("/", "-").replace(" ", "-")
        pages.extend(_render_one_provider(data, sec_label, tag_class))

    # no data at all
    if not sections:
        pages.append('<div class="section"><h2>No data</h2>'
                     '<p>Both API targets failed. See warnings above.</p></div>')

    # footer
    pages.append('<div class="footer">')
    pages.append(f'Generated by ai_usage_html.py &nbsp;|&nbsp; {now_str}')
    pages.append("</div>")

    pages.append("</body>")
    pages.append("</html>")
    return "\n".join(pages)


def _css() -> str:
    """Return the complete embedded stylesheet."""
    return textwrap.dedent("""
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
      background: #0d1117; color: #e6edf3;
      min-height: 100vh; padding: 32px 24px 64px;
    }
    .header {
      text-align: center; margin-bottom: 40px;
    }
    .header h1 {
      font-size: 28px; font-weight: 700; letter-spacing: -0.5px;
    }
    .provider-badge {
      color: #58a6ff;
    }
    .subtitle {
      color: #8b949e; font-size: 14px; margin-top: 6px;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 16px; margin-bottom: 40px;
    }
    .card {
      background: #161b22; border: 1px solid #30363d;
      border-radius: 10px; padding: 20px;
      transition: border-color 0.2s;
    }
    .card:hover { border-color: #58a6ff; }
    .card-icon { font-size: 24px; margin-bottom: 8px; }
    .card-title {
      font-size: 12px; text-transform: uppercase;
      letter-spacing: 0.5px; color: #8b949e; margin-bottom: 4px;
    }
    .card-value {
      font-size: 24px; font-weight: 700; color: #f0f6fc;
    }
    .card-sub {
      display: block; font-size: 12px; color: #8b949e; margin-top: 4px;
    }
    .section {
      background: #161b22; border: 1px solid #30363d;
      border-radius: 12px; padding: 24px; margin-bottom: 24px;
    }
    .section h2 { font-size: 18px; margin-bottom: 16px; }
    .section h3 { font-size: 14px; margin-bottom: 12px; color: #8b949e; }
    .combined-section {
      border-color: #d2a8ff;
    }
    .provider-section.gpt {
      border-color: #3fb950;
    }
    .provider-section.claude-ds {
      border-color: #58a6ff;
    }
    .provider-section h2 {
      font-size: 18px; margin-bottom: 4px;
    }
    .provider-section .subtitle {
      margin-bottom: 16px;
    }
    .muted { color: #8b949e; font-weight: 400; font-size: 14px; }
    .warning-section { border-color: #d29922; }
    .warning-list { list-style: none; padding: 0; }
    .warning-list li {
      color: #d29922; font-size: 13px; padding: 4px 0;
      border-bottom: 1px solid #21262d;
    }
    .warning-list li:last-child { border-bottom: none; }
    .sub-grid { display: flex; flex-direction: column; gap: 12px; }
    .sub-item {
      display: grid;
      grid-template-columns: 80px 1fr 140px 60px;
      align-items: center; gap: 12px;
    }
    .sub-label { font-weight: 600; color: #e6edf3; }
    .sub-bar {
      background: #21262d; border-radius: 4px; height: 10px; overflow: hidden;
    }
    .sub-fill {
      background: linear-gradient(90deg, #3fb950, #238636);
      height: 100%; border-radius: 4px; transition: width 0.3s;
    }
    .sub-val { font-size: 13px; color: #c9d1d9; text-align: right; }
    .sub-pct { font-size: 13px; color: #8b949e; text-align: right; }
    .chart { margin-bottom: 8px; }
    .chart-row {
      display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
    }
    .chart-label {
      width: 56px; text-align: right; font-size: 12px;
      color: #8b949e; flex-shrink: 0;
    }
    .chart-track {
      flex: 1 1 0%; min-width: 0; height: 18px;
    }
    .chart-bar {
      display: block; height: 100%;
      background: linear-gradient(90deg, #3fb950, #58a6ff);
      border-radius: 3px; min-width: 6px;
      transition: width 0.3s;
    }
    .chart-val {
      font-size: 12px; color: #c9d1d9; font-variant-numeric: tabular-nums;
      flex-shrink: 0;
    }
    .table-wrap { overflow-x: auto; }
    .data-table {
      width: 100%; border-collapse: collapse; font-size: 13px;
    }
    .data-table th, .data-table td {
      padding: 10px 14px; text-align: right;
      border-bottom: 1px solid #21262d;
    }
    .data-table th {
      background: #0d1117; font-weight: 600; color: #8b949e;
      font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px;
    }
    .data-table tbody tr:hover { background: #1c2128; }
    .data-table td:first-child { text-align: left; color: #e6edf3; }
    .cost-cell { font-weight: 600; color: #f0883e; }
    .footer {
      text-align: center; font-size: 12px; color: #484f58;
      margin-top: 48px; padding-top: 24px;
      border-top: 1px solid #21262d;
    }
    """).strip()


# ── main ────────────────────────────────────────────────────────────────────

# Per-target config: name, base URL, and auth-file source.
TARGET_CONFIG = {
    "gpt": {
        "name": "GPT",
        "base_url": GPT_API_BASE_URL,
        "auth_file": Path.home() / ".codex" / "auth.json",
        "key_path": ["OPENAI_API_KEY"],
    },
    "claude": {
        "name": "Claude/DS",
        "base_url": CLAUDE_API_BASE_URL,
        "auth_file": Path.home() / ".claude" / "settings.json",
        "key_path": ["env", "ANTHROPIC_AUTH_TOKEN"],
    },
}


def _read_key_from_file(path: Path, key_path: List[str]) -> str:
    """Read a value from a JSON file at *path* following *key_path*."""
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for k in key_path:
            data = data.get(k, {})
            if not data:
                return ""
        return str(data)
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return ""


def _fetch_target(cfg: dict) -> Tuple[Optional[Dict], str]:
    """Query usage endpoint for one target. Returns (data, warning).

    On success: (data_dict, "").  On failure: (None, warning_message).
    """
    api_key = _read_key_from_file(cfg["auth_file"], cfg["key_path"])
    if not api_key:
        return None, f"{cfg['name']}: No API key — missing {cfg['auth_file']}"
    try:
        usage_url = cfg["base_url"].rstrip("/") + "/usage"
        return _api_get(usage_url, api_key), ""
    except SystemExit as e:
        return None, f"{cfg['name']}: {e}"


def _render_warnings(warnings: List[str]) -> List[str]:
    """Return HTML for a warnings section."""
    if not warnings:
        return []
    lines = ['<div class="section warning-section">', '<h2>⚠ Warnings</h2>', '<ul class="warning-list">']
    for w in warnings:
        lines.append(f"<li>{escape(w)}</li>")
    lines.extend(["</ul>", "</div>"])
    return lines


def main() -> None:
    """Query both targets, render combined HTML with warnings for failures."""
    warnings: List[str] = []
    sections: List[Tuple[Dict, str]] = []
    sys.stderr.write("🔍 Fetching MinieyeL4 API usage…\n")

    for t in ("gpt", "claude"):
        cfg = TARGET_CONFIG[t]
        data, warn = _fetch_target(cfg)
        if warn:
            warnings.append(warn)
        if data is not None:
            sections.append((data, cfg["name"]))

    for w in warnings:
        sys.stderr.write(f"  ⚠ {w}\n")

    if not sections:
        sys.stderr.write("No valid API key found or both API keys are invalid.\n")
        sys.exit(1)

    html = _build_html(sections, warnings)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = SCRIPT_DIR / f"ai_usage_report_{ts}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    sys.stderr.write(f"✅ {out_path} ({len(html):,} bytes) — {len(sections)}/2 targets OK\n")


if __name__ == "__main__":
    main()
