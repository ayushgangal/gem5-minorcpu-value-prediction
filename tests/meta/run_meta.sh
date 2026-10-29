#!/bin/bash
#
# Tests of META selection between LVP address speculation and V-ASTRA
# forwarding (enableMeta; see README.md).
#
#   run_meta.sh config      parameter combinations that are rejected / accepted
#   run_meta.sh directed    meta.c kernels and forward.c under NP, LVP, V-ASTRA
#                           and META: architectural equivalence, the selection
#                           rule on the traces, one source per consumer
#   run_meta.sh lifecycle   existing programs (LVP, V-ASTRA, bypass) under
#                           META, drain and statistics reset
#   run_meta.sh astra-lvp   the metaAstraLvpLoads experiment (off / train /
#                           candidate) against NO-PREDICTION on meta.c, the
#                           LVP programs and forward.c, and drain / reset
#   run_meta.sh align       meta.c kernel 13 with check_alignment: an LVP
#                           operand makes an early load fault in initiateAcc,
#                           the load runs again at the head (np / off / train
#                           / cand)
#   run_meta.sh all
#
# OUT (default /tmp/meta-test) is where everything is written.  gem5 must
# already be built.

set -euo pipefail

ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
HERE=$ROOT/tests/meta
OUT=${OUT:-/tmp/meta-test}
CC=${CC:-riscv64-linux-gnu-gcc}
NM=${NM:-riscv64-linux-gnu-nm}
GEM5=${GEM5:-$ROOT/build/RISCV/gem5.opt}
CFG=$ROOT/tests/astra/with_params.py
FLAGS=MinorExecute,MinorMem,VBypass,VAstra,META,LVP
FLAGS=$FLAGS,ExecEnable,ExecUser,ExecResult,ExecEffAddr
CPU='system.cpu[0]'
# tests/lvp/ldld.c walks 16384 slots: the lifecycle and astra-lvp suites build
# it with -DNUM_SLOTS=1024 (small instruction traces), which needs the
# definition made overridable in a copy of the source
SLOTS_SED='s/^#define NUM_SLOTS 16384/#ifndef NUM_SLOTS\n'
SLOTS_SED+='#define NUM_SLOTS 16384\n#endif/'

# parameter sets, as -P arguments (applied just before instantiation)
VA=(--astra -P "$CPU.enableVCache=True" -P "$CPU.enableVAstraDiag=True"
    -P "$CPU.enableVAstraBypass=True"
    -P "$CPU.enableVAstraScoreboardRelease=True")
FWD=(-P "$CPU.enableVAstraForwarding=True")
LVPSPEC=(--lvp --lvp-spec-addr)
META=(-P "$CPU.enableMeta=True")

# MODE -> arguments
mode_args()    # np | lvp | va | meta
{
    case $1 in
    np) ;;
    lvp) echo "${LVPSPEC[@]}" ;;
    va) echo "${VA[@]} ${FWD[@]}" ;;
    meta | off) echo "${VA[@]} ${FWD[@]} ${LVPSPEC[@]} ${META[@]}" ;;
    train) echo "${VA[@]} ${FWD[@]} ${LVPSPEC[@]} ${META[@]}" \
        "-P $CPU.metaAstraLvpLoads=train" ;;
    cand) echo "${VA[@]} ${FWD[@]} ${LVPSPEC[@]} ${META[@]}" \
        "-P $CPU.metaAstraLvpLoads=candidate" ;;
    esac
}

build()    # SRC OUTBIN [-D...]
{
    local src=$1 bin=$2
    shift 2
    "$CC" -O1 -static -nostdlib -ffreestanding -march=rv64g -mabi=lp64d \
        -Wl,-n -Wl,--no-relax-gp -Wl,-e,_start "$@" -o "$bin" "$src" \
        2> /dev/null
}

