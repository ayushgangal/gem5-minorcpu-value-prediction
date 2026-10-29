#!/usr/bin/env python3
import csv, os, statistics as S
from collections import defaultdict
P = os.path.dirname(os.path.abspath(__file__))
OLD = os.path.expanduser("~/gem5-validation-2026-10-23/vastra-stage2b-implementation/stage3-meta/perf/summary.csv")
rows = list(csv.DictReader(open(P + "/runs.csv")))
again = [r for r in rows if r["repeat"] == "0-again"]
rows = [r for r in rows if r["repeat"] != "0-again"]
num = lambda x: int(float(x)) if x not in ("", None) else 0
by = defaultdict(list)
order = []
for r in rows:
    k = (r["workload"], r["mode"])
    by[k].append(r)
    if r["workload"] not in order:
        order.append(r["workload"])
old = {(r["workload"], r["mode"]): r for r in csv.DictReader(open(OLD)) if r.get("roi_cycles_median", "").isdigit()}
modemap = {"np": "np", "lv": "lv", "va": "va"}
out = []
for wl in order:
    base = by[(wl, "np")]
    bc = [num(r["numCycles"]) for r in base]
    for mode in ("np", "lv", "va", "meta", "train", "cand"):
        rs = by[(wl, mode)]
        cyc = [num(r["numCycles"]) for r in rs]
        med = S.median(cyc)
        red = [100.0 * (b - c) / b for b, c in zip(bc, cyc)]
        row = {"workload": wl, "mode": mode, "runs": len(cyc), "roi_cycles_raw": " ".join(map(str, cyc)),
               "roi_cycles_median": med, "roi_cycles_min": min(cyc), "roi_cycles_max": max(cyc),
               "spread_percent": round(100.0 * (max(cyc) - min(cyc)) / med, 3),
               "cycle_reduction_percent_median": round(100.0 * (S.median(bc) - med) / S.median(bc), 2),
               "reduction_min": round(min(red), 2), "reduction_max": round(max(red), 2),
               "committed_insts": rs[0]["commitStats0.numInsts"],
               "insts_equal_to_np": all(r["commitStats0.numInsts"] == base[0]["commitStats0.numInsts"] for r in rs),
               "checksum": rs[0]["checksum"],
               "checksum_equal_to_np": all(r["checksum"] == base[0]["checksum"] for r in rs),
               "exe_sha256": rs[0]["exe_sha256"], "all_rc0": all(r["rc"] == "0" for r in rs)}
        for k in ("dcache.ReadReq.misses::total", "l2.overallMisses::total",
                  "lvp.confidentPredictions", "lvp.incorrect", "lvp.specLoadsCommitted",
                  "lvp.mispredictSquashes", "vastra.syntheticResponses", "vastra.fwdAdmitted",
                  "meta.consumersEvaluated", "meta.selVAstra", "meta.selLVP", "meta.selNone",
                  "meta.provisionalBases", "meta.provisionalValidated", "meta.provisionalDropped", "astra.baseCorrect", "astra.baseIncorrect", "astra.baseUnavailableLoads", "vastra.candidates", "meta.vastraPending", "meta.vastraFailed", "meta.vastraNoRecord",
                  "meta.lvpHeldForVAstra", "meta.vastraOverLvp", "meta.bothAdmissible"):
            row[k] = rs[0][k]
        # Stage 2d consistency (same executable, same mode, earlier binary)
        o = old.get((wl, mode))   # the Stage 3 results of the build without the experiment
        row["stage2d_cycles"] = o["roi_cycles_median"] if o else ""
        row["equals_stage2d"] = (str(int(med)) == o["roi_cycles_median"].split(".")[0]) if o else ""
        out.append(row)
fields = []
for r in out:
    for k in r:
        if k not in fields:
            fields.append(k)
with open(P + "/summary.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, restval="")
    w.writeheader(); w.writerows(out)
print("repeat of stable/np:", again[0]["numCycles"], "vs", by[("stable", "np")][0]["numCycles"])
print("%-11s %-5s %9s %9s %9s %7s %8s ins= ck= s2d= | meta: eval va lvp none pend over | fwdAdm" % ("workload", "mode", "median", "min", "max", "spread", "red%"))
for r in out:
    print("%-11s %-5s %9s %9s %9s %7s %8s %s %s %s | %s %s %s %s %s %s | %s" % (
        r["workload"], r["mode"], int(r["roi_cycles_median"]), r["roi_cycles_min"], r["roi_cycles_max"],
        r["spread_percent"], r["cycle_reduction_percent_median"], r["insts_equal_to_np"], r["checksum_equal_to_np"],
        r["equals_stage2d"], r["meta.consumersEvaluated"], r["meta.selVAstra"], r["meta.selLVP"], r["meta.selNone"],
        r["meta.vastraPending"], r["meta.vastraOverLvp"], r["vastra.fwdAdmitted"]))
