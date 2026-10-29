#!/usr/bin/env bash
#
# Interactive runner for the seven META performance workloads (gem5,
# MinorCPU, RISC-V SE mode).  Runs ONE workload in ONE configuration at a
# time, chosen from menus, and compares it against no prediction.
#
# Everything it uses is inside this gem5 repository, found relative to the
# script itself (research/astra-vastra-meta/scripts/), and never modified:
#   - the built simulator          build/RISCV/gem5.opt
#   - the research configurations  configs/research/vp_baseline.py
#                                  tests/astra/with_params.py
#   - the original workload executables, copied into
#     research/astra-vastra-meta/perf/{stage2d,stage3-meta}/bin/
#
# Every run goes to a new directory under research/astra-vastra-meta/runs/
# (ignored by git).  Nothing is rebuilt or compiled, and nothing existing is
# overwritten.
#
# Start it from anywhere with:
#   bash <gem5>/research/astra-vastra-meta/scripts/run_meta_interactive.sh

set -u
export PYTHONDONTWRITEBYTECODE=1    # never write .pyc files next to the configs
export LC_ALL=C

# ------------------------------------------------------------------ paths

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HERE=$(cd "$SCRIPT_DIR/.." && pwd)            # research/astra-vastra-meta
GEM5_DIR=$(cd "$HERE/../.." && pwd)           # the gem5 repository
GEM5="$GEM5_DIR/build/RISCV/gem5.opt"
BASE_CFG="$GEM5_DIR/configs/research/vp_baseline.py"
PARAM_CFG="$GEM5_DIR/tests/astra/with_params.py"

VAL="$HERE"
S2D="$HERE/perf/stage2d"
S3P="$HERE/perf/stage3-meta"
OUT_ROOT="$HERE/runs"
REPORTED="$S3P/summary.csv"          # the original five-run medians

CPU='system.cpu[0]'

# ---------------------------------------------------------------- workloads
# key | menu label | executable | recorded hash file | what it tests

WL_KEYS=(stable randbase altvalue vcmiss fwdcold mixed fwdboth)

declare -A WL_LABEL=(
  [stable]="Stable"
  [randbase]="Random base (randbase)"
  [altvalue]="Alternating value (altvalue)"
  [vcmiss]="V\$ miss (vcmiss)"
  [fwdcold]="Forwarding cold (fwdcold)"
  [mixed]="Mixed (mixed)"
  [fwdboth]="Forwarding both (fwdboth)"
)

declare -A WL_EXE=(
  [stable]="$S2D/bin/perf1"
  [randbase]="$S2D/bin/perf2"
  [altvalue]="$S2D/bin/perf3"
  [vcmiss]="$S2D/bin/perf4"
  [fwdcold]="$S3P/bin/m6"
  [mixed]="$S3P/bin/m7"
  [fwdboth]="$S3P/bin/m9"
)

# where the hash of each executable was recorded when the experiment ran
# (the records name the original locations; the bytes are the same)
declare -A WL_HASHFILE=(
  [stable]="$S2D/exe-sha256.txt"   [randbase]="$S2D/exe-sha256.txt"
  [altvalue]="$S2D/exe-sha256.txt" [vcmiss]="$S2D/exe-sha256.txt"
  [fwdcold]="$S3P/exe-sha256.txt"  [mixed]="$S3P/exe-sha256.txt"
  [fwdboth]="$S3P/exe-sha256.txt"
)
declare -A WL_HASHNAME=(
  [stable]="/perf1" [randbase]="/perf2" [altvalue]="/perf3" [vcmiss]="/perf4"
  [fwdcold]="bin/_/m6" [mixed]="bin/_/m7" [fwdboth]="bin/_/m9"
)

