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

# ---- directed, one configuration at a time
for name in stall-on-use default; do
    d=$OUT/directed-$name
    if [ $name = default ]; then cfgfile=$ROOT/configs/research/vp_baseline.py; config=default
    else cfgfile=$ROOT/configs/research/vp_stall_on_use.py; config=stall-on-use; fi
    rm -rf "${d:?}"; mkdir -p "$d"
    build "$HERE/forward.c" "$d/fw"
    : > "$d/pcs.txt"
    for s in ch bw tm sc ab pd cm ft sq; do
        for i in M S P C E U; do
            "$NM" "$d/fw" | awk -v s="${s}_$i" '$3 == s { print s, "0x" $1 }' >> "$d/pcs.txt"
        done
    done
    echo "$config" > "$d/config.txt"
    pair "$d" "$d/fw" "$cfgfile"
    echo "=== directed ($config)"
    python3 -I "$HERE/check_forward.py" directed "$d" > "$OUT/directed-$name.log" 2>&1 || status=1
    echo "directed-$name: PASS=$(grep -c '^PASS' $OUT/directed-$name.log) FAIL=$(grep -c '^FAIL' $OUT/directed-$name.log)"
    sq "$d"
done

# ---- lifecycle, one program at a time
l=$OUT/lifecycle; chk=$OUT/lifecycle-check
rm -rf "${l:?}" "${chk:?}"; mkdir -p "$l" "$chk"
sou=$ROOT/configs/research/vp_stall_on_use.py
def=$ROOT/configs/research/vp_baseline.py
check_one() {   # NAME
    mkdir -p "$chk/$1"; ln -sfn "$l/$1" "$chk/$1/$1"
    python3 -I "$HERE/check_forward.py" lifecycle "$chk/$1" > "$OUT/lifecycle-$1.log" 2>&1 || status=1
    echo "lifecycle $1: PASS=$(grep -c '^PASS' $OUT/lifecycle-$1.log) FAIL=$(grep -c '^FAIL' $OUT/lifecycle-$1.log)"
    sq "$l/$1"
}
for m in discard fault store classify; do
    mkdir -p "$l/vastra-$m"
    OUT=$l/vastra-$m/build bash "$ROOT/tests/astra/run_vastra.sh" check-asm "$m" > "$l/vastra-$m/build.log" 2>&1
    pair "$l/vastra-$m" "$l/vastra-$m/build/$m/va" "$def"
    check_one vastra-$m
done
for m in ATOMIC ABANDON SPLIT FP SYSCALL SUB SPECIAL; do
    mkdir -p "$l/bypass-$m"
    build "$ROOT/tests/astra/bypass.c" "$l/bypass-$m/bp" -DBP_"$m"
    pair "$l/bypass-$m" "$l/bypass-$m/bp" "$def"
    check_one bypass-$m
done
for m in stable phase; do
    mkdir -p "$l/ldld-$m"
    OUT=$l/ldld-$m/build bash "$ROOT/tests/lvp/run_lvp_stageb.sh" check-asm "$m" > "$l/ldld-$m/build.log" 2>&1
    pair "$l/ldld-$m" "$l/ldld-$m/build/$m/ldld" "$def"
    check_one ldld-$m
    mkdir -p "$l/ldld-$m-sou"
    pair "$l/ldld-$m-sou" "$l/ldld-$m/build/$m/ldld" "$sou"
    check_one ldld-$m-sou
done
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
