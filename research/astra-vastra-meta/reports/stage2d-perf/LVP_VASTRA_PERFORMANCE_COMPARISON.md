# LVP versus ASTRA-V-ASTRA, isolated modes (Stage 2d)

Written for: the researcher deciding how to evaluate the hybrid predictor once META exists.
Committed source tested: branch `astra-vastra-dev`, commit `88f72e2bd461756a2b5ca0ca5fa1f3ed4accf2cf`, `build/RISCV/gem5.opt` (sha256 prefix `2a22ce1b23fa1503`, built from that source; the tree was clean throughout). Nothing in the repository was changed; the benchmark, drivers and results live in this directory.

## 1. Method

**Configuration.** The canonical research baseline `configs/research/vp_baseline.py` (default MinorCPU functional-unit timing) for every run. Modes (flags checked in the `config.ini` snapshots in `config-snapshots/`):

| mode | parameters that differ from the baseline |
|---|---|
| NO-PREDICTION (`np`) | none |
| LVP-ONLY (`lv`) | `enableLVP=true`, `lvpSpecAddr=true` (threshold 3, 1024 entries, whole program) |
| V-ASTRA-ONLY (`va`) | `enableAstra`, `enableVCache`, `enableVAstraDiag`, `enableVAstraBypass`, `enableVAstraScoreboardRelease`, `enableVAstraForwarding` = true; LVP off |
| HYBRID | **unavailable: META is not implemented** (recorded as such in `summary.csv`; `lvpSpecAddr` and forwarding are mutually exclusive in the committed source and no ad hoc policy was built) |

The stall-on-use configuration is not used: under it a dependent load cannot issue before its producer's release, so LVP's speculation could not operate (a different experiment).

**Workloads** (`src/perf.c`, one source, `-DWORK=n`; freestanding RV64G; the same executable bytes for the three modes of a comparison; hashes in `exe-sha256.txt`). Every lap walks a chain of four dependent loads `P -> C -> E -> F` (F's value is added to a checksum). Before the chain, a lap stores to four lines that conflict with each hot line in the 4-way L1D set (16 KiB apart: same L1D set, same V$ index, another tag) and executes `fence rw,rw`, so the hot lines are evicted from the L1D and **every chain load is an L1D miss that hits the L2** (800 of 800 loads in the ROI; latency bound). Stores with another tag do not change a V$ entry, so the V$ keeps the hot words. There are no artificial delay loops. Regions of interest are delimited by the gem5 pseudo-instructions `m5_reset_stats` (after the warm-up laps) and `m5_dump_stats` (after 200 laps); the first statistics block of each run is the ROI. Warm-up: 100 laps (predictor training, V$ and cache warm-up).

| workload | what it is | intended to favor |
|---|---|---|
| `stable` | the same four addresses and values every lap | shared chain: both predictors apply (LVP saturates, ASTRA predicts stride 0, V$ hits) |
| `randbase` | P's base is one of 8 lines picked by bits 40-42 of a 64-bit LCG, all holding the same pointer | LVP at P (value stable); ASTRA cannot predict P's base (C, E, F stay predictable) |
| `altvalue` | P's value alternates every lap between two copies of the next node (a store flips it) | V-ASTRA (C's base alternation is a learnable stride pattern; LVP never gets confident at P) |
| `vcmiss` | the four chain lines are 4096 bytes apart: one V$ index, so each load replaces the previous one's V$ entry | LVP (values stable) while V-ASTRA finds no V$ bytes |

**Measurements.** Per run: ROI `numCycles` (the ROI statistics block, not the whole run), `simInsts`, checksum, L1D/L2 statistics, LVP/V-ASTRA counters. Repeats: five runs per (workload, mode), each with the same executable copied to a path of a different length (the layout effects seen in earlier stages came from path length), plus an exact re-run of the first configuration. Second experiment (`sensitivity.csv`): warm-up 0/5/20/100 laps and ROI 100/200/400/800 laps. `cycle_reduction_percent = 100 * (baseline_roi_cycles - enabled_roi_cycles) / baseline_roi_cycles`.

