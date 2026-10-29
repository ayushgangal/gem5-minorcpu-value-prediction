# ASTRA / V-ASTRA / LVP / META: results, reports and scripts

This folder collects, inside the gem5 repository, the important results,
reports, workloads and scripts of the value-prediction work on MinorCPU
(RISC-V, SE mode).  The implementation itself lives in `src/cpu/minor/`
(`lvp.*`, `astra.*`, `vcache.*`, `vastra.*`, `meta.*`, `execute.*`) and its
regression tests in `tests/lvp`, `tests/astra`, `tests/sou` and `tests/meta`.

Everything here was **copied** on 2026-10-29 (gem5 HEAD `19c2581b9b`) from the
validation directories outside the repository; the originals were not moved or
changed.  Every copy was checked byte for byte against its original.  The bulky
raw evidence (per-instruction traces, about 50 GB) stays outside, see
[Where the rest is](#where-the-rest-is).

## Layout

| Path | Contents |
|---|---|
| `scripts/run_meta_interactive.sh` | Interactive runner for the seven META performance workloads (menus; runs no prediction plus the chosen configuration and prints the cycle reduction) |
| `perf/stage2d/` | Stage 2d performance comparison: `src/perf.c` (the `stable`, `randbase`, `altvalue`, `vcmiss` workloads, WORK 1-4), the executables used (`bin/perf1..4`), their hashes (`exe-sha256.txt`), the drivers as run (`run_perf.py`, `run_sensitivity.py`, `analyze.py`), raw results (`runs.csv`, `sensitivity.csv`), medians (`summary.csv`, `tables.md`, `analysis-stdout.txt`) and `config-snapshots/` |
| `perf/stage3-meta/` | Stage 3 four-mode comparison (no prediction, LVP, V-ASTRA, META): the `meta.c` snapshot the new workloads were built from (`src/meta.c`), executables `bin/m3..m10` (`m6` fwdcold, `m7` mixed, `m9` fwdboth), hashes, drivers as run (`run_perf3.py`, `analyze3.py`), `runs.csv`, `summary.csv`, `analysis-stdout.txt` |
| `perf/stage3-meta-exp/` | The `metaAstraLvpLoads` experiment (`train`, `candidate`) on the same workloads: drivers, `runs.csv`, `summary.csv` |
| `reports/` | Design documents, audits and stage reports (see below) |
| `regression/` | Summaries of the full regression runs (`stage3-*-summary.txt`), the PASS/FAIL result logs of the META suites (`logs/`; the two largest are gzipped) and the piecewise drivers used to run the suites on a small disk (`drivers/`) |
| `runs/` | Output of the interactive runner (created on first use, ignored by git) |

### Reports

| Report | What it covers |
|---|---|
| `reports/early-2026-10-19/` | First ASTRA shadow-predictor and V$ stage summaries |
| `reports/stage2a/README.md`, `reports/stage2b-design/REPORT.md` | V-ASTRA probe and bypass design stages |
| `reports/paper-fidelity-audit/ASTRA_VASTRA_PAPER_FIDELITY_AUDIT.md` | How the implementation compares with the HPCA 2025 paper |
| `reports/stage2c-design/ISSUE_TIME_VASTRA_DESIGN.md` | Issue-time V-ASTRA design study (Design A scoreboard release) |
| `reports/stage2c-design-b/DESIGN_B_VASTRA_FORWARDING.md` | Design B: validated forwarding to dependent loads |
| `reports/stage2c-stall-on-use/README.md` | The stall-on-use baseline configuration |
| `reports/stage2c5-review/STAGE2C5_ALU_EXECUTION_VS_META.md` | Dependent-ALU execution versus META review |
| `reports/stage2c-postcommit/SUMMARY.md` | Post-commit validation of the ASTRA-V-ASTRA milestone |
| `reports/stage2d-perf/LVP_VASTRA_PERFORMANCE_COMPARISON.md` | LVP versus V-ASTRA performance before META |
| `reports/stage3-meta/STAGE3_META_REPORT.md` | META implementation, validation and four-mode performance |
| `reports/stage3-meta/EXPERIMENT_REPORT.md` | The `metaAstraLvpLoads` experiment |
| `reports/stage3-meta/AUDIT_candidate_mode.md` | Speculative-dependency audit of `candidate` mode |
| `reports/stage3-meta/RECOVERY-ldld-phase-sou.md` | Record of the disk-space recovery during the regression |
| `reports/stage3-meta/COMMIT_MSG_DRAFT.txt` | The message of the META commit |

## Headline results (default META: `enableMeta=True`, `metaAstraLvpLoads=off`)

ROI cycles, median of five runs (the same executable launched from five path
lengths; spread 0 except fwdboth, 0.025 %), with the cycle reduction against no
prediction.  Every run has the checksum and ROI committed-instruction count of
no prediction.  Source: `perf/stage3-meta/summary.csv` (the first four rows
equal the Stage 2d results of `perf/stage2d/summary.csv`).

| workload | no prediction (cycles) | LVP only | V-ASTRA only | META |
|---|---|---|---|---|
| stable | 34547 | 24047 (30.39%) | 5043 (85.4%) | 5043 (85.4%) |
| randbase | 35608 | 30620 (14.01%) | 18249 (48.75%) | 24828 (30.27%) |
| altvalue | 31344 | 25944 (17.23%) | 12819 (59.1%) | 12819 (59.1%) |
| vcmiss | 31144 | 24944 (19.91%) | 31144 (0.0%) | 24944 (19.91%) |
| fwdcold | 55141 | 55141 (0.0%) | 34003 (38.33%) | 34003 (38.33%) |
| mixed | 86491 | 79825 (7.71%) | 65054 (24.79%) | 59505 (31.2%) |
| fwdboth | 28908 | 28908 (0.0%) | 28405 (1.74%) | 28405 (1.74%) |

`cycle reduction = 100 * (no-prediction cycles - cycles) / no-prediction cycles`;
ROI cycles are `system.cpu.numCycles` in the first statistics block of
`stats.txt` (the programs reset the statistics before the measured laps and dump
them after); ROI committed instructions are `system.cpu.commitStats0.numInsts`
in the same block (`simInsts` also counts the warm-up).

## Running the workloads

Interactively (from any directory; needs `build/RISCV/gem5.opt`):

    bash research/astra-vastra-meta/scripts/run_meta_interactive.sh

Pick a workload, then a configuration; for LVP, V-ASTRA or META it also runs
no prediction and prints both cycle counts, the reduction, and whether the
checksums and instruction counts match.  One run is a preliminary measurement;
the simulator is deterministic, so it normally equals the five-run median.

By hand, one run (here: fwdcold under META; outputs to `/tmp/fwdcold-meta`,
which must not exist):

    build/RISCV/gem5.opt -d /tmp/fwdcold-meta tests/astra/with_params.py \
        --cmd=research/astra-vastra-meta/perf/stage3-meta/bin/m6 \
        --astra -P 'system.cpu[0].enableVCache=True' \
        -P 'system.cpu[0].enableVAstraDiag=True' \
        -P 'system.cpu[0].enableVAstraBypass=True' \
        -P 'system.cpu[0].enableVAstraScoreboardRelease=True' \
        -P 'system.cpu[0].enableVAstraForwarding=True' \
        --lvp --lvp-spec-addr -P 'system.cpu[0].enableMeta=True'

No prediction: `build/RISCV/gem5.opt -d DIR configs/research/vp_baseline.py
--cmd=EXE`; LVP only: the same with `--lvp --lvp-spec-addr`; V-ASTRA only:
`tests/astra/with_params.py` with the `--astra` and five `-P` options above.

The five repeats of the original experiment are the same executable copied into
directories with names of different lengths (`_`, `x`, `xxxx`, `xxxxxxxx`,
`xxxxxxxxxxxxxxxx`), which changes the stack layout.

**The drivers in `perf/` and `regression/drivers/` are kept as they were run:
they contain absolute paths to the original locations outside the repository
and write next to themselves.  Read them for reference; do not run them from
here without adapting the paths** (they would write into this folder).

## Where the rest is

Outside the repository, under `~/gem5-validation-2026-10-23/` and
`~/gem5-validation-2026-10-19/`: the raw output of every run (per-run
`stats.txt`, `config.ini`, compressed per-instruction traces) of all stages,
about 50 GB, for example `vastra-stage2b-implementation/stage3-meta/` (Stage 3
regression and experiments), `stage2c-release/`, `stage2c-forward/`,
`stage2c-postcommit/`, `hardening*/`.  The summaries and logs that state the
results are the ones copied here; the traces can be regenerated by running the
tests.  `~/gem5-venv/` holds the SCons 4.8.1 used to build gem5
(`PATH=~/gem5-venv/bin:$PATH scons build/RISCV/gem5.opt -j$(nproc)
PYTHON_CONFIG=/usr/bin/python3.12-config`), and `~/gem5-astra-backup-2026-10-18/`
a checksummed backup from before the ASTRA commit.
