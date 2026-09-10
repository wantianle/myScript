#!/usr/bin/env python3
# mprobe — 公司网关全模型探测（延迟 / 速度 / 流畅度 / 可靠性）
# 覆盖两个 key 的全部可路由模型，逐模型流式采样，评估:
#   TTFT(首字延迟) / 总耗时 / 输出速度(~tok/s) / 流内最大停顿 / 成功率
#
# 用法:
#   mprobe                      # 全部 key × 全部模型，每模型 2 次采样
#   mprobe --n 3                # 每模型 3 次采样（可靠性更准）
#   mprobe --key minieye        # 只测 minieye key
#   mprobe --models deepseek,gpt-5.6   # 只测名称含关键词的模型（逗号分隔，任一匹配）
#   mprobe --list               # 只列出各 key 可路由的模型
import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

BASE = "https://sub2api.minieye.tech/v1"
OC_CONFIG = os.path.expanduser("~/.config/opencode/opencode.jsonc")
CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
PROMPT = "从1数到30，每行一个数字，不要解释。"
MAX_TOKENS = 1200


# ── 工具函数 ──────────────────────────────────────

def dwidth(s):
    return sum(2 if unicodedata.east_asian_width(c) in "FW" else 1 for c in str(s))


def pad(s, w):
    return str(s) + " " * max(0, w - dwidth(s))


def rpad(s, w):
    return " " * max(0, w - dwidth(s)) + str(s)


def strip_jsonc(s):
    out, i, n = [], 0, len(s)
    instr = esc = False
    while i < n:
        c = s[i]
        if instr:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
            i += 1
            continue
        if c == '"':
            instr = True
            out.append(c)
            i += 1
            continue
        if s.startswith("//", i):
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if s.startswith("/*", i):
            j = s.find("*/", i)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def load_keys():
    """从 opencode.jsonc 与 claude settings 读取两个 key。"""
    keys = {}
    try:
        cfg = json.loads(strip_jsonc(open(OC_CONFIG, encoding="utf-8").read()))
        prov = cfg.get("provider", {})
        mk = ((prov.get("minieye") or {}).get("options") or {}).get("apiKey")
        if mk:
            keys["minieye"] = mk
    except Exception as e:
        print(f"! 读取 {OC_CONFIG} 失败: {e}", file=sys.stderr)
    try:
        cs = json.load(open(CLAUDE_SETTINGS, encoding="utf-8"))
        ck = (cs.get("env") or {}).get("ANTHROPIC_AUTH_TOKEN")
        if ck:
            keys["claude"] = ck
    except Exception as e:
        print(f"! 读取 {CLAUDE_SETTINGS} 失败: {e}", file=sys.stderr)
    if "claude" not in keys:
        try:
            cfg = json.loads(strip_jsonc(open(OC_CONFIG, encoding="utf-8").read()))
            ck = ((cfg.get("provider", {}).get("minieye-claude") or {}).get("options") or {}).get("apiKey")
            if ck:
                keys["claude"] = ck
        except Exception:
            pass
    if "minieye" not in keys:
        m = re.search(r'"apiKey"\s*:\s*"(sk-[^"]+)"', open(OC_CONFIG, encoding="utf-8").read())
        if m:
            keys["minieye"] = m.group(1)
    return keys


