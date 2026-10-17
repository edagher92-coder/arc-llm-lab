#!/usr/bin/env python3
"""Reproduces the DFlash timing arithmetic in dflash_timing_analysis.md.

Inputs are ONLY the numbers the user reported for the latest traced run plus
public specs. No new measurements are introduced. Every derived value is an
arithmetic consequence of those inputs; anything that would need a split of the
uninstrumented remainder is printed as UNKNOWN.
"""
from __future__ import annotations
import json

# ---- user-reported traced run (authoritative per brief) ----
RUN = dict(
    output_tokens=2304,
    native_gen_s=60.898,
    wall_s=61.764,
    first_content_s=0.864,
    rounds=458,
    drafted=2576,
    accepted=1789,
    draft_timer_s=9.535,  # excludes feature readback/injection path
    draft_n_max=7,
)

# ---- public specs / configs ----
B60_BW_GBPS = 456.0          # Intel ARK, Arc Pro B60 (decimal GB/s)
MAIN_FILE_BYTES = 17_442_400_352
# Qwen3.5-27B public config (Qwen3.8 assumed same shape - UNVERIFIED)
VOCAB, HIDDEN = 248_320, 5_120


def derive(r=RUN):
    d = {}
    d["tps_native"] = r["output_tokens"] / r["native_gen_s"]
    d["tokens_per_round"] = r["output_tokens"] / r["rounds"]
    d["drafted_per_round"] = r["drafted"] / r["rounds"]
    d["accepted_per_round"] = r["accepted"] / r["rounds"]
    d["acceptance_rate"] = r["accepted"] / r["drafted"]
    # each verification round emits accepted + 1 (bonus/correction) tokens
    d["tokens_explained_by_rounds"] = r["accepted"] + r["rounds"]
    d["tokens_unexplained"] = r["output_tokens"] - d["tokens_explained_by_rounds"]
    d["ms_per_round"] = 1000 * r["native_gen_s"] / r["rounds"]
    d["draft_ms_per_round"] = 1000 * r["draft_timer_s"] / r["rounds"]
    d["remainder_ms_per_round"] = d["ms_per_round"] - d["draft_ms_per_round"]
    d["draft_share"] = r["draft_timer_s"] / r["native_gen_s"]
    d["wall_minus_native_s"] = r["wall_s"] - r["native_gen_s"]

    # bandwidth floor of ONE target forward (all VRAM-resident weights read once)
    emb_q4k = VOCAB * HIDDEN * 4.5 / 8      # token_embd if Q4_K (4.5 bpw)
    emb_q6k = VOCAB * HIDDEN * 6.5625 / 8   # token_embd if Q6_K
    for label, emb in (("emb_on_gpu", 0.0), ("emb_cpu_q4k", emb_q4k), ("emb_cpu_q6k", emb_q6k)):
        bytes_read = MAIN_FILE_BYTES - emb
        t_ms = 1000 * bytes_read / (B60_BW_GBPS * 1e9)
        d[f"fwd_floor_ms[{label}]"] = t_ms
        d[f"nonspec_tps_ceiling[{label}]"] = 1000 / t_ms

    # targets: what must change to reach 40 / 50 t/s on this same contract
    for tgt in (40, 45, 50):
        d[f"round_ms_needed_at_current_tpr[{tgt}]"] = 1000 * d["tokens_per_round"] / tgt
        d[f"tpr_needed_at_current_round_ms[{tgt}]"] = tgt * d["ms_per_round"] / 1000
    # optimistic bound: verify at bandwidth floor + measured draft time, nothing else
    floor = d["fwd_floor_ms[emb_on_gpu]"]
    d["ideal_round_ms(verify_floor+draft)"] = floor + d["draft_ms_per_round"]
    d["ideal_tps_at_current_tpr"] = 1000 * d["tokens_per_round"] / d["ideal_round_ms(verify_floor+draft)"]
    d["remainder_minus_verify_floor_ms"] = d["remainder_ms_per_round"] - floor
    d["UNKNOWN_split"] = ("target verify GPU time, feature readback (GPU->host), CPU concat, "
                          "inject upload + inject decode, synchronize waits, lattice readback, "
                          "CPU selector argmax, sampling/accept, server loop overhead")
    return d


def sustained_runs():
    runs = {
        "original MAX14/draft7": [38.79, 42.71, 43.91],
        "MMVQ override removed": [36.01, 37.16, 36.92],
        "8 workers (BALANCED, not isolated)": [38.36, 37.28, 42.81],
        "MAX14/draft5": [37.68, 40.76, 41.24],
    }
    out = {}
    for k, v in runs.items():
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5
        out[k] = dict(mean=round(m, 3), sd=round(sd, 3), min=min(v), max=max(v), all_ge_40=all(x >= 40 for x in v))
    return out


if __name__ == "__main__":
    d = derive()
    print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}, indent=2))
    print(json.dumps(sustained_runs(), indent=2))


def feature_traffic(n_extract_options=(5, 8), pcie_gbps_practical=(10.0, 14.0), prompt_tokens=(2048, 8192, 32768)):
    """Host traffic implied by common/speculative.cpp DFlash process():
    llama_get_embeddings_layer_inp() -> host copy of n_extract x n_embd_tgt f32 per token,
    CPU memcpy concat, then upload again as batch_inject embeddings.
    n_extract for the Qwen3.8 DFlash2 draft is UNVERIFIED (z-lab Qwen3.5-27B-DFlash: 8, Qwen3.6-27B-DFlash: 5)."""
    out = {}
    tpr_batch = RUN["drafted"] / RUN["rounds"] + 1  # tokens in each verify batch
    for n in n_extract_options:
        per_tok = n * HIDDEN * 4
        out[f"n_extract={n}"] = {
            "bytes_per_token_KiB": per_tok / 1024,
            "per_round_MiB_one_direction": per_tok * tpr_batch / 2**20,
            "per_round_ms_transfer_at_practical_pcie": [round(1000 * per_tok * tpr_batch / (g * 1e9), 3) for g in pcie_gbps_practical],
            "prefill_GiB_one_direction": {p: round(per_tok * p / 2**30, 3) for p in prompt_tokens},
            "prefill_s_one_direction_at_practical_pcie": {p: [round(per_tok * p / (g * 1e9), 3) for g in pcie_gbps_practical] for p in prompt_tokens},
        }
    return out


if __name__ == "__main__":
    print(json.dumps({"native_tps_if_first_token_excluded": round((RUN['output_tokens'] - 1) / RUN['native_gen_s'], 4)}, indent=2))
    print(json.dumps(feature_traffic(), indent=2))
