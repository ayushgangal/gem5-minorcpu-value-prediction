# ASTRA Stage A step 1 - existing tests on the current binary (2026-10-19)
Binary build/RISCV/gem5.opt (2026-10-19 03:18:54, newer than every ASTRA source), LVP off, shadow ASTRA, 1024 entries.
Setups: sepy = tests/astra/run_astra.sh as written (se.py, RoundRobin, limits 2/2); canon = same runner copy through
canon_wrap.py running configs/research/vp_baseline.py unchanged (SingleThreaded, limits 16/16). Runs per setup: D (ASTRA off), S, SL (ASTRA log).
Results: sepy 78 PASS / 0 FAIL; canon 78 PASS / 0 FAIL; native `--astra --astra-entries 1024` run == wrapper run SL (stats, trace).
Checksum 4545984 and 117,928 committed instructions in every run. Cycles: sepy 633,448 (D=S=SL); canon 135,540 (D=S=SL).
ASTRA stats S: sepy look 649 train 640 correct 538 incorrect 102 squashed 9 faulted 0 unavailable 0; canon look 646 train 640 correct 548 incorrect 92 squashed 6 faulted 0 unavailable 0.
Squashed loads never trained (independent check of the SL logs: squashed and updated exec ids disjoint).
Caveat: the golden model is a re-implementation of the same inferences, not independent proof of paper fidelity.
Logs: sepy.log canon.log canon_native.log; run dirs sepy/ canon/ canon_native/; state-before.txt state-after.txt.