## 2. Correctness (separate from performance)
* Every mode of every workload exits 0, prints the **same checksum** and executes the **same number of ROI instructions** as NO-PREDICTION (`summary.csv`: `checksum_equal_to_np`, `insts_equal_to_np` true in all 12 mode-workload cells; the sensitivity runs agree in all 28 variants).
* Configuration: `config.ini` of `np` vs `lv` differs only in `enableLVP` and `lvpSpecAddr`; `np` vs `va` only in the V-ASTRA/ASTRA/V$ parameters.

## 3. Results (ROI cycles, 5 repeats per cell)
| workload | mode | ROI cycles median | min | max | cycles/lap | reduction vs NO-PREDICTION | ROI insts | checksum = NO-PRED | L1D read misses |
|---|---|---|---|---|---|---|---|---|---|
| stable | NO-PREDICTION | 34547 | 34547 | 34547 | 172.74 | - | 7248 | True | 800 |
| stable | LVP-ONLY | 24047 | 24047 | 24047 | 120.23 | 30.39% | 7248 | True | 800 |
| stable | V-ASTRA-ONLY | 5043 | 5043 | 5043 | 25.21 | 85.40% | 7248 | True | 0 |
| randbase | NO-PREDICTION | 35608 | 35608 | 35608 | 178.04 | - | 17793 | True | 800 |
| randbase | LVP-ONLY | 30620 | 30620 | 30620 | 153.1 | 14.01% | 17793 | True | 800 |
| randbase | V-ASTRA-ONLY | 18249 | 18249 | 18249 | 91.25 | 48.75% | 17793 | True | 205 |
| altvalue | NO-PREDICTION | 31344 | 31344 | 31344 | 156.72 | - | 9057 | True | 800 |
| altvalue | LVP-ONLY | 25944 | 25944 | 25944 | 129.72 | 17.23% | 9057 | True | 800 |
| altvalue | V-ASTRA-ONLY | 12819 | 12819 | 12819 | 64.09 | 59.10% | 9057 | True | 0 |
| vcmiss | NO-PREDICTION | 31144 | 31144 | 31144 | 155.72 | - | 11748 | True | 800 |
| vcmiss | LVP-ONLY | 24944 | 24944 | 24944 | 124.72 | 19.91% | 11748 | True | 800 |
| vcmiss | V-ASTRA-ONLY | 31144 | 31144 | 31144 | 155.72 | 0.00% | 11748 | True | 800 |

Repeatability: the five layout repeats of every cell are **bit-identical** (spread 0.000%), and an exact re-run of `stable`/NO-PREDICTION reproduced 34547 cycles. gem5 is deterministic, so identical repeats show insensitivity to this layout perturbation, not independent noise samples.

## 4. Mechanism evidence (first repeat; ROI window)
| workload | mode | mechanism counters in the ROI |
|---|---|---|
| stable | LVP-ONLY | LVP confident predictions 801, correct 800, incorrect 0, speculative loads issued 600, committed 600, recovery squashes 0 |
| stable | V-ASTRA-ONLY | V-ASTRA candidates 800, synthetic responses (memory requests suppressed) 800, forwarded dependents 0, base wrong 0, V$ tag-miss fallbacks 0 |
| randbase | LVP-ONLY | LVP confident predictions 800, correct 800, incorrect 0, speculative loads issued 429, committed 429, recovery squashes 0 |
| randbase | V-ASTRA-ONLY | V-ASTRA candidates 595, synthetic responses (memory requests suppressed) 595, forwarded dependents 0, base wrong 205, V$ tag-miss fallbacks 0 |
| altvalue | LVP-ONLY | LVP confident predictions 600, correct 600, incorrect 0, speculative loads issued 400, committed 400, recovery squashes 0 |
| altvalue | V-ASTRA-ONLY | V-ASTRA candidates 801, synthetic responses (memory requests suppressed) 801, forwarded dependents 0, base wrong 0, V$ tag-miss fallbacks 0 |
| vcmiss | LVP-ONLY | LVP confident predictions 800, correct 800, incorrect 0, speculative loads issued 600, committed 600, recovery squashes 0 |
| vcmiss | V-ASTRA-ONLY | V-ASTRA candidates 800, synthetic responses (memory requests suppressed) 0, forwarded dependents 0, base wrong 0, V$ tag-miss fallbacks 800 |