run_config()
{
    local d=$OUT/config bad=0 rc
    rm -rf "${d:?}"
    mkdir -p "$d"
    build "$HERE/meta.c" "$d/m" -DWORK=1 -DWARM=2 -DROI=2
    cfgcase()    # NAME EXPECT(ok|MESSAGE) args...
    {
        local name=$1 expect=$2
        shift 2
        rc=0
        "$GEM5" -d "$d/$name" "$CFG" --cmd="$d/m" "$@" > "$d/$name.out" \
            2>&1 || rc=$?
        if [ "$expect" = ok ]; then
            if [ $rc -eq 0 ] &&
                grep -q "Beginning simulation" "$d/$name.out"; then
                echo "PASS  $name: accepted"
            else echo "FAIL  $name: rejected (rc $rc)"; bad=$((bad + 1)); fi
        else
            if [ $rc -ne 0 ] &&
                ! grep -q "Beginning simulation" "$d/$name.out" &&
                grep -q "$expect" "$d/$name.out"; then
                echo "PASS  $name: rejected: $expect"
            else echo "FAIL  $name: not rejected as expected (rc $rc)"
                 bad=$((bad + 1)); fi
        fi
    }
    local M=(-P "$CPU.enableMeta=True")
    local X=(-P "$CPU.metaAstraLvpLoads=candidate")
    local V=(-P "$CPU.enableVCache=True")
    local D=(-P "$CPU.enableVAstraDiag=True")
    local B=(-P "$CPU.enableVAstraBypass=True")
    local R=(-P "$CPU.enableVAstraScoreboardRelease=True")
    local F=(-P "$CPU.enableVAstraForwarding=True")
    local VAB=(--astra "${V[@]}" "${D[@]}" "${B[@]}" "${R[@]}")
    # META needs both predictors and forwarding
    cfgcase meta-alone "enableMeta requires" "${M[@]}"
    cfgcase meta-no-lvp "enableMeta requires" "${VAB[@]}" "${F[@]}" "${M[@]}"
    cfgcase meta-lvp-no-specaddr "enableMeta requires" "${VAB[@]}" "${F[@]}" \
        --lvp "${M[@]}"
    cfgcase meta-no-forwarding "enableMeta requires" "${VAB[@]}" \
        "${LVPSPEC[@]}" "${M[@]}"
    cfgcase meta-no-bypass "requires" --astra "${V[@]}" "${D[@]}" "${R[@]}" \
        "${F[@]}" "${LVPSPEC[@]}" "${M[@]}"
    cfgcase meta-no-release "requires" --astra "${V[@]}" "${D[@]}" "${B[@]}" \
        "${F[@]}" "${LVPSPEC[@]}" "${M[@]}"
    cfgcase meta-no-astra "requires" "${V[@]}" "${D[@]}" "${B[@]}" "${R[@]}" \
        "${F[@]}" "${LVPSPEC[@]}" "${M[@]}"
    # test-only fault injection is excluded
    cfgcase meta-skip-flush "must not be combined" "${VAB[@]}" "${F[@]}" \
        "${LVPSPEC[@]}" "${M[@]}" -P "$CPU.vastraTestSkipSyscallFlush=True"
    cfgcase meta-skip-scan "must not be combined" "${VAB[@]}" "${F[@]}" \
        "${LVPSPEC[@]}" "${M[@]}" -P "$CPU.vastraTestSkipStoreScan=True"
    # the V$ guards apply
    rc=0
    EXTRA_CPU=timing VP_CONFIG=$ROOT/configs/research/vp_baseline.py "$GEM5" \
        -d "$d/two-cpu" "$ROOT/tests/astra/with_cpus.py" --cmd="$d/m" \
        "${VAB[@]}" "${F[@]}" "${LVPSPEC[@]}" "${M[@]}" > "$d/two-cpu.out" \
        2>&1 || rc=$?
    if [ $rc -ne 0 ] && grep -q "need exactly one CPU" "$d/two-cpu.out"; then
        echo "PASS  two-cpu: rejected: need exactly one CPU"
    else
        echo "FAIL  two-cpu: not rejected (rc $rc)"; bad=$((bad + 1))
    fi
    # the valid configuration
    cfgcase meta-ok ok "${VAB[@]}" "${F[@]}" "${LVPSPEC[@]}" "${M[@]}"
    cfgcase meta-ok-window ok "${VAB[@]}" "${F[@]}" "${LVPSPEC[@]}" "${M[@]}" \
        --lvp-window 0x10000 0x20000
    # strict verification excludes the bypass, and so META (existing rule)
    cfgcase meta-verify "mutually exclusive" "${VAB[@]}" "${F[@]}" \
        "${LVPSPEC[@]}" "${M[@]}" -P "$CPU.enableVAstraVerify=True"
    # the experiment parameter needs META
    cfgcase astra-lvp-without-meta "metaAstraLvpLoads requires enableMeta" \
        "${VAB[@]}" "${F[@]}" "${X[@]}"
    cfgcase astra-lvp-candidate ok "${VAB[@]}" "${F[@]}" "${LVPSPEC[@]}" \
        "${M[@]}" "${X[@]}"
    cfgcase astra-lvp-train ok "${VAB[@]}" "${F[@]}" "${LVPSPEC[@]}" \
        "${M[@]}" -P "$CPU.metaAstraLvpLoads=train"
    cfgcase astra-lvp-bad-value "" "${VAB[@]}" "${F[@]}" "${LVPSPEC[@]}" \
        "${M[@]}" -P "$CPU.metaAstraLvpLoads=maybe"
    if grep -q "metaAstraLvpLoads=off" "$d/meta-ok/config.ini"; then
        echo "PASS  metaAstraLvpLoads defaults to off (config.ini)"
    else
        echo "FAIL  metaAstraLvpLoads default"; bad=$((bad + 1))
    fi
    # the standalone configurations are unchanged
    cfgcase np ok
    cfgcase lvp-only ok --lvp
    cfgcase lvp-spec ok "${LVPSPEC[@]}"
    cfgcase vastra-only ok "${VAB[@]}"
    cfgcase vastra-fwd ok "${VAB[@]}" "${F[@]}"
    cfgcase fwd-and-lvpspec-without-meta "mutually exclusive" "${VAB[@]}" \
        "${F[@]}" "${LVPSPEC[@]}"
    if grep -q "enableMeta=false" "$d/vastra-fwd/config.ini" &&
       grep -q "enableMeta=true" "$d/meta-ok/config.ini"; then
        echo "PASS  enableMeta is false by default and true in the META" \
            "configuration (config.ini)"
    else
        echo "FAIL  enableMeta values in config.ini"; bad=$((bad + 1))
    fi
    [ $bad -eq 0 ] || { echo "$bad configuration check(s) failed"; return 1; }
}

