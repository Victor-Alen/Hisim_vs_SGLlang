#!/usr/bin/env python3
"""
HiSim per-item TTFT breakdown extractor.

Works on EXISTING request.jsonl output — no code changes to HiSim needed.

Usage:
    python hisim_breakdown_analysis.py --request-jsonl /tmp/hisim/simulation/request.jsonl
    python hisim_breakdown_analysis.py --request-jsonl path/to/request.jsonl [--http-tok-us-per-token 5.6]

Fields derivable without any code change:
    queue_wait_ms       = queue_end - created_time
    prefill_compute_ms  ≈ gen_token_latencies[0] - queue_wait  (contains launch_delay too)
    first_decode_ms     = gen_token_latencies[1]               (= TPOT[0])
    corrected_ttft_ms   = gen_token_latencies[0] + gen_token_latencies[1]

Optional analytical model:
    http_tokenize_ms    ≈ http_tok_us_per_token * input_length / 1000
"""

import argparse
import json
import numpy as np
from pathlib import Path


def load_requests(path: str) -> list[dict]:
    reqs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                reqs.append(json.loads(line))
    return reqs


def breakdown_request(r: dict, http_tok_us_per_token: float = 5.6) -> dict:
    gl = r["gen_token_latencies"]
    created   = r["created_time"]
    q_start   = r["queue_start"]
    q_end     = r["queue_end"]

    queue_wait_s       = q_end - created                          # queue from arrival to scheduled
    prefill_compute_s  = gl[0] - queue_wait_s                     # prefill + launch_delay bundled
    first_decode_s     = gl[1] if len(gl) > 1 else 0.0           # already computed by HiSim
    corrected_ttft_s   = gl[0] + first_decode_s
    hisim_ttft_s       = gl[0]                                    # HiSim's own TTFT (queue+prefill)
    http_tokenize_s    = http_tok_us_per_token * r["input_length"] / 1e6  # analytical model

    tpot_s = np.mean(gl[2:]) if len(gl) > 2 else (gl[1] if len(gl) > 1 else 0.0)

    return {
        "rid":                r["rid"],
        "input_length":       r["input_length"],
        "output_length":      r["output_length"],
        # Already in request.jsonl — no code change
        "queue_wait_ms":      queue_wait_s * 1000,
        "prefill_compute_ms": prefill_compute_s * 1000,   # includes ~0.5ms launch_delay
        "first_decode_ms":    first_decode_s * 1000,
        "tpot_ms":            tpot_s * 1000,
        # Derived
        "hisim_ttft_ms":      hisim_ttft_s * 1000,
        "corrected_ttft_ms":  corrected_ttft_s * 1000,
        # Analytical model (optional)
        "http_tokenize_modeled_ms": http_tokenize_s * 1000,
        "fully_corrected_ttft_ms":  (corrected_ttft_s + http_tokenize_s) * 1000,
    }


def summarize(rows: list[dict]) -> dict:
    def pct(vals, p): return float(np.percentile(vals, p)) if vals else 0.0
    def mean(vals):   return float(np.mean(vals)) if vals else 0.0
    def median(vals): return float(np.median(vals)) if vals else 0.0

    keys = ["queue_wait_ms", "prefill_compute_ms", "first_decode_ms", "tpot_ms",
            "hisim_ttft_ms", "corrected_ttft_ms",
            "http_tokenize_modeled_ms", "fully_corrected_ttft_ms"]
    result = {}
    for k in keys:
        vals = [r[k] for r in rows]
        result[f"mean_{k}"]   = mean(vals)
        result[f"median_{k}"] = median(vals)
        result[f"p99_{k}"]    = pct(vals, 99)
    return result


def main():
    parser = argparse.ArgumentParser(description="HiSim per-item TTFT breakdown")
    parser.add_argument("--request-jsonl", required=True, help="Path to HiSim request.jsonl")
    parser.add_argument("--http-tok-us-per-token", type=float, default=5.6,
                        help="Analytical HTTP+tokenize model: µs per input token (default=5.6)")
    parser.add_argument("--per-request", action="store_true", help="Print per-request rows")
    args = parser.parse_args()

    reqs = load_requests(args.request_jsonl)
    print(f"Loaded {len(reqs)} requests from {args.request_jsonl}")
    print(f"HTTP+tokenize model: {args.http_tok_us_per_token:.1f} µs/token\n")

    rows = [breakdown_request(r, args.http_tok_us_per_token) for r in reqs]

    if args.per_request:
        hdr = f"{'rid[:8]':<10} {'IL':>5} {'OL':>5} {'queue':>7} {'pfx':>7} {'dec1':>7} {'hisim_ttft':>11} {'corr_ttft':>10} {'+http_ttft':>11}"
        print(hdr); print("-" * len(hdr))
        for r in rows:
            print(f"{r['rid'][:8]:<10} {r['input_length']:>5} {r['output_length']:>5} "
                  f"{r['queue_wait_ms']:>7.2f} {r['prefill_compute_ms']:>7.2f} "
                  f"{r['first_decode_ms']:>7.2f} {r['hisim_ttft_ms']:>11.2f} "
                  f"{r['corrected_ttft_ms']:>10.2f} {r['fully_corrected_ttft_ms']:>11.2f}")
        print()

    stats = summarize(rows)
    il = reqs[0]["input_length"]; ol = reqs[0]["output_length"]

    print(f"{'='*70}")
    print(f"SUMMARY  IL={il}  OL={ol}  n={len(rows)}")
    print(f"{'='*70}")
    print(f"{'分项':<35} {'mean(ms)':>9} {'median(ms)':>11} {'P99(ms)':>9}")
    print("-" * 70)
    display = [
        ("queue_wait",           "queue_wait_ms"),
        ("prefill_compute(含launch)",  "prefill_compute_ms"),
        ("1st decode (gen[1])",  "first_decode_ms"),
        ("TPOT (decode均值)",    "tpot_ms"),
        ("─── HiSim TTFT (q+pfx)",      "hisim_ttft_ms"),
        ("─── Corrected TTFT (+dec1)", "corrected_ttft_ms"),
        ("HTTP+tok (解析建模)",   "http_tokenize_modeled_ms"),
        ("─── Fully Corrected (+http)", "fully_corrected_ttft_ms"),
    ]
    for name, key in display:
        print(f"  {name:<33} {stats['mean_'+key]:>9.2f} {stats['median_'+key]:>11.2f} {stats['p99_'+key]:>9.2f}")
    print()
    print(f"  分项说明 (no code change needed):")
    print(f"    queue_wait         = queue_end - created_time       (已在request.jsonl)")
    print(f"    prefill_compute    = gen_token_latencies[0] - queue_wait (已在request.jsonl)")
    print(f"    1st decode         = gen_token_latencies[1]         (已在request.jsonl)")
    print(f"    HiSim TTFT         = gen_token_latencies[0]         (原始, queue+prefill only)")
    print(f"    Corrected TTFT     = gen[0] + gen[1]                (更贴近真实TTFT)")
    print(f"    HTTP+tok (modeled) = {args.http_tok_us_per_token:.1f}µs × IL                  (解析建模)")


if __name__ == "__main__":
    main()
