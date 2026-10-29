#!/usr/bin/env python3
import csv, os, statistics as S
from collections import defaultdict
P = os.path.dirname(os.path.abspath(__file__))
rows = [r for r in csv.DictReader(open(P + "/runs.csv")) if r["repeat"] != "0-again"]
def num(x):
    return int(float(x)) if x not in ("", None) else 0
by = defaultdict(list)
for r in rows:
    by[(r["workload"], r["mode"])].append(r)
out = []
for wl in ("stable", "randbase", "altvalue", "vcmiss"):
    base = by[(wl, "np")]
    bc = [num(r["numCycles"]) for r in base]
    for mode in ("np", "lv", "va"):
        rs = by[(wl, mode)]
        cyc = [num(r["numCycles"]) for r in rs]
        med = S.median(cyc)
        red = [100.0 * (b - c) / b for b, c in zip(bc, cyc)]
        row = {
            "workload": wl, "mode": mode, "runs": len(cyc),
            "roi_cycles_median": med, "roi_cycles_min": min(cyc),
            "roi_cycles_max": max(cyc),
            "spread_percent": round(100.0 * (max(cyc) - min(cyc)) / med, 3),
            "cycles_per_lap": round(med / 200, 2),
            "cycle_reduction_percent_median": round(100.0 * (S.median(bc) - med) / S.median(bc), 2),
            "reduction_min_over_repeats": round(min(red), 2),
            "reduction_max_over_repeats": round(max(red), 2),
            "simInsts": rs[0]["simInsts"],
            "insts_equal_to_np": all(r["simInsts"] == base[0]["simInsts"] for r in rs),
            "checksum": rs[0]["checksum"],
            "checksum_equal_to_np": all(r["checksum"] == base[0]["checksum"] for r in rs),
            "exe_sha256": rs[0]["exe_sha256"],
        }
        for k in ("dcache.ReadReq.hits::total", "dcache.ReadReq.misses::total",
                  "l2.overallMisses::total", "lvp.confidentPredictions", "lvp.correct",
                  "lvp.incorrect", "lvp.specLoadsIssued", "lvp.specLoadsCommitted",
                  "lvp.mispredictSquashes", "vastra.candidates", "vastra.syntheticResponses",
                  "vastra.fwdPublished", "vastra.fwdAdmitted", "vastra.baseWrong",
                  "vastra.fbTagMiss"):
            row[k] = rs[0][k]
        out.append(row)
for wl in ("stable", "randbase", "altvalue", "vcmiss"):
    out.append({"workload": wl, "mode": "hybrid", "runs": 0,
                "roi_cycles_median": "unavailable (META not implemented)"})
fields = []
for r in out:
    for k in r:
        if k not in fields:
            fields.append(k)
with open(P + "/summary.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, restval="")
    w.writeheader()
    w.writerows(out)
for r in out[:-4]:
    print(r["workload"], r["mode"], r["roi_cycles_median"], r["roi_cycles_min"], r["roi_cycles_max"],
          "red%", r["cycle_reduction_percent_median"], "insts==", r["insts_equal_to_np"], "ck==", r["checksum_equal_to_np"],
          "| lvp conf", r["lvp.confidentPredictions"], "corr", r["lvp.correct"], "inc", r["lvp.incorrect"], "spec", r["lvp.specLoadsCommitted"], "sq", r["lvp.mispredictSquashes"],
          "| va cand", r["vastra.candidates"], "syn", r["vastra.syntheticResponses"], "fwd", r["vastra.fwdAdmitted"], "bw", r["vastra.baseWrong"], "rmiss", r["dcache.ReadReq.misses::total"], "l2m", r["l2.overallMisses::total"])