# one program in the four modes, with traces (DIR BINARY [extra args])
quad()
{
    local d=$1 bin=$2 m rc
    shift 2
    for m in np lvp va meta; do
        rc=0
        # shellcheck disable=SC2046
        (ulimit -c 0; "$GEM5" -d "$d/$m" --debug-flags="$FLAGS" \
            --debug-file=trace.txt "$CFG" --cmd="$bin" $(mode_args $m) "$@" \
            > "$d/$m.out" 2>&1) || rc=$?
        echo "$rc" > "$d/$m.rc"
        echo "$(basename "$d") $m: exit status $rc"
    done
}

KERNELS=${KERNELS:-"1 2 3 4 5 6 7 8 9 10"}

run_directed()
{
    local d=$OUT/directed k fail=0
    mkdir -p "$d"
    for k in $KERNELS; do
        rm -rf "${d:?}/k$k"
        mkdir -p "$d/k$k"
        build "$HERE/meta.c" "$d/k$k/m" -DWORK="$k" -DWARM=40 -DROI=100
        "$NM" "$d/k$k/m" | awk '$3 ~ /^(k|f)_[A-Z]$/ { print $3, "0x" $1 }' \
            > "$d/k$k/pcs.txt"
        quad "$d/k$k" "$d/k$k/m"
        python3 -I "$HERE/check_meta.py" directed-one "$d/k$k" "$k" || fail=1
        gzip -f "$d"/k"$k"/*/trace.txt
    done
    # the forwarding workload of the V-ASTRA forwarding tests, all sections
    rm -rf "${d:?}/forward"
    mkdir -p "$d/forward"
    build "$ROOT/tests/sou/forward.c" "$d/forward/fw"
    quad "$d/forward" "$d/forward/fw"
    python3 -I "$HERE/check_meta.py" directed-forward "$d/forward" || fail=1
    gzip -f "$d"/forward/*/trace.txt
    return $fail
}

