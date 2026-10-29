#!/usr/bin/env python3
"""Stage 2d: LVP versus ASTRA/V-ASTRA, isolated modes, same binaries.
Runs every (workload, mode, repeat), keeps raw outputs, writes runs.csv."""
import csv, hashlib, os, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

P = os.path.dirname(os.path.abspath(__file__))
G = os.path.expanduser("~/gem5")
GEM5 = G + "/build/RISCV/gem5.opt"
BASE = G + "/configs/research/vp_baseline.py"
WP = G + "/tests/astra/with_params.py"
# repeats: the same executable copied to paths of different lengths (the
# layout of the stack, and so some cache set conflicts, depends on it)
PADS = ["", "x", "xxxx", "xxxxxxxx", "xxxxxxxxxxxxxxxx"]
WORKS = {1: "stable", 2: "randbase", 3: "altvalue", 4: "vcmiss"}
MODES = {
    "np": [],                                       # NO-PREDICTION
    "lv": ["--lvp", "--lvp-spec-addr"],             # LVP-ONLY
    "va": ["--astra", "-P", "system.cpu[0].enableVCache=True",
           "-P", "system.cpu[0].enableVAstraDiag=True",
           "-P", "system.cpu[0].enableVAstraBypass=True",
           "-P", "system.cpu[0].enableVAstraScoreboardRelease=True",
           "-P", "system.cpu[0].enableVAstraForwarding=True"],  # V-ASTRA-ONLY
}
STATS = ["numCycles", "dcache.ReadReq.hits::total", "dcache.ReadReq.misses::total",
         "dcache.overallMisses::total", "l2.overallMisses::total",
         "lvp.confidentPredictions", "lvp.correct", "lvp.incorrect",
         "lvp.specLoadsIssued", "lvp.specLoadsCommitted", "lvp.specLoadsSquashed",
         "lvp.mispredictSquashes", "astra.baseCorrect", "astra.baseIncorrect",
         "vastra.candidates", "vastra.syntheticResponses", "vastra.fwdPublished",
         "vastra.fwdAdmitted", "vastra.fwdCommitted", "vastra.fwdSquashed",
         "vastra.baseWrong", "vastra.fbTagMiss", "vastra.bypassAbandoned_"]

def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def roi_stats(path):
    """First statistics block: reset at m5_reset_stats, dumped at m5_dump_stats"""
    out, n = {}, 0
    for line in open(path):
        if line.startswith("---------- Begin"):
            n += 1
            if n > 1:
                break
        elif n == 1:
            m = re.match(r"(\S+)\s+(\S+)", line)
            if m:
                out[m.group(1)] = m.group(2)
    return out

def one(job):
    w, mode, rep = job
    pad = PADS[rep]
    bin_dir = f"{P}/bin/{pad or '_'}"
    exe = f"{bin_dir}/perf{w}"
    out = f"{P}/runs/W{w}/r{rep}/{mode}"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    args = [GEM5, "-d", out]
    if mode == "va":
        args += [WP, "--cmd=" + exe] + MODES[mode]
    else:
        args += [BASE, "--cmd=" + exe] + MODES[mode]
    with open(out + ".out", "w") as f:
        rc = subprocess.run(args, stdout=f, stderr=subprocess.STDOUT,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).returncode
    text = open(out + ".out", errors="replace").read()
    ck = re.search(r"checksum (\d+)", text)
    st = roi_stats(out + "/stats.txt") if os.path.exists(out + "/stats.txt") else {}
    row = {"workload": WORKS[w], "work": w, "mode": mode, "repeat": rep,
           "path_pad": len(pad), "rc": rc, "checksum": ck.group(1) if ck else "",
           "exe_sha256": sha(exe)[:16], "simInsts": st.get("simInsts", "")}
    for k in STATS:
        row[k] = st.get("system.cpu." + k, st.get("system." + k, ""))
    return row

if __name__ == "__main__":
    jobs = [(w, m, r) for w in WORKS for r in range(len(PADS)) for m in MODES]
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(one, jobs))
    # determinism: the first job again, same path
    again = one((1, "np", 0))
    rows.append(dict(again, repeat="0-again"))
    with open(f"{P}/runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(len(rows), "rows; failures:", [r for r in rows if r["rc"] != 0])
