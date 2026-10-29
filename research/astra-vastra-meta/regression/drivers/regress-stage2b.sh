#!/bin/bash
D=~/gem5-validation-2026-10-23/vastra-stage2b-implementation/regression
source ~/gem5-venv/bin/activate; export PYTHON_CONFIG=/usr/bin/python3.12-config
cd ~/gem5
run() { n=$1; shift; OUT=$D/$n bash "$@" > $D/$n.log 2>&1; echo "$n rc=$?" >> $D/summary.txt; }
run astra tests/astra/run_astra.sh run
run astra_targeted tests/astra/run_astra_targeted.sh all
run vcache tests/astra/run_vcache.sh all
run vastra tests/astra/run_vastra.sh all
run lvp_run tests/lvp/run_lvp_stageb.sh run
for m in threshold pcwindow invalid-config confidence alias; do run lvp_$m tests/lvp/run_lvp_stageb.sh $m; done
echo done >> $D/summary.txt