# an existing program under NO-PREDICTION and META, with traces
duo()    # DIR BINARY [extra args]   (LIGHT=1: no per-instruction trace)
{
    local d=$1 bin=$2 m rc fl=$FLAGS
    [ -z "${LIGHT:-}" ] || fl=VBypass,VAstra,META,LVP
    shift 2
    for m in np meta; do
        rc=0
        # shellcheck disable=SC2046
        (ulimit -c 0; "$GEM5" -d "$d/$m" --debug-flags="$fl" \
            --debug-file=trace.txt "${PAIRCFG:-$CFG}" --cmd="$bin" \
            $(mode_args $m) "$@" > "$d/$m.out" 2>&1) || rc=$?
        echo "$rc" > "$d/$m.rc"
        echo "$(basename "$d") $m: exit status $rc"
    done
}

# check one program directory now and compress its traces
finish()    # DIR
{
    python3 -I "$HERE/check_meta.py" lifecycle-one "$1" || LIFE_FAIL=1
    gzip -f "$1"/*/trace.txt
}

run_lifecycle()
{
    local l=$OUT/lifecycle m w mode
    LIFE_FAIL=0
    mkdir -p "$l"
    local def=$ROOT/configs/research/vp_baseline.py
    # the LVP programs (stable, phase change, fan-out, fault, chain)
    declare -A LDLD=([stable]="" [phase]="-DLVP_PHASE"
        [fanout]="-DLVP_PHASE -DLVP_FANOUT" [fault]="-DLVP_FAULT"
        [chain]="-DLVP_CHAIN")
    for w in stable phase fanout fault chain; do
        rm -rf "${l:?}/ldld-$w"; mkdir -p "$l/ldld-$w"
        # shellcheck disable=SC2086
        # the programs walk 16384 slots: a shorter walk (1024) keeps the
        # instruction traces small; nothing else is changed
        sed "$SLOTS_SED" "$ROOT/tests/lvp/ldld.c" > "$l/ldld-$w/ldld.c"
        build "$l/ldld-$w/ldld.c" "$l/ldld-$w/ld" -DNUM_SLOTS=1024 ${LDLD[$w]}
        # the fault program sweeps 256 KiB 32 times: no per-instruction trace
        [ $w != fault ] || export LIGHT=1
        duo "$l/ldld-$w" "$l/ldld-$w/ld"
        unset LIGHT
        finish "$l/ldld-$w"
    done
    # the V-ASTRA programs: discard, fault, store, classify
    for m in discard fault store classify; do
        rm -rf "${l:?}/vastra-$m"; mkdir -p "$l/vastra-$m"
        OUT=$l/vastra-$m/build bash "$ROOT/tests/astra/run_vastra.sh" \
            check-asm "$m" > "$l/vastra-$m/build.log" 2>&1
        duo "$l/vastra-$m" "$l/vastra-$m/build/$m/va"
        finish "$l/vastra-$m"
    done
    # the bypass programs, with the syscall flush
    for m in ATOMIC ABANDON SPLIT FP SYSCALL SUB SPECIAL; do
        rm -rf "${l:?}/bypass-$m"; mkdir -p "$l/bypass-$m"
        build "$ROOT/tests/astra/bypass.c" "$l/bypass-$m/bp" -DBP_"$m"
        duo "$l/bypass-$m" "$l/bypass-$m/bp"
        finish "$l/bypass-$m"
    done
    # drain and statistics reset
    for mode in drain reset; do
        for w in classify SYSCALL forward ldld-phase; do
            local d=$l/$mode-$w bin chunk=1500000
            rm -rf "${d:?}"; mkdir -p "$d"
            case $w in
            classify) bin=$l/vastra-classify/build/classify/va ;;
            SYSCALL) bin=$l/bypass-SYSCALL/bp ;;
            forward) bin=$d/fw; build "$ROOT/tests/sou/forward.c" "$bin"
                     chunk=3000000 ;;
            ldld-phase) bin=$l/ldld-phase/ld; chunk=500000 ;;
            esac
            PAIRCFG=$ROOT/tests/astra/drain_reset.py DRAIN_MODE=$mode \
                DRAIN_CHUNK=$chunk duo "$d" "$bin"
            finish "$d"
        done
    done
    return $LIFE_FAIL
}

# one program under np, off (the current META), train and cand, with traces
quad4()    # DIR BINARY [extra args]   (LIGHT=1: no per-instruction trace)
{
    local d=$1 bin=$2 m rc fl=$FLAGS${EXTRA_FLAGS:+,$EXTRA_FLAGS}
    shift 2
    [ -z "${LIGHT:-}" ] || fl=VBypass,VAstra,META,LVP,ASTRA
    for m in np off train cand; do
        rc=0
        # shellcheck disable=SC2046
        (ulimit -c 0; "$GEM5" -d "$d/$m" --debug-flags="$fl" \
            --debug-file=trace.txt "${PAIRCFG:-$CFG}" --cmd="$bin" \
            $(mode_args $m) "$@" > "$d/$m.out" 2>&1) || rc=$?
        echo "$rc" > "$d/$m.rc"
        echo "$(basename "$d") $m: exit status $rc"
    done
}

run_astra_lvp()
{
    local l=$OUT/astra-lvp k w fail=0 d mode chunk bin
    mkdir -p "$l"
    one()    # NAME BINARY [extra]
    {
        local name=$1 binary=$2
        shift 2
        quad4 "$l/$name" "$binary" "$@"
        python3 -I "$HERE/check_meta.py" astra-lvp-one "$l/$name" || fail=1
        gzip -f "$l"/"$name"/*/trace.txt
    }
    for k in ${KERNELS:-3 4 5 7 10 11 12}; do
        rm -rf "${l:?}/k$k"; mkdir -p "$l/k$k"
        build "$HERE/meta.c" "$l/k$k/m" -DWORK="$k" -DWARM=40 -DROI=100
        one "k$k" "$l/k$k/m"
    done
    # KERNELS_ONLY=1: only the meta.c kernels of this invocation
    [ -z "${KERNELS_ONLY:-}" ] || return $fail
    declare -A LDLD=([stable]="" [phase]="-DLVP_PHASE"
        [fanout]="-DLVP_PHASE -DLVP_FANOUT" [fault]="-DLVP_FAULT"
        [chain]="-DLVP_CHAIN")
    for w in stable phase fanout fault chain; do
        rm -rf "${l:?}/ldld-$w"; mkdir -p "$l/ldld-$w"
        sed "$SLOTS_SED" "$ROOT/tests/lvp/ldld.c" > "$l/ldld-$w/ldld.c"
        # shellcheck disable=SC2086
        build "$l/ldld-$w/ldld.c" "$l/ldld-$w/ld" -DNUM_SLOTS=1024 ${LDLD[$w]}
        [ $w != fault ] || export LIGHT=1
        one "ldld-$w" "$l/ldld-$w/ld"
        unset LIGHT
    done
    rm -rf "${l:?}/forward"; mkdir -p "$l/forward"
    build "$ROOT/tests/sou/forward.c" "$l/forward/fw"
    one forward "$l/forward/fw"
    # drain and statistics reset
    for mode in drain reset; do
        for w in forward ldld-phase; do
            d=$mode-$w
            rm -rf "${l:?}/$d"; mkdir -p "$l/$d"
            if [ $w = forward ]; then bin=$l/forward/fw; chunk=3000000
            else bin=$l/ldld-phase/ld; chunk=500000; fi
            PAIRCFG=$ROOT/tests/astra/drain_reset.py DRAIN_MODE=$mode \
                DRAIN_CHUNK=$chunk one "$d" "$bin"
        done
    done
    return $fail
}

run_align()
{
    local l=$OUT/align fail=0
    rm -rf "${l:?}"
    mkdir -p "$l"
    build "$HERE/meta.c" "$l/m" -DWORK=13 -DWARM=20 -DROI=40
    "$NM" "$l/m" | awk '$3 ~ /^k_(P1|P|C)$/ { print $3, "0x" $1 }' \
        > "$l/pcs.txt"
    PAIRCFG=$HERE/with_alignment.py EXTRA_FLAGS=ASTRA quad4 "$l" "$l/m"
    python3 -I "$HERE/check_meta.py" align-one "$l" || fail=1
    gzip -f "$l"/*/trace.txt
    return $fail
}

case ${1:-} in
config) run_config ;;
align) run_align ;;
astra-lvp) run_astra_lvp ;;
lifecycle) run_lifecycle ;;
directed) run_directed ;;
all)
    status=0
    for m in config directed lifecycle; do
        echo "=== $m"
        bash "$0" "$m" || status=1
    done
    exit $status
    ;;
*) sed -n '3,/^$/{/^$/!p}' "$0" >&2; exit 2 ;;
esac
