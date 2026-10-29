# Design A suites of tests/sou/run_release.sh against the committed build,
# piecewise (see driver_forward.sh).  config, directed + selftest (the
# selftest needs the uncompressed trace, so it runs before compression),
# then the lifecycle programs one at a time.
# Run as: bash -c "$(cat driver_release.sh)" ~/gem5/tests/sou/run_release.sh
eval "$(sed '/^case \${1:-} in/,$d' "$0")"
OUT=$V_OUT
mkdir -p "$OUT"
sq() { find "$1" -name trace.txt -print0 | xargs -0 -r -n1 -P4 gzip -9; }
status=0
# config
OUT=$OUT/config-run run_config > "$V_OUT/release-config.log" 2>&1 || status=1
echo "release config: PASS=$(grep -c '^PASS' $V_OUT/release-config.log) FAIL=$(grep -c '^FAIL' $V_OUT/release-config.log)"
# directed, then selftest on the uncompressed trace
OUT=$V_OUT/directed-run run_directed > "$V_OUT/release-directed.log" 2>&1 || status=1
echo "release directed: PASS=$(grep -c '^PASS' $V_OUT/release-directed.log) FAIL=$(grep -c '^FAIL' $V_OUT/release-directed.log)"
python3 -I "$HERE/check_release.py" selftest "$V_OUT/directed-run/directed" > "$V_OUT/release-selftest.log" 2>&1 || status=1
echo "release selftest: PASS=$(grep -c '^PASS' $V_OUT/release-selftest.log) FAIL=$(grep -c '^FAIL' $V_OUT/release-selftest.log)"
sq "$V_OUT/directed-run"
# lifecycle, one program at a time (the commands of run_lifecycle)
l=$V_OUT/lifecycle; chk=$V_OUT/lifecycle-check
rm -rf "${l:?}" "${chk:?}"; mkdir -p "$l" "$chk"
check_one() {
    mkdir -p "$chk/$1"; ln -sfn "$l/$1" "$chk/$1/$1"
    python3 -I "$HERE/check_release.py" lifecycle "$chk/$1" > "$V_OUT/release-lifecycle-$1.log" 2>&1 || status=1
    echo "release lifecycle $1: PASS=$(grep -c '^PASS' $V_OUT/release-lifecycle-$1.log) FAIL=$(grep -c '^FAIL' $V_OUT/release-lifecycle-$1.log)"
    sq "$l/$1"
}
for m in discard fault store classify; do
    mkdir -p "$l/vastra-$m"
    OUT=$l/vastra-$m/build bash "$ROOT/tests/astra/run_vastra.sh" check-asm "$m" > "$l/vastra-$m/build.log" 2>&1
    pair "$l/vastra-$m" "$l/vastra-$m/build/$m/va"
    check_one vastra-$m
done
for m in ATOMIC ABANDON SPLIT FP SYSCALL SUB SPECIAL; do
    mkdir -p "$l/bypass-$m"
    build "$ROOT/tests/astra/bypass.c" "$l/bypass-$m/bp" -DBP_"$m"
    pair "$l/bypass-$m" "$l/bypass-$m/bp"
    check_one bypass-$m
done
for mode in drain reset; do
    mkdir -p "$l/$mode-classify" "$l/$mode-SYSCALL"
    PAIRCFG=$ROOT/tests/astra/drain_reset.py DRAIN_MODE=$mode DRAIN_CHUNK=1500000 pair "$l/$mode-classify" "$l/vastra-classify/build/classify/va"
    check_one $mode-classify
    PAIRCFG=$ROOT/tests/astra/drain_reset.py DRAIN_MODE=$mode DRAIN_CHUNK=1500000 pair "$l/$mode-SYSCALL" "$l/bypass-SYSCALL/bp"
    check_one $mode-SYSCALL
done
echo "release driver status=$status"
exit $status
