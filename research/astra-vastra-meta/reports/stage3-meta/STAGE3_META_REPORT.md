# Stage 3: META selection between LVP and ASTRA-V-ASTRA

Source: branch `astra-vastra-dev`, HEAD `88f72e2bd461756a2b5ca0ca5fa1f3ed4accf2cf` (unchanged, nothing staged,
committed or pushed) plus uncommitted META changes.  Binary: `build/RISCV/gem5.opt` sha256 prefix `9f9f8ca1a12a8cde`
(built 03:06:53, newer than every file in `src/cpu/minor`; scons exit 0, 46m51s, log `logs/build1.log`).
Build command: see memory note; venv SCons 4.8.1 + `PYTHON_CONFIG=/usr/bin/python3.12-config` (system SCons 4.11 fails the zlib check).

## Files
Modified: `src/cpu/minor/{BaseMinorCPU.py,SConscript,dyn_inst.hh,execute.cc,execute.hh}` (+277/-12).
New: `src/cpu/minor/{meta.cc,meta.hh}`, `tests/meta/{README.md,meta.c,check_meta.py,run_meta.sh}`.

## Implementation
* `enableMeta` (default false).  Fatal unless `enableLVP && lvpSpecAddr && enableVAstraForwarding`; rejected with
  `vastraTestSkipSyscallFlush` / `vastraTestSkipStoreScan`.  The forwarding/`lvpSpecAddr` exclusion remains without META.
* `Execute::metaSelect` (one explicit decision per consumer evaluation, `MetaSource {None,VAstra,LVP}`):
  V-ASTRA if the producer's record is Validated (calls the unchanged `vastraFwdAdmissible`); nothing while the record is
  Pending; otherwise LVP if the unchanged `lvpSpecAdmissible` holds; otherwise none.  The early-issue block uses it
  instead of the two independent tests.  LVP prediction, confidence, validation and recovery code is untouched.
* The accepted source is recorded where the request enters the LSQ (`executeMemRefInst`), and `metaClassify` panics if a
  consumer ever has both roles or a source disagreeing with its LVP/V-ASTRA lifecycle.  `MetaSelector` (meta.cc) keeps
  per-window accounting (evaluated + carryIn = resolved + inFlight) and survives drain/reset like the other groups;
  the drain check panics on live consumers.
* A V-ASTRA-served consumer never sets `lvpUsedBySpec`, so a wrong LVP prediction for its producer raises no recovery.
* Not done on purpose: a load served by an LVP operand still does not capture its ASTRA base (existing rule in
  `astraCaptureBase`), so it is not a V-ASTRA candidate itself (see randbase below).

## Evidence (all retained under this directory)
| Suite | Result | Log |
|---|---|---|
| META config | 20 PASS / 0 FAIL | logs/meta-final-config.log |
| META directed (kernels 1-10 x np/lvp/va/meta, forward.c) | 270 / 0 | logs/meta-final-directed.log |
| META lifecycle (24 programs x np/meta, drain/reset) | 4601 / 0 | logs/meta-final-lifecycle.log |
| Existing suites (ASTRA 78, targeted 340, V$ 157, V-ASTRA incl verify-detect 276, LVP 772, bypass 297, stall-on-use 17, Design A 255, Design B config 10 / directed 64 / lifecycle 201, bypass drain/reset 112) | 2579 / 0 | regression/ |
| Total | 7470 PASS / 0 FAIL | |
Counts of the old suites equal the post-commit run.  The first META runs had checker-side faults (parser assumptions) that were
fixed and rechecked; no check was weakened.  One honest FAIL was recorded and superseded: `regression/forward/lifecycle-ldld-phase-sou.rerun1-pathlength-mismatch.log`
(rerun with a longer program path shifted sp by 0x10; the exact rerun passes, 15/0).  Disk-recovery notes: `logs/RECOVERY-ldld-phase-sou.md`.

Selection evidence (traces, not counters): every `META decide` line is checked against the V-ASTRA record events
(`create/publish/fail`) of its producer; every accepted consumer equals a V-ASTRA `admit` or an LVP `accepted` line, never
both; V-ASTRA consumers were admitted after publication and their request entered the LSQ before the producer committed
(k6: 131, k9: 276, k10: 272 consumers); every LVP recovery follows an incorrect validation and none involves a V-ASTRA
consumer; k3/k10: LVP wrong 3 times with 0 recoveries (LVP-only recovers 3 on k3); k4: 3 recoveries in META and in LVP-only;
k5: nothing predicted; k2/k4: V$ miss falls back and LVP serves; forward.c: older-store rejects (14) and abandoned
candidates (14) never publish, 47 chained forwards, squashed consumers, committed stream identical to NO-PREDICTION.
The only path not observed is "V-ASTRA pending while LVP is ready" (`meta.lvpHeldForVAstra` = 0 in every run): the pending case
(13 consumers in forward.c) never had the LVP admission rule satisfied.