declare -A WL_INFO=(
  [stable]="Source: perf/stage2d/src/perf.c, WORK 1.  Each lap stores to four
  conflicting lines (evicting the hot lines from the L1 data cache; the V\$
  keeps them), then walks a chain of four dependent loads P->C->E->F whose
  addresses and values never change.  Every load misses the L1 and hits the
  L2.  ASTRA predicts every base, the V\$ holds every value: V-ASTRA can
  bypass all four loads without any memory access."
  [randbase]="Source: perf.c, WORK 2.  P's address is one of 8 lines picked by
  a 64-bit LCG (unpredictable for ASTRA), but all 8 lines hold the same
  pointer, so P's value is constant (LVP is confident).  C, E, F follow
  constant pointers.  V-ASTRA bypasses C, E, F; under META, P has no V-ASTRA
  record, LVP serves its consumers, and those LVP-served loads stop being
  V-ASTRA candidates."
  [altvalue]="Source: perf.c, WORK 3.  A store flips P's pointer every lap
  between two copies of the next node, so P's value changes every lap (LVP is
  never confident at P).  P's address is constant and C's alternates in a
  pattern ASTRA learns, so V-ASTRA bypasses the whole chain."
  [vcmiss]="Source: perf.c, WORK 4.  The four chain lines are 4096 bytes apart:
  they share one V\$ index and evict each other, so V-ASTRA always misses the
  V\$ and falls back.  The values are constant, so LVP can predict them.
  META selects LVP here."
  [fwdcold]="Source: perf/stage3-meta/src/meta.c, WORK 6 (FWD_SEG).  Each lap:
  M loads a never-touched (cold, DRAM) line and holds the head of the
  pipeline; P loads a pointer from a hot slot (V\$ hit); C loads the cold line
  P points to (another DRAM miss).  With V-ASTRA forwarding, P's validated
  value lets C send its request while M is still outstanding, so the two DRAM
  misses overlap.  P's value changes every lap, so LVP cannot help."
  [mixed]="Source: meta.c snapshot, WORK 7.  Each lap is the vcmiss chain
  (only LVP helps) followed by the fwdcold segment (only V-ASTRA forwarding
  helps).  META can use both in the same lap."
  [fwdboth]="Source: meta.c snapshot, WORK 9.  A cold load M holds the head;
  P reads one constant pointer and C, E follow constant pointers (all L1/V\$
  hits).  Both LVP and V-ASTRA could supply C's and E's source; META picks
  V-ASTRA.  The gain is small because each lap is dominated by M's DRAM miss."
)

# ----------------------------------------------------------- configurations

CFG_KEYS=(np lv va meta)
declare -A CFG_LABEL=(
  [np]="No prediction"
  [lv]="LVP only"
  [va]="V-ASTRA only (ASTRA + V\$ + bypass/forwarding)"
  [meta]="META (enableMeta=True, metaAstraLvpLoads=off)"
)
declare -A CFG_INFO=(
  [np]="Baseline MinorCPU, no value prediction (vp_baseline.py, no flags)."
  [lv]="Last-value prediction with address speculation: a dependent load may
  use a confident predicted value as its base address (--lvp --lvp-spec-addr)."
  [va]="ASTRA base prediction, the shadow value cache (V\$), the V-ASTRA bypass,
  scoreboard release and validated forwarding to dependent loads
  (with_params.py --astra -P ...)."
  [meta]="All V-ASTRA options plus LVP address speculation, with META choosing
  one source per dependent load: V-ASTRA if validated, nothing while V-ASTRA
  is pending, else LVP if admissible, else none.  metaAstraLvpLoads is left at
  its default (off)."
)

# fill CONFIG (the gem5 config script) and ARGS (its options) for a config key
set_config() {
  local va=(--astra
            -P "$CPU.enableVCache=True"
            -P "$CPU.enableVAstraDiag=True"
            -P "$CPU.enableVAstraBypass=True"
            -P "$CPU.enableVAstraScoreboardRelease=True"
            -P "$CPU.enableVAstraForwarding=True")
  case "$1" in
    np)   CONFIG="$BASE_CFG";  ARGS=() ;;
    lv)   CONFIG="$BASE_CFG";  ARGS=(--lvp --lvp-spec-addr) ;;
    va)   CONFIG="$PARAM_CFG"; ARGS=("${va[@]}") ;;
    meta) CONFIG="$PARAM_CFG"
          ARGS=("${va[@]}" --lvp --lvp-spec-addr -P "$CPU.enableMeta=True") ;;
    *)    return 1 ;;
  esac
}

# ---------------------------------------------------------------- helpers

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
line() { printf '%s\n' "----------------------------------------------------------------------"; }

