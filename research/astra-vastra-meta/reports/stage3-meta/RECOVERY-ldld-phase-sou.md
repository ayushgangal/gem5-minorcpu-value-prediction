# Recovery of forward lifecycle ldld-phase-sou (Design B regression piece)
- 11:26 disk-low events: caused by localsearch-3 (GNOME indexer) rewriting ~/.cache/tracker3/files/meta.db (+1.1 GB WAL), not by gem5.
- R run (pid 383851) had a pending SIGTERM from the disk guard; ended exit_code 15; incomplete trace kept as R.incomplete/trace.txt.incomplete.gz (+ .sha256, INCOMPLETE.txt). Driver chain (run_all.sh, driver_forward.sh, subshell) was SIGKILLed while stopped (my scripts, no evidence touched).
- P: trace.txt.gz (sha256 of original in P/trace.txt.sha256 == hash of gzip -dc stream), uncompressed copy removed.
- rerun 1 of R used a longer --cmd path: sp differs by 0x10 (24 lines) -> stream check FAILED honestly (log kept: lifecycle-ldld-phase-sou.rerun1-pathlength-mismatch.log, R.rerun1-pathlength/).
- rerun 2 (rerun_R.sh) with the driver's exact path: R trace 2295273234 bytes (== post-commit run); unmodified check_forward.py lifecycle with P streamed through a FIFO: PASS=15 FAIL=0 (lifecycle-ldld-phase-sou.log).
- Disk is btrfs compress=zstd:1: traces cost ~5% of their logical size; deleting uncompressed traces frees little; gz files do not shrink further.
