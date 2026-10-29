#!/usr/bin/env python3
"""Stage 3: NO-PREDICTION, LVP-ONLY, V-ASTRA-ONLY and META on the Stage 2d
workloads (same executables) and the new META workloads.  Same ROI (first
statistics block), same repeat procedure (same executable under five path
lengths) as Stage 2d.  Raw outputs kept under runs/; rows in runs.csv."""
import csv, hashlib, os, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

P = os.path.dirname(os.path.abspath(__file__))
S2D = os.path.expanduser("~/gem5-validation-2026-10-23/vastra-stage2b-implementation/stage2d-perf")
G = os.path.expanduser("~/gem5")
GEM5 = G + "/build/RISCV/gem5.opt"
BASE = G + "/configs/research/vp_baseline.py"
WP = G + "/tests/astra/with_params.py"
PADS = ["", "x", "xxxx", "xxxxxxxx", "xxxxxxxxxxxxxxxx"]
C = "system.cpu[0]."
VA = ["--astra", "-P", C + "enableVCache=True", "-P", C + "enableVAstraDiag=True",
      "-P", C + "enableVAstraBypass=True", "-P", C + "enableVAstraScoreboardRelease=True",
      "-P", C + "enableVAstraForwarding=True"]
MODES = {"np": (BASE, []), "lv": (BASE, ["--lvp", "--lvp-spec-addr"]), "va": (WP, VA),
         "meta": (WP, VA + ["--lvp", "--lvp-spec-addr", "-P", C + "enableMeta=True"])}
# (name, source, executable file)
WORKS = [("stable", "s2d", "perf1"), ("randbase", "s2d", "perf2"), ("altvalue", "s2d", "perf3"),
         ("vcmiss", "s2d", "perf4"),
         ("stableflip", "new", "m3"), ("vcflip", "new", "m4"), ("none", "new", "m5"),
         ("fwdcold", "new", "m6"), ("mixed", "new", "m7"), ("pdstore", "new", "m8"),
         ("fwdboth", "new", "m9"), ("fwdflip", "new", "m10")]
STATS = ["numCycles", "commitStats0.numInsts", "dcache.ReadReq.hits::total",
         "dcache.ReadReq.misses::total", "dcache.overallMisses::total", "l2.overallMisses::total",
         "lvp.confidentPredictions", "lvp.correct", "lvp.incorrect", "lvp.specLoadsIssued",
         "lvp.specLoadsCommitted", "lvp.specLoadsSquashed", "lvp.mispredictSquashes",
         "vastra.candidates", "vastra.syntheticResponses", "vastra.fwdPublished",
         "vastra.fwdAdmitted", "vastra.fwdCommitted", "vastra.fwdSquashed",
         "vastra.baseWrong", "vastra.fbTagMiss", "vastra.bypassAbandoned_",
         "meta.consumersEvaluated", "meta.selVAstra", "meta.selLVP", "meta.selNone",
         "meta.vastraValidated", "meta.vastraPending", "meta.vastraFailed",
         "meta.vastraNoRecord", "meta.lvpAdmissible", "meta.lvpRefused",
         "meta.lvpHeldForVAstra", "meta.vastraOverLvp", "meta.bothAdmissible"]

def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def roi_stats(path):
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

def exe_path(src, f, rep):
    pad = PADS[rep]
    base = S2D if src == "s2d" else P
    return f"{base}/bin/{pad or '_'}/{f}"

def one(job):
    (name, src, f), mode, rep = job
    exe = exe_path(src, f, rep)
    out = f"{P}/runs/{name}/r{rep}/{mode}"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cfg, extra = MODES[mode]
    args = [GEM5, "-d", out, cfg, "--cmd=" + exe] + extra
    with open(out + ".out", "w") as fo:
        rc = subprocess.run(args, stdout=fo, stderr=subprocess.STDOUT,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).returncode
    text = open(out + ".out", errors="replace").read()
    ck = re.search(r"checksum (\d+)", text)
    st = roi_stats(out + "/stats.txt") if os.path.exists(out + "/stats.txt") else {}
    row = {"workload": name, "mode": mode, "repeat": rep, "path_pad": len(PADS[rep]) if isinstance(rep, int) else 0,
           "rc": rc, "checksum": ck.group(1) if ck else "", "exe_sha256": sha(exe)[:16],
           "simInsts": st.get("simInsts", "")}
    for k in STATS:
        row[k] = st.get("system.cpu." + k, st.get("system." + k, ""))
    # keep only the small files of a run (stats, config); the run has no trace
    return row

if __name__ == "__main__":
    jobs = [(w, m, r) for w in WORKS for r in range(len(PADS)) for m in MODES]
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(one, jobs))
    again = one((WORKS[0], "np", 0))
    rows.append(dict(again, repeat="0-again"))
    with open(f"{P}/runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(len(rows), "rows; failures:", [(r["workload"], r["mode"], r["repeat"]) for r in rows if r["rc"] != 0])
