#!/usr/bin/env python3
"""VRAM feasibility calculator (ESTIMATES). Replace every *_est with values read from
the llama-server load log (model buffer / KV / RS / compute buffer lines) and the
Windows DXGI budget before trusting any row. Does NOT prove usable context."""
import json
GiB = 2**30
TOTAL = 24.0                      # Intel spec 24 GB GDDR6; usable dedicated is lower (measure)
W_MAIN_GPU = (15.27, 16.2445)     # low: token_embd kept on CPU (llama.cpp default, Q4_K/Q6_K est) ; high: whole file
W_DRAFT = 1.0645
RS_EST = 8 * 48 * (48*128*128*4 + 3*10240*4) / GiB   # 48 GDN layers, f32, (1+n_rs_seq=7) rows -> ~1.17 GiB
COMPUTE_EST = (0.8, 1.6)          # main+draft compute/prealloc buffers at ub256 (est.)
DISPLAY = (0.75, 1.5, 3.0)        # DWM/display on the only GPU; pack's repo log claims 2.6-3.3 GB (unverified)
RESERVE = 1.5                     # governor headroom (pack's own guardrail: >=1.5 GiB free)
KV_F16_KIB = 64.5                 # user estimate; public config gives exactly 64.0 (16 attn layers x 4 KV x 256 x 2 x 2B)
KV_Q8_KIB = KV_F16_KIB * 34/64    # q8_0 = 34 bytes per 32 elems vs 64 for f16
DRAFT_KV_Q8_KIB = (2.1, 10.6)     # 1 full-attn layer only (SWA) .. 5 layers full ctx, 8 KV x 128, q8_0 (est.)

def row(ctx, kv_kib, scen):
    w, comp, disp = scen
    kv = ctx*kv_kib*1024/GiB
    dkv = ctx*DRAFT_KV_Q8_KIB[1]*1024/GiB if scen is WORST else ctx*DRAFT_KV_Q8_KIB[0]*1024/GiB + 4*2048*2.1*1024/GiB
    used = w + W_DRAFT + RS_EST + comp + disp + kv + dkv
    return dict(ctx=ctx, main_kv_GiB=round(kv,3), draft_kv_GiB=round(dkv,3), used_GiB=round(used,2),
                margin_vs_reserve_GiB=round(TOTAL-used-RESERVE,2), fits=TOTAL-used-RESERVE >= 0)

BEST = (W_MAIN_GPU[0], COMPUTE_EST[0], DISPLAY[0])
MID = (W_MAIN_GPU[0], COMPUTE_EST[1], DISPLAY[1])
WORST = (W_MAIN_GPU[1], COMPUTE_EST[1], DISPLAY[2])

if __name__ == "__main__":
    out = {"assumptions": dict(TOTAL=TOTAL, W_MAIN_GPU=W_MAIN_GPU, W_DRAFT=W_DRAFT, RS_EST_GiB=round(RS_EST,3),
            COMPUTE_EST=COMPUTE_EST, DISPLAY=DISPLAY, RESERVE=RESERVE, KV_F16_KIB=KV_F16_KIB, KV_Q8_KIB=round(KV_Q8_KIB,2)),
           "check_32K_to_96K_delta_f16_GiB": round((98304-32768)*KV_F16_KIB*1024/GiB, 3)}
    for name, scen in (("best", BEST), ("mid", MID), ("worst", WORST)):
        for kvname, kib in (("f16", KV_F16_KIB), ("q8_0", KV_Q8_KIB)):
            out[f"{name}/{kvname}"] = [row(c, kib, scen) for c in (32768, 49152, 57344, 65536, 98304)]
    print(json.dumps(out, indent=1))