CURRENT_RUN_DIR=""
on_interrupt() {
  echo
  if [ -n "$CURRENT_RUN_DIR" ]; then
    say "Interrupted while simulating.  The partial (incomplete) output stays in:"
    say "  $CURRENT_RUN_DIR"
  else
    say "Interrupted."
  fi
  exit 130
}
trap on_interrupt INT TERM

# read a menu choice; returns the number in REPLY_NUM
ask_number() {   # PROMPT MAX
  local prompt=$1 max=$2 r
  while true; do
    if ! read -r -p "$prompt" r; then echo; exit 0; fi   # Ctrl+D
    r=${r//[[:space:]]/}
    if [[ "$r" =~ ^[0-9]+$ ]] && [ "$r" -ge 0 ] && [ "$r" -le "$max" ]; then
      REPLY_NUM=$r
      return 0
    fi
    say "  Please type a number from 0 to $max and press Enter."
  done
}

ask_yes_no() {   # PROMPT -> 0 for yes
  local r
  while true; do
    if ! read -r -p "$1 [y/n]: " r; then echo; exit 0; fi
    case "${r,,}" in
      y|yes) return 0 ;;
      n|no)  return 1 ;;
      *)     say "  Please answer y or n." ;;
    esac
  done
}

# the first statistics block of stats.txt is the region of interest (the
# programs reset the statistics before it and dump them after it)
roi_stat() {     # STATS_FILE NAME -> value or empty
  awk -v key="$2" '
    /^---------- Begin Simulation Statistics/ { n++; next }
    /^---------- End Simulation Statistics/   { if (n == 1) exit; next }
    n == 1 && $1 == key { print $2; exit }
  ' "$1"
}

checksum_of() {  # LOG -> the number the program printed after "checksum"
  grep -oE '^checksum [0-9]+' "$1" | head -n 1 | awk '{print $2}'
}

# original five-run median and reduction from the retained summary
reported() {     # WORKLOAD MODE -> "median reduction" or empty
  [ -r "$REPORTED" ] || return 0
  awk -F, -v w="$1" -v m="$2" '
    NR == 1 { for (i = 1; i <= NF; i++) col[$i] = i; next }
    $1 == w && $2 == m {
      print $col["roi_cycles_median"], $col["cycle_reduction_percent_median"]
      exit
    }' "$REPORTED"
}

check_inputs() { # WORKLOAD -> 0 if everything needed exists
  local ok=0 f
  for f in "$GEM5" "$BASE_CFG" "$PARAM_CFG" "${WL_EXE[$1]}"; do
    if [ ! -e "$f" ]; then warn "missing: $f"; ok=1; fi
  done
  [ -x "$GEM5" ] || { warn "not executable: $GEM5"; ok=1; }
  return $ok
}

verify_exe_hash() {  # WORKLOAD: compare with the hash recorded at the time
  local exe=${WL_EXE[$1]} hf=${WL_HASHFILE[$1]} name=${WL_HASHNAME[$1]}
  local want got
  want=$(awk -v n="$name" 'index($2, n) && substr($2, length($2) - length(n) + 1) == n { print $1; exit }' "$hf" 2>/dev/null)
  got=$(sha256sum "$exe" | awk '{print $1}')
  if [ -z "$want" ]; then
    warn "no recorded hash for $exe in $hf (cannot confirm it is the original)"
  elif [ "$want" != "$got" ]; then
    warn "$exe does not match the hash recorded in $hf"
    return 1
  else
    say "  Executable matches the hash recorded for the original experiment."
  fi
}

# --------------------------------------------------------------- one run

