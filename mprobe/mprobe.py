#!/usr/bin/env python3
# mprobe — 公司网关模型探测（延迟 / 速度 / 可靠性）
# 覆盖 minieye key 的可路由模型（自动排除包装/路由/停用模型），逐模型流式采样:
#   TTFT(响应延迟) / 总耗时 / 输出速度(~tok/s) / 成功率
#
# 用法:
#   mprobe                      # 全部模型，每模型 2 次采样
#   mprobe --n 3                # 每模型 3 次采样（可靠性更准）
#   mprobe --models deepseek,gpt-5.6   # 只测名称含关键词的模型（逗号分隔，任一匹配）
#   mprobe --list               # 只列出将探测的模型
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
PROMPT = "从1数到30，每行一个数字，不要解释。"
MAX_TOKENS = 1200
# 排除模型: 包装/路由类(Auto / codex-auto-review / gpt-reserve)、
# 专用型(gpt-5.4-mini / gpt-5.3-codex-spark)、
# 重复别名(deepseek-flash 与 deepseek-v4-flash-vision-exp 均路由到 deepseek-v4-flash 同一后端)
SKIP_MODELS = {
    "Auto",
    "codex-auto-review",
    "gpt-reserve",
    "gpt-5.4-mini",
    "gpt-5.3-codex-spark",
    "deepseek-flash",
    "deepseek-v4-flash-vision-exp",
}


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


def load_key():
    """从 opencode.jsonc 读取 minieye key。"""
    try:
        cfg = json.loads(strip_jsonc(open(OC_CONFIG, encoding="utf-8").read()))
        mk = ((cfg.get("provider", {}).get("minieye") or {}).get("options") or {}).get("apiKey")
        if mk:
            return mk
    except Exception as e:
        print(f"! 读取 {OC_CONFIG} 失败: {e}", file=sys.stderr)
    m = re.search(r'"apiKey"\s*:\s*"(sk-[^"]+)"', open(OC_CONFIG, encoding="utf-8").read())
    if m:
        return m.group(1)
    print("没有找到 minieye apiKey")
    sys.exit(2)


def fetch_models(key):
    req = urllib.request.Request(BASE + "/models", headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("data") or data.get("models") or []
    return [m.get("id") or m.get("name") for m in items if isinstance(m, dict)]


# ── 单次延迟探测 ──────────────────────────────────

def probe(key, model, timeout):
    payload = {"model": model, "messages": [{"role": "user", "content": PROMPT}],
               "max_tokens": MAX_TOKENS, "stream": True}
    req = urllib.request.Request(
        BASE + "/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t0 = time.time()
    ttft = None
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
    return {"ok": err is None, "ttft": ttft, "total": total,
            "toks": toks, "err": err, "events": events}


# ── 汇总与输出 ────────────────────────────────────

def summarize(samples):
    ok = [s for s in samples if s["ok"]]
    n = len(samples)
    ttfts = [s["ttft"] for s in ok if s["ttft"] is not None]
    totals = [s["total"] for s in ok]
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
        "tps": sum(tps) / len(tps) if tps else None,
    }
    t = r["ttft"]
    r["v_speed"] = "—" if t is None else ("快" if t <= 1.0 else ("中" if t <= 3.0 else "慢"))
    o = r["ok_rate"]
    r["v_rel"] = "好" if o >= 1.0 else ("中" if o >= 0.5 else "差")
    return r


def f_s(v):
    return "—" if v is None else f"{v:.2f}"


def print_table(results):
    rows = [(m, summarize(ss)) for m, ss in results]
    if not rows:
        return
    wm = max(max(dwidth(m) for m, _ in rows), 24)
    hdr = (pad("模型", wm) + " " + rpad("n", 3) + " "
           + rpad("ok%", 5) + " " + rpad("TTFT(s)", 8) + " " + rpad("总耗时(s)", 9) + " "
           + rpad("~tok/s", 7) + "  "
           + pad("速度", 6) + pad("可靠", 6))
    print(hdr)
    print("─" * dwidth(hdr))
    for m, r in rows:
        line = (pad(m, wm) + " " + rpad(str(r["n"]), 3) + " "
                + rpad(f"{r['ok_rate']*100:.0f}%", 5) + " " + rpad(f_s(r["ttft"]), 8) + " "
                + rpad(f_s(r["total"]), 9) + " " + rpad("—" if r["tps"] is None else f"{r['tps']:.1f}", 7) + "  "
                + pad(r["v_speed"], 6) + pad(r["v_rel"], 6))
        print(line)


def print_legend():
    print()
    print("说明: TTFT=首字延迟(响应延迟); 总耗时=整次请求; ~tok/s=输出速度(含思考, 近似); ok%=采样成功率(可靠性)")
    print("评级: 速度 快≤1s/中≤3s/慢>3s | 可靠 好=100%/中≥50%/差<50%")


# ── 主流程 ────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="公司网关模型探测（延迟/速度/可靠性）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=2, help="每个模型采样次数（默认 2）")
    ap.add_argument("--timeout", type=float, default=60, help="单次请求超时秒数（默认 60）")
    ap.add_argument("--models", default="", help="模型名关键词过滤，逗号分隔，任一匹配")
    ap.add_argument("--list", action="store_true", help="只列出将探测的模型")
    args = ap.parse_args()

    key = load_key()
    try:
        all_models = fetch_models(key)
    except Exception as e:
        print(f"! 获取模型列表失败: {e}")
        sys.exit(2)

    skipped = [m for m in all_models if m in SKIP_MODELS]
    models = [m for m in all_models if m not in SKIP_MODELS]
    filters = [s.strip() for s in args.models.split(",") if s.strip()]
    if filters:
        models = [m for m in models if any(f in m for f in filters)]

    if args.list:
        print(f"[minieye] 将探测 {len(models)} 个模型（跳过 {len(skipped)} 个）")
        for m in models:
            print("  " + m)
        if skipped:
            print("已跳过: " + ", ".join(skipped))
        return

    print(f"mprobe — {time.strftime('%Y-%m-%d %H:%M:%S')}  采样 n={args.n}  超时 {args.timeout:g}s  "
          f"模型 {len(models)}" + (f"（跳过 {len(skipped)} 个）" if skipped else ""))
    print()
    results = []
    for idx, m in enumerate(models, 1):
        samples = []
        for _ in range(args.n):
            samples.append(probe(key, m, args.timeout))
            time.sleep(0.3)
        results.append((m, samples))
        r = summarize(samples)
        flag = "OK" if r["ok_rate"] >= 1.0 else ("PART" if r["ok_rate"] > 0 else "FAIL")
        err = next((s["err"] for s in samples if s["err"]), "")
        print(f"[{idx:>3}/{len(models)}] {m}  ok={r['ok_rate']*100:.0f}%  "
              f"ttft={f_s(r['ttft'])}  {flag}  {err[:70]}", flush=True)

    print()
    print_table(results)
    print_legend()

    fails = [(m, s["err"]) for m, ss in results for s in ss if not s["ok"]]
    print()
    if fails:
        print(f"异常明细（{len(fails)} 条）:")
        for m, err in fails[:40]:
            print(f"  {m}: {err}")
    else:
        print(f"全部正常：{len(models)} 个模型 × {args.n} 次采样无失败。")


if __name__ == "__main__":
    main()
