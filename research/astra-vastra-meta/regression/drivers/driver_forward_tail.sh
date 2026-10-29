# Continuation of driver_forward.sh after ldld-phase-sou: the drain/reset programs only.
# Existing lifecycle evidence is not touched.
# Runs the Design B suites of tests/sou/run_forward.sh against the committed
# build, piecewise (one directed configuration / one lifecycle program at a
# time, traces compressed after each piece) because the disk cannot hold all
# traces at once.  The functions of run_forward.sh are imported unchanged; the
# commands inside the loops are copied from run_directed / run_lifecycle.
# Run as: bash -c "$(cat driver_forward.sh)" ~/gem5/tests/sou/run_forward.sh
eval "$(sed '/^case \${1:-} in/,$d' "$0")"
OUT=$V_OUT
mkdir -p "$OUT"
sq() { find "$1" -name trace.txt -print0 | xargs -0 -r -n1 -P4 gzip -9; }
status=0

# ---- lifecycle, one program at a time
l=$OUT/lifecycle; chk=$OUT/lifecycle-check
mkdir -p "$l" "$chk"   # NOT removed: continuation of the run
sou=$ROOT/configs/research/vp_stall_on_use.py
def=$ROOT/configs/research/vp_baseline.py
check_one() {   # NAME
    mkdir -p "$chk/$1"; ln -sfn "$l/$1" "$chk/$1/$1"
    python3 -I "$HERE/check_forward.py" lifecycle "$chk/$1" > "$OUT/lifecycle-$1.log" 2>&1 || status=1
    echo "lifecycle $1: PASS=$(grep -c '^PASS' $OUT/lifecycle-$1.log) FAIL=$(grep -c '^FAIL' $OUT/lifecycle-$1.log)"
    sq "$l/$1"
}
for mode in drain reset; do
    mkdir -p "$l/$mode-classify" "$l/$mode-SYSCALL" "$l/$mode-forward"
    PAIRCFG=$ROOT/tests/astra/drain_reset.py DRAIN_MODE=$mode DRAIN_CHUNK=1500000 pair "$l/$mode-classify" "$l/vastra-classify/build/classify/va" "$def"
    check_one $mode-classify
    PAIRCFG=$ROOT/tests/astra/drain_reset.py DRAIN_MODE=$mode DRAIN_CHUNK=1500000 pair "$l/$mode-SYSCALL" "$l/bypass-SYSCALL/bp" "$def"
    check_one $mode-SYSCALL
    build "$HERE/forward.c" "$l/$mode-forward/fw"
    PAIRCFG=$ROOT/tests/astra/drain_reset.py DRAIN_MODE=$mode DRAIN_CHUNK=3000000 pair "$l/$mode-forward" "$l/$mode-forward/fw" "$def"
    check_one $mode-forward
done
echo "forward driver status=$status"
exit $status