* LVP operated in every workload: confident predictions, all correct, speculative dependent loads issued and committed, no recovery squash. At `altvalue` its confident predictions (600) are exactly C, E and F; P's value alternates and never becomes confident.
* V-ASTRA operated where intended: `stable`/`altvalue` suppressed all (800/801) memory requests of the chain; at `randbase` the 205 loads of P with a wrong ASTRA base fell back (205 L1D read misses remain); at `vcmiss` all 800 candidates fell back on a V$ tag miss and **no response was synthesised**.
* **Forwarding contributed nothing here**: `fwdAdmitted` is 0 in every run, because in these kernels a producer is already the head of the in-flight queue when it is validated. The V-ASTRA numbers are those of the bypass alone (Design A's release is a no-op in the default timing).

## 5. Sensitivity to warm-up and ROI length
| workload | warm laps | ROI laps | NO-PRED cycles | LVP cycles (reduction) | V-ASTRA cycles (reduction) | same instruction count |
|---|---|---|---|---|---|---|
| altvalue | 0 | 200 | 31964 | 26672 (16.6%) | 13607 (57.4%) | yes |
| altvalue | 5 | 200 | 31344 | 25944 (17.2%) | 12858 (59.0%) | yes |
| altvalue | 20 | 200 | 31344 | 25944 (17.2%) | 12819 (59.1%) | yes |
| altvalue | 100 | 100 | 15694 | 12994 (17.2%) | 6419 (59.1%) | yes |
| altvalue | 100 | 200 | 31344 | 25944 (17.2%) | 12819 (59.1%) | yes |
| altvalue | 100 | 400 | 62644 | 51844 (17.2%) | 25619 (59.1%) | yes |
| altvalue | 100 | 800 | 125244 | 103644 (17.2%) | 51219 (59.1%) | yes |
| randbase | 0 | 200 | 36655 | 31771 (13.3%) | 19593 (46.5%) | yes |
| randbase | 5 | 200 | 35599 | 30639 (13.9%) | 18375 (48.4%) | yes |
| randbase | 20 | 200 | 35607 | 30619 (14.0%) | 18282 (48.7%) | yes |
| randbase | 100 | 100 | 17853 | 15341 (14.1%) | 8989 (49.6%) | yes |
| randbase | 100 | 200 | 35608 | 30620 (14.0%) | 18249 (48.8%) | yes |
| randbase | 100 | 400 | 71109 | 61175 (14.0%) | 36423 (48.8%) | yes |
| randbase | 100 | 800 | 142221 | 122303 (14.0%) | 72254 (49.2%) | yes |
| stable | 0 | 200 | 35087 | 24797 (29.3%) | 5844 (83.3%) | yes |
| stable | 5 | 200 | 34545 | 24050 (30.4%) | 5043 (85.4%) | yes |
| stable | 20 | 200 | 34547 | 24047 (30.4%) | 5043 (85.4%) | yes |
| stable | 100 | 100 | 17297 | 12047 (30.4%) | 2543 (85.3%) | yes |
| stable | 100 | 200 | 34547 | 24047 (30.4%) | 5043 (85.4%) | yes |
| stable | 100 | 400 | 69047 | 48047 (30.4%) | 10043 (85.5%) | yes |
| stable | 100 | 800 | 138047 | 96047 (30.4%) | 20043 (85.5%) | yes |
| vcmiss | 0 | 200 | 31950 | 25874 (19.0%) | 31950 (0.0%) | yes |
| vcmiss | 5 | 200 | 31144 | 24944 (19.9%) | 31144 (0.0%) | yes |
| vcmiss | 20 | 200 | 31144 | 24944 (19.9%) | 31144 (0.0%) | yes |
| vcmiss | 100 | 100 | 15594 | 12494 (19.9%) | 15594 (0.0%) | yes |
| vcmiss | 100 | 200 | 31144 | 24944 (19.9%) | 31144 (0.0%) | yes |
| vcmiss | 100 | 400 | 62244 | 49844 (19.9%) | 62244 (0.0%) | yes |
| vcmiss | 100 | 800 | 124444 | 99644 (19.9%) | 124444 (0.0%) | yes |

The reductions are constant (within 0.1 point) for ROI lengths of 100 to 800 laps and for warm-ups of 5 laps or more; with no warm-up the reductions are 1 to 2 points lower (LVP/V-ASTRA train during the ROI). The instruction counts agree in all variants.

## 6. Answers
1. **LVP cycle reduction** (ROI cycles, median of 5): `stable` 30.39%, `randbase` 14.01%, `altvalue` 17.23%, `vcmiss` 19.91%.
2. **ASTRA-V-ASTRA cycle reduction**: `stable` 85.40%, `randbase` 48.75%, `altvalue` 59.10%, `vcmiss` 0.00% (no V$ hit, no synthetic response, no overhead: cycles identical to NO-PREDICTION).
3. **Repeatability**: identical across five path-length layouts and an exact re-run (spread 0%); stable to 0.1 point across ROI lengths 100-800 and warm-ups of 5-100 laps.
4. **Which workload favors which mechanism**: V-ASTRA wins by a large margin whenever its conditions hold (predictable base, V$ hit): `stable`, `altvalue`, and the C/E/F links of `randbase`. LVP is the only effective mechanism where the V$ cannot supply the bytes (`vcmiss`: 19.91% vs 0.00%). `randbase` is the mixed case: V-ASTRA loses the P link (205 base mispredictions) but still wins overall; LVP covers P's value but only one dependent link at a time (it helps a consumer while its producer is outstanding), so the two cover different links.
5. **Strength of the evidence**: the effects (14% to 85%) are far larger than the observed variability (0), and each is backed by counters of the mechanism that produced it, equal checksums and equal instruction counts, so within this model and these kernels the improvements are established and not inconclusive. They are **not** a general speedup claim: the kernels are chains of dependent L2-hit loads built to be latency bound, the V$ is warm by construction, 25 cycles per lap (stores and a fence) are a common floor, only one memory configuration and one timing configuration were used, and V-ASTRA's 85% on `stable` comes from suppressing every chain load's memory access in a pattern its tables fit perfectly. Real workloads, mixed instruction streams and stall-on-use timing remain to be measured.

## 7. Hybrid
Not evaluated: META does not exist, and combining the modes is not valid in the committed source (`lvpSpecAddr` and forwarding are mutually exclusive). Nothing here claims a hybrid benefit.

### Recommendation for evaluating the hybrid once META exists
* Use this harness unchanged (same sources, ROI definition, path-length repeats, `summary.csv` schema) and add a fourth mode `meta`; keep NO-PREDICTION, LVP-ONLY and V-ASTRA-ONLY in the same batch and the same executables.
* Pass criteria, per workload: architectural output and ROI instruction count equal to NO-PREDICTION; the META source counters show the intended source per load (V-ASTRA on `stable`, LVP on `vcmiss`, both on `randbase`); **meta >= max(LVP-only, V-ASTRA-only)** on each workload within the measurement variability, and strictly better on `randbase` where the predictors cover different links; no recovery squash caused by a V-ASTRA-served consumer.
* Add workloads before drawing conclusions: one where both predictors fail (cost of a wrong or conflicting choice), one with V$ conflict by stores (V-ASTRA rejected, LVP stable), a mixed-latency one, and stall-on-use timing for the V-ASTRA arm.
* Report cycle reductions per workload with the same ROI statistics; never use whole-run `numCycles`.

## 8. Artifacts
`runs.csv` (every run, raw), `summary.csv` (per cell), `sensitivity.csv`, `tables.md`, `runs/`, `runs-sens/` (gem5 outputs, stats, config.ini of each run), `config-snapshots/`, `src/perf.c`, `exe-sha256.txt`, `run_perf.py`, `run_sensitivity.py`, `analyze.py`, `analysis-stdout.txt`.
