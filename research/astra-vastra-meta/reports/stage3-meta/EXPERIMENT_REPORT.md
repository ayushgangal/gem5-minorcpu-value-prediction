# Experiment: metaAstraLvpLoads (off | train | candidate)
Binary `4f54e5664db498c1` (build logs/build-exp1.log failed on a missing SConscript enum entry, logs/build-exp2.log exit 0).
Tests (all retained): config 25/0 (logs/exp-config.log); astra-lvp programs 8036/0 (logs/exp-k11.log: k11 randbase, ldld stable/phase/fanout/fault/chain,
forward.c, drain/reset) and 380/0 (logs/exp-kernels.log: k3 k4 k5 k7 k10); confirmation regression on the new binary with the parameter off:
existing suites 1937/0 (ASTRA, targeted, V$, V-ASTRA, LVP, bypass, stall-on-use; same counts as before), META config 25/0, directed 270/0, lifecycle 4601/0.
Performance: perf-exp/summary.csv, runs.csv, runs/ (361 runs, 12 workloads x 6 modes x 5 path lengths, same executables and ROI as perf/).
With the parameter off, np/lv/va/meta cycles equal the earlier Stage 3 results on all 12 workloads.
