#!/bin/bash
S=~/gem5-validation-2026-10-23/vastra-stage2b-implementation/stage3-meta
D=$S/hard/regression
cd ~/gem5
export PYTHONDONTWRITEBYTECODE=1
guard() { local a; a=$(df --output=avail -m / | tail -1); echo "$1 avail=${a}MB" >> $D/summary.txt; [ "$a" -gt 1500 ] || { echo "free space below 1500MB, not starting $1" >> $D/summary.txt; exit 3; }; }
guard "astra-lvp full"
OUT=$S/hard bash tests/meta/run_meta.sh astra-lvp > $S/logs/hard-astra-lvp.log 2>&1; echo "astra-lvp rc=$? PASS=$(grep -c '^PASS' $S/logs/hard-astra-lvp.log) FAIL=$(grep -c '^FAIL' $S/logs/hard-astra-lvp.log)" >> $D/summary.txt
guard "meta config"
OUT=$S/hard/meta-final/config bash tests/meta/run_meta.sh config > $S/logs/hard-meta-config.log 2>&1; echo "meta config rc=$? PASS=$(grep -c '^PASS' $S/logs/hard-meta-config.log) FAIL=$(grep -c '^FAIL' $S/logs/hard-meta-config.log)" >> $D/summary.txt
guard "meta directed"
OUT=$S/hard/meta-final bash tests/meta/run_meta.sh directed > $S/logs/hard-meta-directed.log 2>&1; echo "meta directed rc=$? PASS=$(grep -c '^PASS' $S/logs/hard-meta-directed.log) FAIL=$(grep -c '^FAIL' $S/logs/hard-meta-directed.log)" >> $D/summary.txt
guard "meta lifecycle"
OUT=$S/hard/meta-final bash tests/meta/run_meta.sh lifecycle > $S/logs/hard-meta-lifecycle.log 2>&1; echo "meta lifecycle rc=$? PASS=$(grep -c '^PASS' $S/logs/hard-meta-lifecycle.log) FAIL=$(grep -c '^FAIL' $S/logs/hard-meta-lifecycle.log)" >> $D/summary.txt
for part in astra vcache vastra lvp bypass sou; do bash $D/run_all.sh $part; done
echo "done hard" >> $D/summary.txt