# run one workload in one configuration into RUN_ROOT/<config>; sets
# R_CYCLES R_INSTS R_CHECKSUM R_DIR, returns nonzero on any failure
run_one() {      # WORKLOAD CONFIG_KEY RUN_ROOT
  local wl=$1 key=$2 root=$3 dir log rc
  set_config "$key" || return 1
  dir="$root/$key"
  log="$root/$key.log"
  R_CYCLES=""; R_INSTS=""; R_CHECKSUM=""; R_DIR=$dir

  if [ -e "$dir" ] || [ -e "$log" ]; then
    warn "$dir already exists; not overwriting it"
    return 1
  fi

  say ""
  say ">>> Running ${WL_LABEL[$wl]} with: ${CFG_LABEL[$key]}"
  say "    output: $dir"
  say "    log:    $log"
  say "    (this usually takes from a few seconds to about a minute)"

  CURRENT_RUN_DIR=$dir
  "$GEM5" -d "$dir" "$CONFIG" --cmd="${WL_EXE[$wl]}" "${ARGS[@]}" \
      > "$log" 2>&1
  rc=$?
  CURRENT_RUN_DIR=""

  # the exact command, for reproducing it by hand later
  {
    printf 'cd %q &&' "$PWD"
    printf ' %q' "$GEM5" -d "$dir" "$CONFIG" --cmd="${WL_EXE[$wl]}" "${ARGS[@]}"
    printf '\n'
  } > "$root/$key.command"

  if [ $rc -ne 0 ]; then
    warn "gem5 exited with status $rc.  Last lines of the log:"
    tail -n 15 "$log" >&2
    return 1
  fi
  if [ ! -s "$dir/stats.txt" ]; then
    warn "no statistics file: $dir/stats.txt"
    return 1
  fi

  R_CYCLES=$(roi_stat "$dir/stats.txt" system.cpu.numCycles)
  R_INSTS=$(roi_stat "$dir/stats.txt" system.cpu.commitStats0.numInsts)
  R_CHECKSUM=$(checksum_of "$log")

  if [ -z "$R_CYCLES" ] || [ -z "$R_INSTS" ]; then
    warn "could not read the ROI statistics from $dir/stats.txt"
    return 1
  fi
  if [ -z "$R_CHECKSUM" ]; then
    warn "the program did not print a checksum (see $log)"
    return 1
  fi

  say "    done: ROI cycles $R_CYCLES, ROI committed instructions $R_INSTS," \
      "checksum $R_CHECKSUM"
  return 0
}

# ------------------------------------------------------------- one session

run_session() {  # WORKLOAD CONFIG_KEY
  local wl=$1 key=$2 stamp root
  local b_cyc b_ins b_ck b_dir s_cyc s_ins s_ck s_dir red rep

  check_inputs "$wl" || { say "Cannot run: inputs are missing."; return 1; }

  line
  say "Workload:      ${WL_LABEL[$wl]}"
  say "  ${WL_INFO[$wl]}"
  say "  Executable:  ${WL_EXE[$wl]}"
  verify_exe_hash "$wl" || {
    ask_yes_no "The executable differs from the original.  Run anyway?" ||
      return 1
  }
  say ""
  say "Configuration: ${CFG_LABEL[$key]}"
  say "  ${CFG_INFO[$key]}"
  say ""
  say "Program: 100 warm-up laps, then a measured region of 200 laps"
  say "(the region of interest, ROI).  Measured: system.cpu.numCycles in the"
  say "first statistics block of stats.txt (the ROI)."
  if [ "$key" != np ]; then
    say "Two simulations will run: no prediction (the baseline), then"
    say "${CFG_LABEL[$key]}, and the cycle reduction is computed."
  fi
  line
  ask_yes_no "Start?" || { say "Not started."; return 0; }

  stamp=$(date +%Y%m%d-%H%M%S)-$$-$RANDOM
  root="$OUT_ROOT/$wl/$stamp"
  if ! mkdir -p "$OUT_ROOT/$wl" || ! mkdir "$root"; then
    warn "cannot create the output directory $root"
    return 1
  fi

  run_one "$wl" np "$root" || { say "Baseline run failed."; return 1; }
  b_cyc=$R_CYCLES; b_ins=$R_INSTS; b_ck=$R_CHECKSUM; b_dir=$R_DIR

  if [ "$key" = np ]; then
    line
    say "RESULT  ${WL_LABEL[$wl]}, ${CFG_LABEL[np]}"
    say "  ROI cycles:                    $b_cyc"
    say "  ROI committed instructions:    $b_ins"
    say "  checksum:                      $b_ck"
    say "  output directory:              $b_dir"
    rep=$(reported "$wl" np)
    [ -n "$rep" ] && say "  original five-run median:      ${rep%% *} cycles"
    say "  (one run: a preliminary measurement, not the five-run median)"
    line
    return 0
  fi

  run_one "$wl" "$key" "$root" ||
    { say "${CFG_LABEL[$key]} run failed."; return 1; }
  s_cyc=$R_CYCLES; s_ins=$R_INSTS; s_ck=$R_CHECKSUM; s_dir=$R_DIR

  red=$(awk -v b="$b_cyc" -v s="$s_cyc" 'BEGIN { printf "%.2f", 100 * (b - s) / b }')

  line
  say "RESULT  ${WL_LABEL[$wl]}"
  printf '  %-34s %12s %14s %18s\n' "configuration" "ROI cycles" \
      "ROI insts" "checksum"
  printf '  %-34s %12s %14s %18s\n' "${CFG_LABEL[np]}" "$b_cyc" "$b_ins" "$b_ck"
  printf '  %-34s %12s %14s %18s\n' "${CFG_LABEL[$key]%% (*}" "$s_cyc" \
      "$s_ins" "$s_ck"
  say ""
  if [ "$b_ck" = "$s_ck" ] && [ "$b_ins" = "$s_ins" ]; then
    say "  Checksum and ROI committed instruction count are identical:"
    say "  this is a like-for-like comparison."
    say "  Cycle reduction = 100 * ($b_cyc - $s_cyc) / $b_cyc = ${red}%"
  else
    say "  !!! The checksum or the ROI committed instruction count DIFFERS"
    say "  !!! between the two runs.  The cycle difference (${red}%) is NOT a"
    say "  !!! verified like-for-like comparison.  Check the logs."
  fi
  rep=$(reported "$wl" "$key")
  if [ -n "$rep" ]; then
    say "  Original experiment (five-run median): ${rep%% *} cycles," \
        "${rep##* }% reduction"
  fi
  say "  Note: this is ONE run of each configuration, a preliminary"
  say "  measurement, not the original five-run median.  (The simulator is"
  say "  deterministic, so the same executable and configuration normally"
  say "  give the same cycles.)"
  say ""
  say "  baseline output:  $b_dir"
  say "  selected output:  $s_dir"
  say "  logs and exact commands: $root/{np,$key}.{log,command}"
  line
}

