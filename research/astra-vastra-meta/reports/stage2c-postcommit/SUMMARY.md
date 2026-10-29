# Post-commit validation of 88f72e2bd461756a2b5ca0ca5fa1f3ed4accf2cf (branch astra-vastra-dev)

Build: build/RISCV/gem5.opt, `scons` incremental check recompiled nothing (binary built from the committed source).
All commands ran with PYTHONDONTWRITEBYTECODE=1; the checkers are run with `python3 -I`.
Because the disk has ~3 GB free, the heavy suites were run piecewise by drivers (driver_forward.sh,
driver_release.sh, driver_bypass.sh) that import the functions of the committed run_*.sh scripts unchanged
(`eval "$(sed '/^case/,$d' run_X.sh)"`), repeat the loops of run_directed / run_lifecycle / run_drain, run the
unchanged checkers per piece and gzip the traces after each piece.

| Test | Command | rc | PASS / FAIL | Log |
|---|---|---|---|---|
| Forward directed, stall-on-use | driver_forward.sh (run_directed body) | 0 | 34 / 0 | forward/directed-stall-on-use.log |
| Forward directed, default | same | 0 | 30 / 0 | forward/directed-default.log |
| Forward lifecycle (27 programs incl. drain/reset-classify, -SYSCALL, -forward) | driver_forward.sh | 0 | 201 / 0 | forward/lifecycle-*.log |
| Forward config | OUT=... tests/sou/run_forward.sh config | 0 | 10 / 0 | forward-config.log |
| Release config | driver_release.sh (run_config) | 0 | 2 / 0 | release/release-config.log |
| Release directed | driver_release.sh (run_directed) | 0 | 37 / 0 | release/release-directed.log |
| Release selftest (uncompressed trace) | check_release.py selftest, run before compression | 0 | 3 / 0 | release/release-selftest.log |
| Release lifecycle (15 programs incl. drain/reset) | driver_release.sh | 0 | 213 / 0 | release/release-lifecycle-*.log |
| Bypass drain/reset (classify, syscall, latency, lvp x drain, reset) | driver_bypass.sh | 0 | 8 x 14 / 0 | bypass-drain/drain-*.log |
| Stall-on-use | OUT=... tests/sou/run_sou.sh | 0 | 17 / 0 | sou.log, sou-config-ini.diff |
