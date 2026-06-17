# SGLang TTFT 分解与 HiSim 覆盖性评估报告

## 1. 执行摘要

- 本报告对 SGLang 一次完整 TTFT 做了分解测量，并给出 HiSim 覆盖边界。  
- TTFT 的计时口径是**客户端端到端首 token 延迟**，包含请求发送、服务端处理、SSE 返回与客户端解析。  
- 在零背景负载下，TTFT 主要由 **Prefill 计算 + 首个 Decode step + HTTP/Tokenize** 构成；SSE 发送仅约 0.2ms。  
- 在有请求流（rr=4）时，SGLang 相比 HiSim 的额外差值主要来自系统级排队与调度链路，而非 SSE 发送开销。

---

## 2. 测试配置

- 模型：`Qwen3-8B`
- 设备：`2 x NVIDIA RTX PRO 6000 Blackwell Server Edition`
- SGLang：DP=2，`attention_backend=triton`，`disaggregation_mode=null`
- 服务参数：`--enable-metrics --enable-request-time-stats-logging`
- 测量接口：SGLang `/generate`（streaming）
- 结果文件：
  - 图：`ttft_breakdown.png`
  - 数据：`summary_compare_rtx6000_run2.csv`

---

## 3. TTFT 计时口径（代码对齐）

SGLang `bench_serving` 的 TTFT 定义：

- 起点：`st = time.perf_counter()`（`session.post(...)` 前）
- 终点：收到并解析到**第一个 content 非空**的流式 chunk

即：

`TTFT = client_receive_first_token - client_send_request`

因此，TTFT 是客户端口径的端到端时延，而非纯 prefill kernel 时间。

---

## 4. 分解方法

使用服务端 `meta_info` 字段与客户端 TTFT 联合分解：

- HTTP 接收 + Tokenize  
  `request_sent_to_scheduler_ts - request_received_ts`
- 调度器排队  
  `queue_time`
- Prefill launch delay  
  `prefill_launch_delay`
- Prefill 计算  
  `prefill_launch_latency`
- SSE 序列化 + 发送  
  `response_sent_to_client_ts - prefill_finished_ts`
- 第一个 Decode step  
  由残差估计：  
  `TTFT_client - (上述各项之和)`

> 说明：当前返回字段不单独暴露 first decode step 时间戳，故采用残差估计。

---

## 5. 实测结果（零背景负载，streaming）

| 组成部分 | IL=256 | 占比 | IL=1024 | 占比 | IL=2048 | 占比 |
|---|---:|---:|---:|---:|---:|---:|
| HTTP 接收 + Tokenizer | 2.29 ms | 10% | 6.03 ms | 22% | 11.42 ms | 33% |
| 调度器排队queue | 0.54 ms | 2% | 0.55 ms | 2% | 0.61 ms | 2% |
| Prefill launch delay | 0.52 ms | 2% | 0.55 ms | 2% | 0.55 ms | 2% |
| prefill compute | 12.37 ms | 56% | 12.41 ms | 45% | 12.40 ms | 35% |
| 1st decode（estimate） | 6.00 ms | 27% | 7.74 ms | 28% | 9.91 ms | 28% |
| SSE serialize+send | 0.22 ms | 1% | 0.20 ms | 1% | 0.21 ms | 1% |
| **TTFT 总计** | **21.94 ms** | 100% | **27.48 ms** | 100% | **35.10 ms** | 100% |

原始展示表（按汇报版排版保留）：

```text
组成部分                 │ IL=256       │ IL=1024      │ IL=2048      │ HiSim建模？                          │
├──────────────────────────┼──────────────┼──────────────┼──────────────┼──────────────────────────────────────┤
│ HTTP接收 + Tokenize      │ 2.3ms (10%)  │ 6.0ms (22%)  │ 11.4ms (33%) │ ❌ 不建模（tokenize ∝ IL）           │
├──────────────────────────┼──────────────┼──────────────┼──────────────┼──────────────────────────────────────┤
│ 调度器排队               │ 0.5ms (2%)   │ 0.6ms (2%)   │ 0.6ms (2%)   │ ✅ 建模（仿真时钟）                  │
├──────────────────────────┼──────────────┼──────────────┼──────────────┼──────────────────────────────────────┤
│ Prefill launch delay     │ 0.5ms (2%)   │ 0.6ms (2%)   │ 0.6ms (2%)   │ ✅ 建模                              │
├──────────────────────────┼──────────────┼──────────────┼──────────────┼──────────────────────────────────────┤
│ Prefill 计算             │ 12.4ms (57%) │ 12.4ms (45%) │ 12.4ms (35%) │ ✅ 建模（aiconfigurator kernel sum） │
├──────────────────────────┼──────────────┼──────────────┼──────────────┼──────────────────────────────────────┤
│ 第一个 Decode step       │ 6.0ms (27%)  │ 7.7ms (28%)  │ 9.9ms (28%)  │ ❌ 不建模                            │
├──────────────────────────┼──────────────┼──────────────┼──────────────┼──────────────────────────────────────┤
│ SSE 序列化+发送          │ 0.22ms (1%)  │ 0.20ms (1%)  │ 0.21ms (1%)  │ ❌ 不建模（可忽略）                  │
├──────────────────────────┼──────────────┼──────────────┼──────────────┼──────────────────────────────────────┤
│ 总计 (client TTFT)       │ 21.9ms       │ 27.5ms       │ 35.1ms       │ HiSim: 19.0 / 29.0 / 36.6ms          │
```

观察：