def fetch_models(key):
    req = urllib.request.Request(BASE + "/models", headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("data") or data.get("models") or []
    return [m.get("id") or m.get("name") for m in items if isinstance(m, dict)]


# ── 单次探测 ──────────────────────────────────────

def probe(key, model, timeout):
    payload = {"model": model, "messages": [{"role": "user", "content": PROMPT}],
               "max_tokens": MAX_TOKENS, "stream": True}
    req = urllib.request.Request(
        BASE + "/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t0 = time.time()
    ttft = None
    last = None
    maxgap = 0.0
    events = 0
    content, reasoning = [], []
    usage = None
    err = None
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        for raw in r:
            now = time.time()
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                j = json.loads(data)
            except Exception:
                continue
            if isinstance(j, dict) and j.get("error"):
                err = str(j["error"])[:140].replace("\n", " ")
                break
            if last is not None:
                gap = now - last
                if gap > maxgap:
                    maxgap = gap
            last = now
            events += 1
            if isinstance(j, dict):
                if j.get("usage"):
                    usage = j["usage"]
                for ch in j.get("choices", []):
                    d = ch.get("delta", {}) or {}
                    think = d.get("reasoning_content") or d.get("reasoning")
                    if ttft is None and (d.get("content") or think):
                        ttft = now - t0
                    if d.get("content"):
                        content.append(d["content"])
                    if think:
                        reasoning.append(think)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "ignore")[:200].replace("\n", " ")
        except Exception:
            body = ""
        err = f"HTTP {e.code} {body}"
    except Exception as e:
        err = type(e).__name__ + ": " + str(e)[:120]
    total = time.time() - t0
    text, think = "".join(content), "".join(reasoning)
    if err is None and events == 0:
        err = "(空响应)"
    toks = None
    if usage and usage.get("completion_tokens"):
        toks = usage["completion_tokens"]
    elif text or think:
        allt = text + think
        cjk = sum(1 for ch in allt if ord(ch) > 127)
        toks = int(cjk / 1.6 + (len(allt) - cjk) / 4) + 1
    return {"ok": err is None, "ttft": ttft, "total": total, "maxgap": maxgap,
            "toks": toks, "err": err, "events": events}


def summarize(samples):
    ok = [s for s in samples if s["ok"]]
    n = len(samples)
    ttfts = [s["ttft"] for s in ok if s["ttft"] is not None]
    totals = [s["total"] for s in ok]
    gaps = [s["maxgap"] for s in ok]
    tps = []
    for s in ok:
        if s["toks"] and s["total"] > 0:
            dt = (s["total"] - s["ttft"]) if s["ttft"] is not None else s["total"]
            tps.append(s["toks"] / max(dt, 0.05))
    r = {
        "n": n,
        "ok_rate": len(ok) / n if n else 0.0,
        "ttft": sum(ttfts) / len(ttfts) if ttfts else None,
        "total": sum(totals) / len(totals) if totals else None,
        "gap": max(gaps) if gaps else None,
        "tps": sum(tps) / len(tps) if tps else None,
    }
    # 评级
    t = r["ttft"]
    r["v_speed"] = "—" if t is None else ("快" if t <= 1.0 else ("中" if t <= 3.0 else "慢"))
    g = r["gap"]
    r["v_flow"] = "—" if g is None else ("好" if g <= 2.0 else ("中" if g <= 6.0 else "差"))
    o = r["ok_rate"]
    r["v_rel"] = "好" if o >= 1.0 else ("中" if o >= 0.5 else "差")
    return r


# ── 输出 ──────────────────────────────────────────

def f_s(v):
    return "—" if v is None else f"{v:.2f}"


def print_table(results):
    rows = [(k, m, summarize(ss)) for k, m, ss in results]
    if not rows:
        return
    wm = max(dwidth(m) for _, m, _ in rows)
    wm = max(wm, 24)
    hdr = (pad("key", 8) + " " + pad("模型", wm) + " " + rpad("n", 3) + " "
           + rpad("ok%", 5) + " " + rpad("TTFT(s)", 8) + " " + rpad("总耗时(s)", 9) + " "
           + rpad("~tok/s", 7) + " " + rpad("停顿(s)", 8) + "  "
           + pad("速度", 6) + pad("流畅", 6) + pad("可靠", 6))
    print(hdr)
    print("─" * dwidth(hdr))
    for k, m, r in rows:
        line = (pad(k, 8) + " " + pad(m, wm) + " " + rpad(str(r["n"]), 3) + " "
                + rpad(f"{r['ok_rate']*100:.0f}%", 5) + " " + rpad(f_s(r["ttft"]), 8) + " "
                + rpad(f_s(r["total"]), 9) + " " + rpad("—" if r["tps"] is None else f"{r['tps']:.1f}", 7) + " "
                + rpad(f_s(r["gap"]), 8) + "  "
                + pad(r["v_speed"], 6) + pad(r["v_flow"], 6) + pad(r["v_rel"], 6))
        print(line)


def print_legend():
    print()
    print("说明: TTFT=首字延迟; 总耗时=整次请求; ~tok/s=输出速度(含思考, 近似); "
          "停顿=流式响应两段数据间最大间隔(流畅度); ok%=采样成功率(可靠性)")
    print("评级: 速度 快≤1s/中≤3s/慢>3s | 流畅 好≤2s/中≤6s/差>6s | 可靠 好=100%/中≥50%/差<50%")


# ── 主流程 ────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="公司网关全模型探测（延迟/速度/流畅度/可靠性）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=2, help="每个模型采样次数（默认 2）")
    ap.add_argument("--timeout", type=float, default=60, help="单次请求超时秒数（默认 60）")
    ap.add_argument("--key", default="all", help="只测指定 key: minieye / claude / all（默认 all）")
    ap.add_argument("--models", default="", help="模型名关键词过滤，逗号分隔，任一匹配")
    ap.add_argument("--list", action="store_true", help="只列出各 key 可路由的模型")
    args = ap.parse_args()

    keys = load_keys()
    sel = [k for k in ("minieye", "claude") if k in keys]
    if args.key != "all":
        sel = [k for k in sel if k == args.key]
    if not sel:
        print("没有可用 key（检查 opencode.jsonc / claude settings）")
        sys.exit(2)

    filters = [s.strip() for s in args.models.split(",") if s.strip()]
    plans = []
    for k in sel:
        try:
            models = fetch_models(keys[k])
        except Exception as e:
            print(f"! [{k}] 获取模型列表失败: {e}")
            continue
        if filters:
            models = [m for m in models if any(f in m for f in filters)]
        plans.append((k, models))

    if args.list:
        for k, ms in plans:
            print(f"[{k}] {len(ms)} 个模型")
            for m in ms:
                print("  " + m)
        return

    total = sum(len(ms) for _, ms in plans)
    print(f"mprobe — {time.strftime('%Y-%m-%d %H:%M:%S')}  "
          f"采样 n={args.n}  超时 {args.timeout:g}s  组合 {total}")
    print()
    results = []
    idx = 0
    for k, models in plans:
        for m in models:
            idx += 1
            samples = []
            for _ in range(args.n):
                samples.append(probe(keys[k], m, args.timeout))
                time.sleep(0.3)
            results.append((k, m, samples))
            r = summarize(samples)
            flag = "OK" if r["ok_rate"] >= 1.0 else ("PART" if r["ok_rate"] > 0 else "FAIL")
            err = next((s["err"] for s in samples if s["err"]), "")
            print(f"[{idx:>3}/{total}] {k}/{m}  ok={r['ok_rate']*100:.0f}%  "
                  f"ttft={f_s(r['ttft'])}  停顿={f_s(r['gap'])}  {flag}  {err[:70]}", flush=True)
    print()
    print_table(results)
    print_legend()

    fails = [(k, m, s["err"]) for k, m, ss in results for s in ss if not s["ok"]]
    print()
    if fails:
        print(f"异常明细（{len(fails)} 条）:")
        for k, m, err in fails[:40]:
            print(f"  [{k}] {m}: {err}")
    else:
        print(f"全部正常：{total} 个组合 × {args.n} 次采样无失败。")


if __name__ == "__main__":
    main()
