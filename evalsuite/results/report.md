# arc-llm-lab: agent reliability report

## Runs

| Run | Agent | Ctx cap | Pass | Completed/min | Median pass time | p90 | Min free VRAM | Reloads | Ctx overflows | Gen tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| claude-32k | claude | 32k | 97/100 (97%) | **1.53** | 24.1s | 48.9s | 1.19 GB | 0 | 0 | 39.0 |
| claude-32k-v2 | claude | 32k | 93/100 (93%) | **1.13** | 22.5s | 44.3s | 1.4 GB | 3 | 1 | 39.1 |
| codex-32k | codex | 32k | 94/100 (94%) | **0.62** | 69.0s | 121.5s | 1.68 GB | 0 | 0 | 31.1 |

## Categories (all runs)

| Category | Attempts | Pass rate | Median time | Tier |
|---|---|---|---|---|
| coding | 60 | 100% | 54.8s | **AUTONOMOUS** |
| debugging | 60 | 98% | 20.4s | **AUTONOMOUS** |
| tool | 45 | 93% | 18.9s | **AUTONOMOUS** |
| fileops | 45 | 91% | 39.7s | **AUTONOMOUS** |
| longctx | 30 | 83% | 49.0s | **SUPERVISED** |
| business | 30 | 97% | 46.8s | **AUTONOMOUS** |
| recovery | 30 | 93% | 27.1s | **AUTONOMOUS** |

## Failure reasons

- claude-32k: answer_not_saved 2, wrong_result 1; plus 1 pass(es) only after a timeout kill (counted as passed, excluded from median/p90)
- claude-32k-v2: answer_not_saved 2, wrong_result 2, timeout 1, context_overflow 1, max_turns 1; plus 2 pass(es) only after a timeout kill (counted as passed, excluded from median/p90)
- codex-32k: api_error 4, timeout 2; plus 1 pass(es) only after a timeout kill (counted as passed, excluded from median/p90)

## Tasks — ESCALATE


## Tasks — SUPERVISED

