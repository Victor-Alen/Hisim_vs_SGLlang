# HiSim PD Sweep Reasonableness Review

## Scope
- Data source: 30 run folders under /mnt/nfs02/users/yaoyao1/projects/hisim/cases_same_seed_flush_cache (5 rr x 3 il x 2 ol).
- Objective: check whether trends look reasonable, and identify suspicious results.

## How These Results Relate To PD Disaggregated Mode
- In PD disaggregated mode, prefill and decode are modeled as separate stages with potentially different bottlenecks.
- For this run, topology is effectively 1 prefill replica + 1 decode replica, so behavior resembles a serial two-stage pipeline.
- Expected trends:
  - Increasing input length should mostly raise TTFT.
  - Increasing output length should mostly raise TPOT and E2E.
  - Increasing request rate should raise queueing and eventually flatten throughput.

## High-Level Verdict
- Primary trend checks pass, and flush-cache appears sufficient to avoid the severe reuse contamination seen in the old fixed-seed no-flush run.
- Prefix cache reuse range is [0.0068, 0.0166] with mean 0.0104.

## Reasonableness Checks
- Completed requests: all runs have completed=200 -> True.
- Monotonic violations for throughput-vs-rr: 0.
- Monotonic violations for TTFT-vs-il: 0.
- mean_queue_ms negative in 30/30 runs (tiny ~-5e-06 artifact).
- mean_kv_transfer_ms equals 0 in 30/30 runs.
- mean_decode_queue_ms equals 0 in 30/30 runs.
- prefix_cache_reused_ratio >= 0.99 in 0/30 runs.

## Diagram 1: Request Throughput vs Request Rate (OL=128)
- Legend (line order in chart):
  - Line 1: IL=256, OL=128
  - Line 2: IL=1024, OL=128
  - Line 3: IL=2048, OL=128
```mermaid
xychart-beta
    title "Req Throughput vs RR (OL=128)"
    x-axis "RR" [1, 2, 4, 8, 12]
    y-axis "req/s" 0 --> 11.5
    line [0.9369, 1.8664, 3.7036, 7.2785, 10.6588]
    line [0.9369, 1.8662, 3.7027, 7.271, 10.5677]
    line [0.9369, 1.8662, 3.7022, 7.2221, 10.3879]
```
- Interpretation:
  - Throughput scales with RR for all lines, and ordering remains IL=256 > IL=1024 > IL=2048 across RR.

## Diagram 2: Request Throughput vs Request Rate (OL=512)
- Legend (line order in chart):
  - Line 1: IL=256, OL=512
  - Line 2: IL=1024, OL=512
  - Line 3: IL=2048, OL=512
```mermaid
xychart-beta
    title "Req Throughput vs RR (OL=512)"
    x-axis "RR" [1, 2, 4, 8, 12]
    y-axis "req/s" 0 --> 11.5
    line [0.9204, 1.7947, 3.4136, 6.2041, 8.4645]
    line [0.9202, 1.794, 3.4084, 6.1413, 8.1325]
    line [0.9196, 1.7912, 3.3936, 5.8657, 7.0817]
```
- Interpretation:
  - Throughput is generally lower than OL=128 at medium/high RR, consistent with heavier decode work.

## Diagram 3: Mean E2E Latency vs Request Rate (IL=1024)
- Legend (line order in chart):
  - Line 1: OL=128, IL=1024
  - Line 2: OL=512, IL=1024
```mermaid
xychart-beta
    title "Mean E2E vs RR (IL=1024)"
    x-axis "RR" [1, 2, 4, 8, 12]
    y-axis "ms" 0 --> 7111.3
    line [770.5239, 811.1144, 883.6244, 1065.7159, 1280.0031]
    line [3063.769, 3266.821, 3661.0189, 4875.3938, 6349.392]
```
- Interpretation:
  - OL=512 remains far above OL=128 and both increase with RR.

## Diagram 4: Mean TPOT vs Request Rate (IL=2048)
- Legend (line order in chart):
  - Line 1: OL=128, IL=2048
  - Line 2: OL=512, IL=2048
```mermaid
xychart-beta
    title "Mean TPOT vs RR (IL=2048)"
    x-axis "RR" [1, 2, 4, 8, 12]
    y-axis "ms/token" 0 --> 56.3
    line [12.3305, 13.4912, 15.9076, 23.594, 41.5184]
    line [12.7697, 14.2839, 17.6921, 34.616, 48.9458]
```
- Interpretation:
  - TPOT rises with RR, with OL=512 increasingly worse at high RR.

## Diagram 5: Mean TTFT vs Request Rate (OL=128)
- Legend (line order in chart):
  - Line 1: IL=256, OL=128
  - Line 2: IL=1024, OL=128
  - Line 3: IL=2048, OL=128
```mermaid
xychart-beta
    title "Mean TTFT vs RR (OL=128)"
    x-axis "RR" [1, 2, 4, 8, 12]
    y-axis "ms" 0 --> 138.7
    line [19.6441, 21.3878, 22.9179, 23.4462, 24.4026]
    line [37.0805, 39.6695, 41.7307, 45.0977, 48.5818]
    line [62.9117, 67.2239, 72.893, 87.0047, 120.5948]
```
- Interpretation:
  - TTFT increases with both IL and RR, consistent with prefill pressure.

## Diagram 6: Mean TTFT vs Request Rate (OL=512)
- Legend (line order in chart):
  - Line 1: IL=256, OL=512
  - Line 2: IL=1024, OL=512
  - Line 3: IL=2048, OL=512
```mermaid
xychart-beta
    title "Mean TTFT vs RR (OL=512)"
    x-axis "RR" [1, 2, 4, 8, 12]
    y-axis "ms" 0 --> 142.3
    line [22.4084, 22.9846, 23.3164, 24.0506, 24.9555]
    line [39.8869, 41.0153, 42.5377, 46.2481, 50.4321]
    line [65.7964, 68.3462, 74.291, 89.9872, 123.7281]
```
- Interpretation:
  - Separation by IL is clearer as RR increases.

## Diagram 7: Prefix Cache Reuse Ratio vs Request Rate (OL=128)
- Legend (line order in chart):
  - Line 1: IL=256, OL=128
  - Line 2: IL=1024, OL=128
  - Line 3: IL=2048, OL=128
```mermaid
xychart-beta
    title "Prefix Cache Reuse Ratio vs RR (OL=128)"
    x-axis "RR" [1, 2, 4, 8, 12]
    y-axis "ratio" 0 --> 1.05
    line [0.0166, 0.0166, 0.0166, 0.0166, 0.0166]
    line [0.0068, 0.0068, 0.0068, 0.0068, 0.0068]
    line [0.0079, 0.0079, 0.0079, 0.0079, 0.0079]
```
- Interpretation:
  - Reuse remains low in this sweep, supporting your observation that flush-cache alone is sufficient for this setup.

## Final Assessment
- Cache contamination is no longer a dominant risk in this sweep.
- Tiny negative mean_queue_ms persists as numerical noise.
- Many runs still show zero mean_kv_transfer_ms / mean_decode_queue_ms, so PD transfer/queue stress may still be underrepresented for this config.

## Recommendations
- Keep the current flush-cache methodology if your target is trend comparison under this setup.
- If you need stronger PD-transfer visibility, increase transfer stress (higher load or transfer settings) and rerun a subset.
