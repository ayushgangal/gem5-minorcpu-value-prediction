#!/usr/bin/env python3
"""Stage 2d, second experiment: sensitivity to the warm-up length and to the
length of the region of interest (same kernels, other WARM / ROI laps)."""
import csv, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_perf as rp
from concurrent.futures import ThreadPoolExecutor

P = rp.P
CC = ["riscv64-linux-gnu-gcc", "-O1", "-static", "-nostdlib", "-ffreestanding",
      "-march=rv64g", "-mabi=lp64d", "-Wl,-n", "-Wl,--no-relax-gp", "-Wl,-e,_start"]
VARS = [(w, warm, roi) for w in (1, 2, 3, 4) for (warm, roi) in
        [(0, 200), (5, 200), (20, 200), (100, 200), (100, 100), (100, 400),
         (100, 800)]]

def build(v):
    w, warm, roi = v
    d = f"{P}/bin/var-w{warm}-r{roi}"
    os.makedirs(d, exist_ok=True)
    exe = f"{d}/perf{w}"
    subprocess.run(CC + [f"-DWORK={w}", f"-DWARM={warm}", f"-DROI={roi}", "-o", exe,
                         f"{P}/src/perf.c"], check=True, stderr=subprocess.DEVNULL)
    return exe

def run(job):
    v, mode = job
    w, warm, roi = v
    exe = f"{P}/bin/var-w{warm}-r{roi}/perf{w}"
    out = f"{P}/runs-sens/W{w}/w{warm}-r{roi}/{mode}"
    import shutil
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    args = [rp.GEM5, "-d", out, rp.WP if mode == "va" else rp.BASE,
            "--cmd=" + exe] + rp.MODES[mode]
    with open(out + ".out", "w") as f:
        rc = subprocess.run(args, stdout=f, stderr=subprocess.STDOUT).returncode
    st = rp.roi_stats(out + "/stats.txt")
    row = {"workload": rp.WORKS[w], "warm": warm, "roi": roi, "mode": mode,
           "rc": rc, "numCycles": st.get("system.cpu.numCycles", ""),
           "simInsts": st.get("simInsts", "")}
    for k in ("lvp.specLoadsCommitted", "lvp.mispredictSquashes",
              "vastra.syntheticResponses", "vastra.fwdAdmitted"):
        row[k] = st.get("system.cpu." + k, "")
    return row

if __name__ == "__main__":
    for v in VARS:
        build(v)
    jobs = [(v, m) for v in VARS for m in rp.MODES]
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(run, jobs))
    with open(f"{P}/sensitivity.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(len(rows), "rows; failures:", [r for r in rows if r["rc"] != 0])