1. `Prefill 计算`是核心项，但占比会随 IL 增大而下降（因为 tokenize 和 first decode 增长）。  
2. `SSE 序列化+发送`稳定在约 0.2ms，影响极小。  
3. `HTTP 接收 + Tokenize`随 IL 明显上升，是不可忽略项。  

---

## 6. HiSim 覆盖矩阵（对应 7 个阶段）

| 阶段 | HiSim 覆盖性 | 说明 |
|---|---|---|
| 1. HTTP 请求序列化 + 发送 | 不覆盖 | 客户端网络/HTTP 栈不在 time predictor 范围内 |
| 2. 服务器接收请求 + tokenize prompt | 基本不覆盖（或弱覆盖） | tokenizer manager 的真实处理不属于 kernel 预测核心 |
| 3. 调度器等待 | 覆盖 | 调度仿真推进全局时钟，包含 queue 行为 |
| 4. Prefill 计算 | 覆盖 | `aiconfigurator` 基于 kernel latency 表（GEMM/Attention）预测 |
| 5. 第一个 decode step | 覆盖不完整 | 首 decode 的服务链路/系统开销通常低估 |
| 6. SSE chunk 序列化并发送 | 不覆盖 | 应用层序列化与发送不在核心模型中 |
| 7. 客户端接收并解析 chunk | 不覆盖 | 客户端行为不在仿真范围内 |

---

## 7. SGLang 与 HiSim 对照

### 7.1 零负载 TTFT 对照

| IL | SGLang（零负载） | HiSim | 差值 |
|---:|---:|---:|---:|
| 256 | 21.9 ms | 19.0 ms | +2.9 ms |
| 1024 | 27.5 ms | 29.0 ms | -1.5 ms |
| 2048 | 35.1 ms | 36.6 ms | -1.5 ms |

零负载下两者接近（误差约 ±3ms）。

### 7.2 真实请求流（SGLang_Data_20260616_dp2_sweep,RR = 4）对照

| IL/OL | SGLang TTFT | HiSim TTFT | 差值 |
|---|---:|---:|---:|
| 256/128 | 30.9 ms | 16.4 ms | +14.5 ms |
| 1024/128 | 34.6 ms | 16.3 ms | +18.3 ms |
| 2048/128 | 39.3 ms | 17.2 ms | +22.1 ms |
| 256/512 | 35.4 ms | 17.2 ms | +18.2 ms |
| 1024/512 | 39.6 ms | 17.4 ms | +22.2 ms |
| 2048/512 | 44.8 ms | 17.7 ms | +27.1 ms |

有请求流时差异显著放大，主因是系统级排队与调度链路差异。

### 7.3 rr=4 分项 breakdown（补充测量，中位数口径）

说明：

- 原始 `SGLang_Data_20260616_dp2_sweep` 的 `bench_serving` 结果只包含聚合指标（TTFT/TPOT/吞吐），**不包含分项时间**。
- 为获得分项，本报告补跑了同条件流量：`rr=4`、`num_prompts=200`、`seed=42`、同 IL/OL 组合。
- 分项来源为 SGLang `/generate` streaming 的 `meta_info`（开启 `--enable-metrics --enable-request-time-stats-logging`）。

| IL/OL | median TTFT | HTTP+tokenize | queue | prefill launch delay | prefill compute | 1st decode(估计) | SSE serialize+send |
|---|---:|---:|---:|---:|---:|---:|---:|
| 256/128 | 39.99 ms | 1.56 ms (3.90%) | 0.37 ms (0.93%) | 0.43 ms (1.06%) | 13.66 ms (34.14%) | 23.40 ms (58.50%) | 0.15 ms (0.37%) |
| 1024/128 | 51.02 ms | 3.50 ms (6.86%) | 0.37 ms (0.73%) | 0.41 ms (0.81%) | 13.31 ms (26.09%) | 33.20 ms (65.08%) | 0.15 ms (0.29%) |
| 2048/128 | 77.45 ms | 6.59 ms (8.51%) | 0.42 ms (0.54%) | 0.44 ms (0.56%) | 12.84 ms (16.57%) | 57.73 ms (74.54%) | 0.15 ms (0.20%) |
| 256/512 | 39.70 ms | 2.14 ms (5.38%) | 0.41 ms (1.04%) | 0.39 ms (0.98%) | 11.79 ms (29.71%) | 24.90 ms (62.73%) | 0.17 ms (0.42%) |
| 1024/512 | 44.46 ms | 4.36 ms (9.80%) | 0.44 ms (0.99%) | 0.40 ms (0.90%) | 11.82 ms (26.59%) | 27.28 ms (61.36%) | 0.17 ms (0.38%) |
| 2048/512 | 49.84 ms | 5.92 ms (11.87%) | 0.53 ms (1.07%) | 0.41 ms (0.83%) | 11.88 ms (23.84%) | 29.24 ms (58.67%) | 0.17 ms (0.34%) |

补充数据文件：

- `rr4_breakdown/rr4_breakdown_summary.csv`
- `rr4_breakdown/rr4_breakdown_summary_median.csv`
- `rr4_breakdown/rr4_il*_ol*_per_request.csv`

---

## 8. 结论

1. **TTFT 是端到端指标**，包含 SSE 返回和客户端解析，口径正确。  
2. “HiSim 未建模 1 和 6”中，**6（SSE 发送）影响极小**，**1（HTTP+tokenize）有贡献但不足以单独解释全部差值**。  
3. 大差值主要来自高负载下真实系统中的排队、调度与服务链路开销；这部分在 HiSim 中被弱化或简化。  
4. 评估建议：  
   - 用 HiSim 评估 kernel 级趋势（prefill/decode 计算趋势）；  
   - 用实测评估端到端 SLA（TTFT、P99、队列效应）。