- `debug-bsearch` (debugging): claude-32k-v2=PASS, claude-32k=PASS, codex-32k=timeout  — hidden tests timed out
- `tool-git-branch` (tool): claude-32k-v2=PASS, claude-32k=PASS, codex-32k=timeout  — branch fix/readme-typo missing or README absent
- `tool-unique-suburbs` (tool): claude-32k-v2=PASS, claude-32k=PASS, codex-32k=api_error  — answer.txt='400' expected=11
- `tool-json-sum` (tool): claude-32k-v2=max_turns, claude-32k=PASS, codex-32k=PASS  — answer.txt='' expected=29580.21
- `files-license-header` (fileops): claude-32k-v2=wrong_result, claude-32k=PASS, codex-32k=PASS  — src/b.py wrong: '# Copyright (c) 2026 FrostLine Hire\nimport os\nprint(os.name)\n'
- `files-extract-emails` (fileops): claude-32k-v2=PASS, claude-32k=PASS, codex-32k=api_error  — emails.txt=['\ufeffaccounts@chillco.com', 'ana.rossi@example.org', 'bob.smith@mailbox.example', 'jon@frostline.com.au', 'events@school.nsw.edu.au', 'j-li@outloo
- `files-tabs-to-spaces` (fileops): claude-32k-v2=wrong_result, claude-32k=wrong_result, codex-32k=PASS  — app/util.py not as expected; app/util.py not as expected
- `long-needle-log` (longctx): claude-32k-v2=answer_not_saved, claude-32k=answer_not_saved, codex-32k=PASS  — answer.txt='' expected='req-eafb1e04'; answer.txt='' expected='req-eafb1e04'
- `long-contract-clause` (longctx): claude-32k-v2=context_overflow, claude-32k=answer_not_saved, codex-32k=PASS  — answer.txt='' expected=14; answer.txt='' expected=14
- `long-count-decorated` (longctx): claude-32k-v2=answer_not_saved, claude-32k=PASS, codex-32k=PASS  — answer.txt='' expected=29
- `biz-price-update` (business): claude-32k-v2=PASS, claude-32k=PASS, codex-32k=api_error  — row ['P000', 'syrup', '3.20'] expected price 3.25
- `recover-wrong-path` (recovery): claude-32k-v2=timeout, claude-32k=PASS, codex-32k=PASS  — answer.txt='' expected=2872.60
- `recover-circular-import` (recovery): claude-32k-v2=PASS, claude-32k=PASS, codex-32k=api_error  — answer.txt='' expected='TOTAL 20 (helper check 2)'

## Sustained sessions (48K-64K)

### sustained-claude-48k-fixed — 10/10 steps passed (cumulative tests), 10/10 own-step tests passed, 32.8 min, peak prompt 36563 tokens, compactions 5, overflow errors 0, reloads 0, memory probe PASS

| Step | Rules | Pass (cumulative) | This step's own test | Time | Peak prompt | Server ctx | Compactions | Failure |
|---|---|---|---|---|---|---|---|---|
| 1 | v1 | PASS | PASS | 103.8s | 26488 | [65536] | 0 |  |
| 2 | v1 | PASS | PASS | 224.4s | 31065 | [65536] | 1 |  |
| 3 | v1 | PASS | PASS | 338.7s | 26596 | [65536] | 2 |  |
| 4 | v1 | PASS | PASS | 277.0s | 34451 | [65536] | 3 |  |
| 5 | v1 | PASS | PASS | 54.2s | 16890 | [65536] | 3 |  |
| 6 | v1 | PASS | PASS | 81.7s | 20993 | [65536] | 3 |  |
| 7 | v1 | PASS | PASS | 101.8s | 24655 | [65536] | 3 |  |
| 8 | v1 | PASS | PASS | 67.0s | 27490 | [65536] | 3 |  |
| 9 | v2 | PASS | PASS | 708.1s | 36563 | [65536] | 5 |  |
| 10 | v2 | PASS | PASS | 13.8s | 18674 | [65536] | 5 |  |

### sustained-claude-48k-v1spec — 5/10 steps passed (cumulative tests), 62.8 min, peak prompt 35419 tokens, compactions 6, overflow errors 0, reloads 0, memory probe PASS

| Step | Rules | Pass (cumulative) | This step's own test | Time | Peak prompt | Server ctx | Compactions | Failure |
|---|---|---|---|---|---|---|---|---|
| 1 | v1 | PASS | - | 94.8s | 19935 | [65536] | 0 |  |
| 2 | v1 | PASS | - | 105.4s | 23637 | [65536] | 0 |  |
| 3 | v1 | PASS | - | 285.9s | 34749 | [65536] | 1 |  |
| 4 | v1 | PASS | - | 345.8s | 26049 | [65536] | 2 |  |
| 5 | v1 | FAIL | - | 268.2s | 34537 | [65536] | 3 | wrong_result |
| 6 | v1 | FAIL | - | 287.9s | 25276 | [65536] | 4 | wrong_result |
| 7 | v1 | FAIL | - | 58.4s | 27480 | [65536] | 4 | wrong_result |
| 8 | v1 | FAIL | - | 264.2s | 35419 | [65536] | 5 | wrong_result |
| 9 | v2 | FAIL | - | 1834.7s | 22115 | [65536] | 6 | timeout |
| 10 | v2 | PASS | - | 220.9s | 22115 | [65536] | 6 |  |

### sustained-claude-64k-fixed — 9/10 steps passed (cumulative tests), 9/10 own-step tests passed, 22.2 min, peak prompt 44443 tokens, compactions 2, overflow errors 0, reloads 0, memory probe FAIL

| Step | Rules | Pass (cumulative) | This step's own test | Time | Peak prompt | Server ctx | Compactions | Failure |
|---|---|---|---|---|---|---|---|---|
| 1 | v1 | PASS | PASS | 111.4s | 28248 | [65536] | 0 |  |
| 2 | v1 | PASS | PASS | 118.4s | 33498 | [65536] | 0 |  |
| 3 | v1 | PASS | PASS | 58.3s | 35802 | [65536] | 0 |  |
| 4 | v1 | PASS | PASS | 232.9s | 41950 | [65536] | 1 |  |
| 5 | v1 | PASS | PASS | 50.4s | 17174 | [65536] | 1 |  |
| 6 | v1 | PASS | PASS | 82.2s | 20794 | [65536] | 1 |  |
| 7 | v1 | PASS | PASS | 90.9s | 24789 | [65536] | 1 |  |
| 8 | v1 | PASS | PASS | 53.0s | 27316 | [65536] | 1 |  |
| 9 | v2 | PASS | PASS | 517.2s | 44443 | [65536] | 2 |  |
| 10 | v2 | FAIL | FAIL | 19.7s | 28662 | [65536] | 2 | wrong_result |

### sustained-claude-64k-v1spec — 4/10 steps passed (cumulative tests), 18.9 min, peak prompt 43119 tokens, compactions 1, overflow errors 0, reloads 0, memory probe FAIL

| Step | Rules | Pass (cumulative) | This step's own test | Time | Peak prompt | Server ctx | Compactions | Failure |
|---|---|---|---|---|---|---|---|---|
| 1 | v1 | PASS | - | 180.9s | 27354 | [65536] | 0 |  |
| 2 | v1 | PASS | - | 154.9s | 32671 | [65536] | 0 |  |
| 3 | v1 | PASS | - | 81.9s | 35466 | [65536] | 0 |  |
| 4 | v1 | PASS | - | 310.0s | 43119 | [65536] | 1 |  |
| 5 | v1 | FAIL | - | 50.8s | 17096 | [65536] | 1 | wrong_result |
| 6 | v1 | FAIL | - | 57.0s | 19245 | [65536] | 1 | wrong_result |
| 7 | v1 | FAIL | - | 58.8s | 21437 | [65536] | 1 | wrong_result |
| 8 | v1 | FAIL | - | 42.5s | 23162 | [65536] | 1 | api_error |
| 9 | v2 | FAIL | - | 169.9s | 33077 | [65536] | 1 | wrong_result |
| 10 | v2 | FAIL | - | 28.8s | 33763 | [65536] | 1 | wrong_result |

### sustained-codex-48k — 9/10 steps passed (cumulative tests), 9/10 own-step tests passed, 40.0 min, peak prompt 28754 tokens, compactions 2, overflow errors 0, reloads 1, memory probe FAIL

| Step | Rules | Pass (cumulative) | This step's own test | Time | Peak prompt | Server ctx | Compactions | Failure |
|---|---|---|---|---|---|---|---|---|
| 1 | v1 | PASS | PASS | 120.1s | 21277 | [65536] | 0 |  |
| 2 | v1 | PASS | PASS | 62.0s | 23030 | [65536] | 0 |  |
| 3 | v1 | PASS | PASS | 63.1s | 26988 | [65536] | 0 |  |
| 4 | v1 | PASS | PASS | 518.9s | 27454 | [65536] | 2 |  |
| 5 | v1 | PASS | PASS | 520.8s | 26909 | [65536] | 1 |  |
| 6 | v1 | PASS | PASS | 205.0s | 26140 | [65536] | 0 |  |
| 7 | v1 | PASS | PASS | 259.1s | 27381 | [65536] | 1 |  |
| 8 | v1 | PASS | PASS | 37.0s | 21768 | [65536] | 0 |  |
| 9 | v2 | PASS | PASS | 458.4s | 28754 | [65536] | 1 |  |
| 10 | v2 | FAIL | FAIL | 155.2s | 24962 | [65536] | 0 | api_error |

### sustained-codex-64k — 9/10 steps passed (cumulative tests), 9/10 own-step tests passed, 32.5 min, peak prompt 27858 tokens, compactions 1, overflow errors 0, reloads 0, memory probe FAIL

| Step | Rules | Pass (cumulative) | This step's own test | Time | Peak prompt | Server ctx | Compactions | Failure |
|---|---|---|---|---|---|---|---|---|
| 1 | v1 | PASS | PASS | 99.9s | 24962 | [65536] | 0 |  |
| 2 | v1 | PASS | PASS | 127.7s | 25525 | [65536] | 0 |  |
| 3 | v1 | PASS | PASS | 308.2s | 27187 | [65536] | 1 |  |
| 4 | v1 | PASS | PASS | 81.1s | 25657 | [65536] | 0 |  |
| 5 | v1 | PASS | PASS | 194.6s | 26563 | [65536] | 1 |  |
| 6 | v1 | PASS | PASS | 437.9s | 27178 | [65536] | 1 |  |
| 7 | v1 | PASS | PASS | 238.2s | 26730 | [65536] | 1 |  |
| 8 | v1 | PASS | PASS | 28.5s | 21487 | [65536] | 0 |  |
| 9 | v2 | PASS | PASS | 396.9s | 27858 | [65536] | 1 |  |
| 10 | v2 | FAIL | FAIL | 37.4s | 23830 | [65536] | 0 | api_error |
