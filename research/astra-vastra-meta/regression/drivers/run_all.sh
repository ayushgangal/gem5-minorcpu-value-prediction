#!/bin/bash
# Stage 3 regression: every existing suite against the build with META, plus
# the META suites.  Heavy suites run one after the other, traces compressed
# after each (the checkers have run by then).  Summary in summary.txt.
D=~/gem5-validation-2026-10-23/vastra-stage2b-implementation/stage3-meta/regression
source ~/gem5-venv/bin/activate; export PYTHON_CONFIG=/usr/bin/python3.12-config
export PYTHONDONTWRITEBYTECODE=1
cd ~/gem5
sq() { find "$1" -name trace.txt -print0 2>/dev/null | xargs -0 -r -n1 -P4 gzip -9; }
guard() { local a; a=$(df --output=avail -m ~ | tail -1); echo "$1 avail=${a}MB" >> $D/summary.txt; [ "$a" -gt 500 ] || { echo "disk low, stop" >> $D/summary.txt; exit 3; }; }
run() { n=$1; shift; guard "before $n"; OUT=$D/$n bash "$@" > $D/$n.log 2>&1; echo "$n rc=$? PASS=$(grep -c '^PASS' $D/$n.log) FAIL=$(grep -c '^FAIL' $D/$n.log)" >> $D/summary.txt; sq $D/$n; }
only=${1:-all}
want() { [ "$only" = all ] || [ "$only" = "$1" ]; }
want astra && run astra tests/astra/run_astra.sh run
want astra_targeted && run astra_targeted tests/astra/run_astra_targeted.sh all
want vcache && run vcache tests/astra/run_vcache.sh all
want vastra && run vastra tests/astra/run_vastra.sh all
if want lvp; then
  run lvp_run tests/lvp/run_lvp_stageb.sh run
  for m in threshold pcwindow invalid-config confidence alias; do run lvp_$m tests/lvp/run_lvp_stageb.sh $m; done
fi
if want bypass; then
  for m in config classify store discard fault syscall atomic abandon order sub split fp synonym special syscall-negative latency lvp; do
    run bypass_$m tests/astra/run_bypass.sh $m
  done
fi
want sou && run sou tests/sou/run_sou.sh
if want release; then guard "before release"; V_OUT=$D/release bash -c "$(cat $D/driver_release.sh)" ~/gem5/tests/sou/run_release.sh > $D/release-driver.log 2>&1; echo "release driver rc=$?" >> $D/summary.txt; fi
if want forward; then
  guard "before forward"; run forward_config tests/sou/run_forward.sh config
  V_OUT=$D/forward bash -c "$(cat $D/driver_forward.sh)" ~/gem5/tests/sou/run_forward.sh > $D/forward-driver.log 2>&1; echo "forward driver rc=$?" >> $D/summary.txt
fi
if want bypass_drain; then guard "before bypass drain"; OUT=$D/bypass-drain bash -c "$(cat $D/driver_bypass.sh)" ~/gem5/tests/astra/run_bypass.sh > $D/bypass-drain-driver.log 2>&1; echo "bypass drain driver rc=$?" >> $D/summary.txt; fi
echo "done $only" >> $D/summary.txt
