# The drain/reset mode of tests/astra/run_bypass.sh against the committed
# build, piecewise (traces compressed after each workload; see
# driver_forward.sh).  The functions of run_bypass.sh are imported unchanged;
# the loops are copied from run_drain.
# Run as: OUT=<dir> bash -c "$(cat driver_bypass.sh)" ~/gem5/tests/astra/run_bypass.sh
eval "$(sed '/^case \${1:-} in/,$d' "$0")"
sq() { find "$1" -name trace.txt -print0 | xargs -0 -r -n1 -P4 gzip -9; }
status=0
d=$OUT/drain
rm -rf "${d:?}"; mkdir -p "$d"
build_va "$d/classify" classify
build_bp "$d/syscall" SYSCALL
build_bp "$d/latency" LAT
for mode in drain reset; do
    for w in classify syscall latency; do
        bin=$d/$w/va
        [ $w != classify ] && bin=$d/$w/bp
        wd=$d/$mode-$w
        mkdir -p "$wd"
        export DRAIN_MODE=$mode DRAIN_CHUNK=${CHUNK_OF[$w]}
        if [ $w = latency ]; then
            run_gem5 "$wd" P "$EXEC,VBypass" "$HERE/drain_reset.py" "$bin" "${BASE[@]}"
            run_gem5 "$wd" B "$EXEC,VBypass" "$HERE/drain_reset.py" "$bin" "${BASE[@]}" "${BYP[@]}"
        else
            run_pair "$wd" "$bin" "$HERE/drain_reset.py"
        fi
        unset DRAIN_MODE DRAIN_CHUNK
        python3 -I "$CHECKER" drain "$wd" "$mode" > "$OUT/drain-$mode-$w.log" 2>&1 || status=1
        echo "bypass drain $mode-$w: PASS=$(grep -c '^PASS' $OUT/drain-$mode-$w.log) FAIL=$(grep -c '^FAIL' $OUT/drain-$mode-$w.log)"
        sq "$wd"
    done
done
mkdir -p "$d/lvpw"
OUT=$d/lvpw/build "$ROOT/tests/lvp/run_lvp_stageb.sh" check-asm phase > "$d/lvpw/build.log" 2>&1
for mode in drain reset; do
    wd=$d/$mode-lvp
    mkdir -p "$wd"
    export DRAIN_MODE=$mode DRAIN_CHUNK=337000
    run_gem5 "$wd" P "$EXEC,VBypass" "$HERE/drain_reset.py" "$d/lvpw/build/phase/ldld" "${BASE[@]}"
    run_gem5 "$wd" B "$EXEC,VBypass" "$HERE/drain_reset.py" "$d/lvpw/build/phase/ldld" "${BASE[@]}" "${BYP[@]}"
    unset DRAIN_MODE DRAIN_CHUNK
    python3 -I "$CHECKER" drain "$wd" "$mode" > "$OUT/drain-$mode-lvp.log" 2>&1 || status=1
    echo "bypass drain $mode-lvp: PASS=$(grep -c '^PASS' $OUT/drain-$mode-lvp.log) FAIL=$(grep -c '^FAIL' $OUT/drain-$mode-lvp.log)"
    sq "$wd"
done
echo "bypass driver status=$status"
exit $status