## Performance (ROI cycles, 5 path-length repeats, `perf/summary.csv`, `perf/runs.csv`, raw `perf/runs/`)
Spread across repeats is 0 for every cell except fwdboth/fwdflip (<= 0.15%).  Every mode of every workload has the checksum
and committed instruction count of NO-PREDICTION.  NP/LVP/V-ASTRA of the four Stage 2d workloads equal the Stage 2d cycles exactly.

| workload | NP | LVP | V-ASTRA | META | META source mix (evaluated: V/L/none) |
|---|---|---|---|---|---|
| stable | 34547 | 24047 (-30.39%) | 5043 (-85.40%) | 5043 (-85.40%) | 200: 0/0/200 |
| randbase | 35608 | 30620 (-14.01%) | 18249 (-48.75%) | **24828 (-30.27%)** | 746: 0/386/360 |
| altvalue | 31344 | 25944 (-17.23%) | 12819 (-59.10%) | 12819 (-59.10%) | 200: 0/0/200 |
| vcmiss | 31144 | 24944 (-19.91%) | 31144 (0.00%) | 24944 (-19.91%) | 800: 0/600/200 |
| stableflip | 32151 | 26831 (-16.55%) | 12912 (-59.84%) | 13039 (-59.44%) | 218: 0/12/206 |
| vcflip | 32752 | 24046 (-26.58%) | 32699 (-0.16%) | 24046 (-26.58%) | 805: 0/593/212 |
| none | 37837 | 37837 (0%) | 30810 (-18.57%) | 30810 (-18.57%) | 566: 0/0/566 |
| fwdcold (forwarding) | 55141 | 55141 (0%) | 34003 (-38.33%) | 34003 (-38.33%) | 200: 188/0/12, fwdAdmitted 188 |
| mixed | 86491 | 79825 (-7.71%) | 65054 (-24.79%) | **59505 (-31.20%)** | 1000: 188/600/212 |
| pdstore | 33748 | 25447 (-24.60%) | 25123 (-25.56%) | 25123 (-25.56%) | 3: 0/3/0 |
| fwdboth | 28908 | 28908 | 28405 (-1.74%) | 28405 (-1.74%) | 600: 400/0/200, over-LVP 400 |
| fwdflip | 28979 | 28979 | 28755 (-0.77%) | 28755 (-0.77%) | 600: 394/0/206, over-LVP 388 |
Forwarding is exercised in fwdcold, mixed, fwdboth and fwdflip (fwdAdmitted 188-400; laps are bound by DRAM misses and L2 hits,
no delay loop).  META equals the better standalone mode on 9 of 12 workloads, is better than both on `mixed`, +1% cycles vs
V-ASTRA on stableflip (12 LVP consumers where V-ASTRA had no record), and clearly worse than V-ASTRA-only on `randbase`.

randbase explanation (trace/counter evidence, `perf/runs/randbase/r0/{va,meta}/stats.txt`): P's base is random, so P has no V-ASTRA record and
META (correctly by the prescribed policy) serves its consumers by LVP (386).  A load running on an LVP-supplied operand does not capture its ASTRA
base (`astraCaptureBase`, existing rule), so those 386 loads are no longer V-ASTRA candidates (`vastra.metadataMissing` 386, candidates 595 -> 209):
V-ASTRA-only bypasses them without a memory access, META sends them to the L2.  This is an integration cost of selecting per consumer
operand; it was not changed because it needs the LVP-supplied base to be validated before it can train/validate ASTRA.

## Differences from the paper / limitations
* Validation is not at issue: V-ASTRA values are validated later in the LSQ path and LVP at the producer's response.
* Selection is per dependent load's source operand, not the paper's per-load value selection with both predictors training in parallel.
* No dependent-ALU early execution (out of scope); the V$ is shadow, per-byte valid, SE mode, one CPU, one thread.
* `lvpHeldForVAstra` (pending V-ASTRA with LVP ready) is implemented and trace-checked by rule but never occurred in these workloads.
* Kernels are extreme latency-bound microbenchmarks; default timing only except the stall-on-use regression.
* Style: `tests/meta` and one `BaseMinorCPU.py` help string have lines > 79 columns; formatting hooks were not run (nothing is committed).

## Integrity
`git diff --check` clean; HEAD unchanged; index and stash empty; `vp_baseline.py` and `vp_stall_on_use.py` byte-identical to HEAD blobs;
ASTRA backup 12/12 OK.  `tests/astra/__pycache__/check_vcache.cpython-314.pyc` (git-ignored derived cache) was regenerated at 03:29:52 by a checker
run under `python3 -I` (which ignores PYTHONDONTWRITEBYTECODE); source unchanged, old bytes not recoverable.  No generated output in the repo.
Removed (own artifacts only): 848 MB of gz traces of an earlier META directed/lifecycle run (`logs/removed-traces-meta-directed-lifecycle.txt`, superseded by `meta-final/`), the incomplete R uncompressed trace (kept as .gz).
