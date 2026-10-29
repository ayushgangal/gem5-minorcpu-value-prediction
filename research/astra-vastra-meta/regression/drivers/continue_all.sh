#!/bin/bash
# Continuation after the disk recovery: remaining forward drain/reset pieces,
# bypass drain/reset, then the clean META config, directed and lifecycle suites.
# Sequential; stops (does not start the next piece) when free space < 2500 MB.
D=~/gem5-validation-2026-10-23/vastra-stage2b-implementation/stage3-meta/regression
S=$(dirname $D)
source ~/gem5-venv/bin/activate; export PYTHON_CONFIG=/usr/bin/python3.12-config
export PYTHONDONTWRITEBYTECODE=1
cd ~/gem5
guard() { local a; a=$(df --output=avail -m / | tail -1); echo "$1 avail=${a}MB" >> $D/summary.txt; [ "$a" -gt 2500 ] || { echo "free space below 2500MB, not starting $1" >> $D/summary.txt; exit 3; }; }
guard "forward tail"
V_OUT=$D/forward bash -c "$(cat $D/driver_forward_tail.sh)" ~/gem5/tests/sou/run_forward.sh > $D/forward-tail-driver.log 2>&1; echo "forward tail driver rc=$?" >> $D/summary.txt
guard "bypass drain"
OUT=$D/bypass-drain bash -c "$(cat $D/driver_bypass.sh)" ~/gem5/tests/astra/run_bypass.sh > $D/bypass-drain-driver.log 2>&1; echo "bypass drain driver rc=$?" >> $D/summary.txt
guard "meta config"
OUT=$S/meta-final/config bash tests/meta/run_meta.sh config > $S/logs/meta-final-config.log 2>&1; echo "meta config rc=$? PASS=$(grep -c '^PASS' $S/logs/meta-final-config.log) FAIL=$(grep -c '^FAIL' $S/logs/meta-final-config.log)" >> $D/summary.txt
guard "meta directed"
OUT=$S/meta-final bash tests/meta/run_meta.sh directed > $S/logs/meta-final-directed.log 2>&1; echo "meta directed rc=$? PASS=$(grep -c '^PASS' $S/logs/meta-final-directed.log) FAIL=$(grep -c '^FAIL' $S/logs/meta-final-directed.log)" >> $D/summary.txt
guard "meta lifecycle"
OUT=$S/meta-final bash tests/meta/run_meta.sh lifecycle > $S/logs/meta-final-lifecycle.log 2>&1; echo "meta lifecycle rc=$? PASS=$(grep -c '^PASS' $S/logs/meta-final-lifecycle.log) FAIL=$(grep -c '^FAIL' $S/logs/meta-final-lifecycle.log)" >> $D/summary.txt
echo "done continue_all" >> $D/summary.txt