# ------------------------------------------------------------------- menus

workload_menu() {
  echo
  line
  say "META performance workloads -- choose one to run"
  line
  local i=1 k
  for k in "${WL_KEYS[@]}"; do
    printf '  %d. %s\n' "$i" "${WL_LABEL[$k]}"
    i=$((i + 1))
  done
  say "  0. Exit"
  ask_number "Workload number: " "${#WL_KEYS[@]}"
}

config_menu() {  # WORKLOAD
  echo
  say "Workload: ${WL_LABEL[$1]}.  Choose a configuration:"
  say "  1. No prediction            (baseline only)"
  say "  2. LVP only                 (baseline + LVP, with the reduction)"
  say "  3. V-ASTRA only             (ASTRA + V\$ + bypass/forwarding;"
  say "                               baseline + V-ASTRA, with the reduction)"
  say "  4. META                     (baseline + META, with the reduction)"
  say "  0. Back to workload selection"
  ask_number "Configuration number: " 4
}

main() {
  say "Interactive META workload runner"
  say "  simulator: $GEM5"
  say "  outputs:   $OUT_ROOT/<workload>/<run id>/"
  local free_mb
  free_mb=$(df -Pm "$VAL" 2>/dev/null | awk 'NR == 2 {print $4}')
  if [ -n "$free_mb" ] && [ "$free_mb" -lt 500 ]; then
    warn "only ${free_mb} MB free on the disk holding $VAL"
  fi

  while true; do
    workload_menu
    [ "$REPLY_NUM" -eq 0 ] && { say "Bye."; exit 0; }
    local wl=${WL_KEYS[$((REPLY_NUM - 1))]}

    while true; do
      config_menu "$wl"
      [ "$REPLY_NUM" -eq 0 ] && break
      run_session "$wl" "${CFG_KEYS[$((REPLY_NUM - 1))]}"
      ask_yes_no "Run another workload or configuration?" || { say "Bye."; exit 0; }
      ask_yes_no "Same workload (${WL_LABEL[$wl]})?" || break
    done
  done
}

main "$@"
