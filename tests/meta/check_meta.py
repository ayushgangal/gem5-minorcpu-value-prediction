#!/usr/bin/env python3
"""Checks of META selection (run_meta.sh).

  directed OUT    meta.c kernels (and forward.c) under NO-PREDICTION (np),
                  LVP address speculation (lvp), V-ASTRA forwarding (va) and
                  META (meta), same binary: architectural equivalence, the
                  selection rule, one accepted source per consumer
  lifecycle OUT   other programs under np and meta: equivalence and lifecycle

The evidence is the trace (MinorExecute, MinorMem, VBypass, LVP, META): each
consumer's decision, the request it sent and when its producer committed.  A
statistic is never the only evidence.  Whole-run numCycles is information
only."""

import os
import re
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sou"))
import check_forward as cf  # noqa: E402
import check_release as cr  # noqa: E402

failures = 0


def check(cond, msg):
    global failures
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        failures += 1


def info(msg):
    print("INFO  " + msg)


R_DECIDE = re.compile(
    r"META decide exec: (\d+) pc: 0x([0-9a-f]+) producer: (\d+) "
    r"choice: (\w+) \(([^)]*)\)"
)
R_ACCEPT = re.compile(
    r"META accept exec: (\d+) pc: 0x([0-9a-f]+) source: (\w+) producer: "
    r"(\d+) value: 0x([0-9a-f]+)"
)
R_OUTCOME = re.compile(
    r"META outcome exec: (\d+) pc: 0x([0-9a-f]+) source: (\w+) outcome: (\w+)"
)
R_LVP_ACC = re.compile(r"Speculative load accepted inst: \S+/(\d+)\.\d+")
R_LVP_VAL = re.compile(
    r"Validated inst: \S+/(\d+)\.\d+ pc: 0x([0-9a-f]+).* exec: (\d+) "
    r"predicted: 0x([0-9a-f]+) actual: 0x([0-9a-f]+) \((\w+)\)"
)
R_LVP_REC = re.compile(r"Recovery redirect inst: \S+/(\d+)\.\d+")
R_DISCARD = re.compile(r"Discarding (?:mem )?inst: \S+/(\d+)\.\d+")
R_LINE = re.compile(r"^\s*(\d+): (\S+): (.*)$")
R_DECFULL = re.compile(
    r"VAstra decide exec: (\d+) pc: 0x[0-9a-f]+ result: (\w+) pred_base: "
    r"0x([0-9a-f]+) actual_base: 0x([0-9a-f]+)"
)


class M(cf.T):
    """The forwarding parser plus the META and LVP events"""

    def __init__(self, path):
        super().__init__(path)
        self.accept = {}  # consumer seq -> [(tick, source, producer)]
        self.outcome = {}  # consumer seq -> [(source, outcome)]
        self.lvp_acc = {}  # consumer seq -> ticks
        self.lvp_val = {}  # producer seq -> (tick, predicted, actual, ok)
        self.lvp_rec = []  # (tick, producer seq)
        self.dec = {}
        self.decfull = {}  # seq -> (result, pred_base, actual_base)
        self.accept_val = {}  # consumer seq -> source value of the accept
        self.discard = {}  # seq -> first tick of a "Discarding" line
        with open(path, errors="replace") as f:
            for line in f:
                if "VAstra decide" in line:
                    g = R_DECFULL.search(line)
                    if g:
                        self.decfull[int(g.group(1))] = (
                            g.group(2),
                            int(g.group(3), 16),
                            int(g.group(4), 16),
                        )
                    continue
                if "Discarding" in line:
                    m = R_LINE.match(line)
                    g = R_DISCARD.search(line)
                    if m and g:
                        self.discard.setdefault(
                            int(g.group(1)), int(m.group(1))
                        )
                    continue
                if (
                    "META " not in line
                    and "LVP" not in line
                    and "Speculative load" not in line
                    and "Validated inst" not in line
                    and "Recovery redirect" not in line
                ):
                    continue
                m = R_LINE.match(line)
                if not m:
                    continue
                tick, msg = int(m.group(1)), m.group(3)
                g = R_DECIDE.search(msg)
                if g:
                    self.dec.setdefault(int(g.group(1)), []).append(
                        (tick, int(g.group(3)), g.group(4), g.group(5))
                    )
                    continue
                g = R_ACCEPT.search(msg)
                if g:
                    self.accept.setdefault(int(g.group(1)), []).append(
                        (tick, g.group(3), int(g.group(4)))
                    )
                    self.accept_val[int(g.group(1))] = int(g.group(5), 16)
                    continue
                g = R_OUTCOME.search(msg)
                if g:
                    self.outcome.setdefault(int(g.group(1)), []).append(
                        (g.group(3), g.group(4))
                    )
                    continue
                g = R_LVP_ACC.search(msg)
                if g:
                    self.lvp_acc.setdefault(int(g.group(1)), []).append(tick)
                    continue
                g = R_LVP_VAL.search(msg)
                if g:
                    self.lvp_val[int(g.group(3))] = (
                        tick,
                        int(g.group(4), 16),
                        int(g.group(5), 16),
                        g.group(6) == "correct",
                    )
                    continue
                g = R_LVP_REC.search(msg)
                if g:
                    self.lvp_rec.append((tick, int(g.group(1))))

    def accepted_source(self, seq):
        return [s for _, s, _ in self.accept.get(seq, [])]


def stats_windows(path):
    return cf.windows(path)


def roi(path):
    """The first statistics block: the region of interest of meta.c"""
    w = stats_windows(path)
    return w[0] if w else {}


def sv(w, name):
    if name == "simInsts":
        return int(w.get(name, 0))
    return int(w.get("system.cpu." + name, 0))


def checksum(out_file):
    """The program's output values (checksum / errors lines), tolerant of the
    wrapper's and gem5's lines interleaved with them"""
    v = cr.program_values(out_file)
    return " ".join(v) if v else None


# ------------------------------------------------- recovery ordering (trace)


def recovery_problems(t):
    """The recovery guarantee of a wrong LVP prediction, from the trace.

    For every LVP producer P whose validation was incorrect and that had at
    least one consumer accepted with its value (META accept, source lvp):
      * every such consumer was accepted no later than P's validation (the
        consumer needs P outstanding), P's validation and the recovery
        redirect carry the same tick or the redirect is later (they are
        separate lines of one cycle: no fixed order is assumed), there is
        exactly one redirect for P;
      * the consumer never handled a response or committed (it has no
        'Memory response inst' / 'Committing inst' line) and it was
        discarded (a 'Discarding' line), whether or not it was bypassed.
    Conversely every redirect belongs to a producer that was validated
    incorrect and had such a consumer, and a correct prediction has none.
    Returns (problems, statistics)."""
    used = {}
    for c, a in t.accept.items():
        if a[0][1] == "lvp":
            used.setdefault(a[0][2], []).append((c, a[0][0]))
    redirects = {}
    for tick, p in t.lvp_rec:
        redirects.setdefault(p, []).append(tick)
    problems = []
    n = bypassed = strict = 0
    # a trace without the MinorExecute lines (the light trace of a very long
    # program) has no response or discard lines: those two checks are skipped
    has_exec = bool(t.inst)
    for p, (vt, pred, act, ok) in t.lvp_val.items():
        cons = used.get(p, [])
        rec = redirects.get(p, [])
        if ok:
            if rec:
                problems.append(("redirect for a correct prediction", p))
            continue
        if not cons:
            if rec:
                problems.append(("redirect without a consumer", p))
            continue
        n += 1
        if len(rec) != 1:
            problems.append(
                ("wrong used prediction: %d redirects" % len(rec), p)
            )
            continue
        if rec[0] < vt:
            problems.append(("redirect before the validation", p))
        for c, at in cons:
            e = t.inst.get(c, {})
            if at > vt:
                problems.append(("consumer accepted after the validation", c))
            if not has_exec:
                continue
            if "commit" in e or e.get("nresp", 0):
                problems.append(
                    ("consumer handled a response or committed", c)
                )
            if c not in t.discard:
                problems.append(("consumer never discarded", c))
            if c in t.bypass:
                bypassed += 1
                if (
                    t.bypass[c] <= vt <= rec[0]
                    and t.discard.get(c, -1) >= rec[0]
                ):
                    strict += 1
    for p in redirects:
        if p not in t.lvp_val:
            problems.append(("redirect for an unvalidated producer", p))
    return problems, {
        "wrong_used": n,
        "consumers_bypassed": bypassed,
        "strict_order": strict,
        "execute_trace": has_exec,
    }


def recovery_ordering(label, t):
    problems, st = recovery_problems(t)
    check(
        not problems,
        "%s: recovery ordering: %d wrong used predictions, each with one "
        "redirect, every consumer accepted before the validation, never "
        "handled or committed and discarded%s; %d bypassed consumers (%d in "
        "the strict order bypass <= validation <= redirect <= discard) "
        "(%d violations %s)"
        % (
            label,
            st["wrong_used"],
            ""
            if st["execute_trace"]
            else " (response/discard lines not in this "
            "light trace: not checked)",
            st["consumers_bypassed"],
            st["strict_order"],
            len(problems),
            problems[:2],
        ),
    )
    return st


# ---------------------------------------------------------------- invariants


def invariants(label, t, w=None):
    """Properties that hold for every META run, whatever the program"""
    # 1. at most one accepted source per consumer, and the accept events
    #    agree with the LVP and V-ASTRA lifecycle events of that consumer
    multi = [s for s, a in t.accept.items() if len(a) != 1]
    check(
        not multi,
        "%s: every consumer has at most one accepted source (%d "
        "accepted, %d violations)" % (label, len(t.accept), len(multi)),
    )
    lvp_acc = {s for s, a in t.accept.items() if a[0][1] == "lvp"}
    va_acc = {s for s, a in t.accept.items() if a[0][1] == "vastra"}
    check(
        lvp_acc == set(t.lvp_acc),
        "%s: the LVP consumers are exactly the loads LVP accepted (%d)"
        % (label, len(lvp_acc)),
    )
    fwd_adm = {
        s for s, evs in t.fwd.items() if any(n == "admit" for n, _, _ in evs)
    }
    check(
        va_acc == fwd_adm,
        "%s: the V-ASTRA consumers are exactly the forwarding admissions "
        "(%d)" % (label, len(va_acc)),
    )
    check(
        not (lvp_acc & va_acc),
        "%s: no consumer was served by both sources" % label,
    )
    # 2. every decision follows the rule
    bad = []
    for s, ds in t.dec.items():
        for tick, prod, choice, why in ds:
            rec = t.fwd.get(prod, [])
            names = [n for n, tk, _ in rec if tk <= tick]
            published = "publish" in names
            failed = "fail" in names
            created = "create" in names
            if choice == "vastra":
                ok = published and why == "vastra-validated"
            elif choice == "lvp":
                # V-ASTRA decided against (record failed) or never a
                # candidate; never while it is pending or validated
                ok = (
                    (not published)
                    and (failed or not created)
                    and why
                    in ("lvp-after-vastra-failed", "lvp-no-vastra-candidate")
                    and (why == "lvp-after-vastra-failed") == failed
                )
            else:
                ok = True
                if why.startswith("wait-vastra-pending"):
                    ok = created and not published and not failed
            if not ok:
                bad.append((s, tick, prod, choice, why, names))
    check(
        not bad,
        "%s: every META decision follows the precedence rule "
        "(V-ASTRA validated, else LVP when V-ASTRA is failed or absent, "
        "else none; nothing while V-ASTRA is pending) over %d decisions "
        "(%d violations %s)"
        % (label, sum(len(d) for d in t.dec.values()), len(bad), bad[:2]),
    )
    # 3. the consumer that was accepted was last decided in favour of that
    #    source in the same cycle
    bad = []
    for s, a in t.accept.items():
        tick, src, prod = a[0]
        ds = [d for d in t.dec.get(s, []) if d[0] == tick]
        if not ds or ds[-1][2] != src:
            bad.append((s, src, ds))
    check(
        not bad,
        "%s: each accepted consumer was decided for that source in "
        "the cycle of acceptance (%d violations)" % (label, len(bad)),
    )
    # 4. V-ASTRA: the request of a forwarded consumer is sent after the
    #    publication of its producer's value (never before)
    bad = []
    for s in va_acc:
        a = t.accept[s][0]
        pub = t.ev(a[2], "publish")
        if not pub or pub[0][0] > a[0]:
            bad.append(s)
    check(
        not bad,
        "%s: every V-ASTRA consumer was admitted after its "
        "producer's publication (%d violations)" % (label, len(bad)),
    )
    # 5. a V-ASTRA consumer never carries an LVP recovery: a recovery
    #    redirect names a producer, and every consumer that used that
    #    producer's prediction took the LVP source
    bad = []
    for tick, prod in t.lvp_rec:
        users = [
            s
            for s, a in t.accept.items()
            if a[0][1] == "lvp" and a[0][2] == prod
        ]
        vusers = [
            s
            for s, a in t.accept.items()
            if a[0][1] == "vastra" and a[0][2] == prod
        ]
        if not users or vusers:
            bad.append((prod, users, vusers))
    check(
        not bad,
        "%s: every LVP recovery redirect (%d) was caused by a "
        "prediction used by an LVP consumer, and no V-ASTRA consumer of "
        "that producer was involved (%d violations)"
        % (label, len(t.lvp_rec), len(bad)),
    )
    recovery_ordering(label, t)
    # 6. every evaluated consumer has exactly one outcome
    evald = set(t.dec)
    bad = [s for s in evald if len(t.outcome.get(s, [])) != 1]
    check(
        not bad,
        "%s: each of the %d evaluated consumers has exactly one "
        "outcome (%d violations)" % (label, len(evald), len(bad)),
    )
    bad = [
        s
        for s, o in t.outcome.items()
        if o[0][0] != (t.accepted_source(s) or ["none"])[0]
        and not (o[0][0] == "none" and not t.accept.get(s))
    ]
    check(
        not bad,
        "%s: each outcome names the source the consumer was "
        "accepted with (%d violations)" % (label, len(bad)),
    )
    # 7. counters agree with the trace
    if w is not None:
        n_va = sum(1 for o in t.outcome.values() if o[0][0] == "vastra")
        n_lvp = sum(1 for o in t.outcome.values() if o[0][0] == "lvp")
        n_none = sum(1 for o in t.outcome.values() if o[0][0] == "none")
        got = (
            sv(w, "meta.selVAstra"),
            sv(w, "meta.selLVP"),
            sv(w, "meta.selNone"),
        )
        info(
            "%s: meta counters (V-ASTRA, LVP, none) = %s, trace (whole "
            "run) = %s" % (label, got, (n_va, n_lvp, n_none))
        )


def window_identity(label, w):
    ev = sv(w, "meta.consumersEvaluated")
    carry = sv(w, "meta.consumersCarryIn")
    done = (
        sv(w, "meta.selVAstra") + sv(w, "meta.selLVP") + sv(w, "meta.selNone")
    )
    infl = sv(w, "meta.consumersInFlight")
    check(
        ev + carry == done + infl,
        "%s: evaluated %d + carry-in %d == resolved %d + in flight %d"
        % (label, ev, carry, done, infl),
    )
    out = (
        sv(w, "meta.vastraCommitted")
        + sv(w, "meta.vastraSquashed")
        + sv(w, "meta.vastraFaulted")
    )
    check(
        out == sv(w, "meta.selVAstra"),
        "%s: V-ASTRA consumers by outcome sum to the V-ASTRA count (%d)"
        % (label, out),
    )
    out = (
        sv(w, "meta.lvpCommitted")
        + sv(w, "meta.lvpSquashed")
        + sv(w, "meta.lvpFaulted")
    )
    check(
        out == sv(w, "meta.selLVP"),
        "%s: LVP consumers by outcome sum to the LVP count (%d)"
        % (label, out),
    )
    # the sources' own lifecycle counters count the same consumers
    check(
        sv(w, "lvp.specLoadsCommitted")
        + sv(w, "lvp.specLoadsSquashed")
        + sv(w, "lvp.specLoadsFaulted")
        == out
        or sv(w, "lvp.specLoadsIssued") + sv(w, "lvp.specCarryIn")
        == sv(w, "lvp.specLoadsCommitted")
        + sv(w, "lvp.specLoadsSquashed")
        + sv(w, "lvp.specLoadsFaulted")
        + sv(w, "lvp.specInFlight"),
        "%s: LVP speculative-load identity holds" % label,
    )
    check(
        sv(w, "vastra.fwdAdmitted") + sv(w, "vastra.fwdCarryIn")
        == sv(w, "vastra.fwdCommitted")
        + sv(w, "vastra.fwdSquashed")
        + sv(w, "vastra.fwdFaulted")
        + sv(w, "vastra.fwdInFlight"),
        "%s: V-ASTRA forwarding identity holds" % label,
    )


def trace_path(d, mode):
    p = os.path.join(d, mode, "trace.txt")
    return p if os.path.exists(p) else p + ".gz"


def load(d, mode):
    p = trace_path(d, mode)
    if p.endswith(".gz"):
        import gzip
        import tempfile

        with gzip.open(p, "rb") as f, tempfile.NamedTemporaryFile(
            "wb", delete=False
        ) as t:
            t.write(f.read())
        try:
            return M(t.name)
        finally:
            os.unlink(t.name)
    return M(p)


def rc(d, mode):
    return int(open(os.path.join(d, mode + ".rc")).read())


def equivalence(label, d, runs):
    """Every mode exits 0, prints the same output and commits the same
    instruction stream (instructions and values) as NO-PREDICTION"""
    check(
        all(rc(d, m) == 0 for m in runs),
        "%s: every mode exits 0 (%s)" % (label, {m: rc(d, m) for m in runs}),
    )
    ck = {m: checksum(os.path.join(d, m + ".out")) for m in runs}
    check(
        len(set(ck.values())) == 1 and ck["np"] is not None,
        "%s: identical output in every mode (%s)" % (label, ck["np"]),
    )
    ref = runs["np"].stream
    if ref:
        check(
            all(r.stream == ref for r in runs.values()),
            "%s: committed instruction stream and values identical to "
            "NO-PREDICTION in every mode (%d instructions)"
            % (label, len(ref)),
        )
    else:
        # a run without a per-instruction trace: the committed instruction
        # count of every statistics window instead
        tot = {
            m: [
                int(w.get("system.cpu.commitStats0.numInsts", 0))
                for w in cf.windows(os.path.join(d, m, "stats.txt"))
            ]
            for m in runs
        }
        check(
            tot["np"]
            and sum(tot["np"]) > 0
            and all(sum(v) == sum(tot["np"]) for v in tot.values()),
            "%s: committed instruction count identical in every mode "
            "(%d; no per-instruction trace for this program)"
            % (label, sum(tot["np"])),
        )
    n = {
        m: sv(roi(os.path.join(d, m, "stats.txt")), "numCycles") for m in runs
    }
    info("%s: ROI/whole-run numCycles (information only) %s" % (label, n))


def pcs(d):
    out = {}
    for line in open(os.path.join(d, "pcs.txt")):
        name, addr = line.split()
        out[name] = int(addr, 16)
    return out


def bound(label, cond, text):
    check(cond, "%s: %s" % (label, text))


def directed_one(d, k):
    k = int(k)
    label = "k%d" % k
    runs = {m: load(d, m) for m in ("np", "lvp", "va", "meta")}
    equivalence(label, d, runs)
    meta = runs["meta"]
    w = {m: roi(os.path.join(d, m, "stats.txt")) for m in runs}
    invariants(label + " META", meta, None)
    window_identity(label + " META ROI", w["meta"])
    for m in ("np", "lvp", "va"):
        check(
            sv(w[m], "meta.consumersEvaluated") == 0
            and not meta_events(runs[m]),
            "%s %s: no META event in a standalone mode" % (label, m),
        )
    check(
        sv(w["np"], "simInsts")
        == sv(w["meta"], "simInsts")
        == sv(w["lvp"], "simInsts")
        == sv(w["va"], "simInsts"),
        "%s: ROI committed instructions equal in every mode (%d)"
        % (label, sv(w["np"], "simInsts")),
    )
    wm = w["meta"]
    sel_va, sel_lvp, sel_none = (
        sv(wm, "meta.selVAstra"),
        sv(wm, "meta.selLVP"),
        sv(wm, "meta.selNone"),
    )
    info(
        "%s: META ROI selections V-ASTRA %d, LVP %d, none %d; LVP-only "
        "recoveries %d, META recoveries %d"
        % (
            label,
            sel_va,
            sel_lvp,
            sel_none,
            sv(w["lvp"], "lvp.mispredictSquashes"),
            sv(wm, "lvp.mispredictSquashes"),
        )
    )
    # V-ASTRA-only and META perform the same forwarding when LVP is idle
    if k == 1:
        bound(
            label,
            sv(wm, "lvp.confidentPredictions") >= 350
            and sv(wm, "vastra.syntheticResponses") >= 350
            and sel_lvp <= 5,
            "both predictors can predict the chain (LVP %d confident, "
            "V-ASTRA %d synthetic responses) and V-ASTRA wins: LVP "
            "served %d consumers (warm-up laps only)"
            % (
                sv(wm, "lvp.confidentPredictions"),
                sv(wm, "vastra.syntheticResponses"),
                sel_lvp,
            ),
        )
    elif k in (2, 4):
        bound(
            label,
            sel_va == 0
            and sel_lvp >= 250
            and sv(wm, "vastra.syntheticResponses") <= 10,
            "V-ASTRA falls back (V$ tag miss; %d synthetic responses) and "
            "LVP serves %d consumers"
            % (sv(wm, "vastra.syntheticResponses"), sel_lvp),
        )
        why = {x[3] for ds in meta.dec.values() for x in ds if x[2] == "lvp"}
        bound(
            label,
            why <= {"lvp-after-vastra-failed", "lvp-no-vastra-candidate"}
            and bool(why),
            "every LVP choice names its reason %s" % sorted(why),
        )
        bound(
            label,
            all(x[2] != "vastra" for ds in meta.dec.values() for x in ds),
            "no consumer was given to V-ASTRA",
        )
    if k in (3, 10):
        bound(
            label,
            sv(wm, "lvp.incorrect") >= 3
            and sv(wm, "lvp.mispredictSquashes") == 0,
            "LVP's independent prediction was wrong %d times, and no LVP "
            "recovery was raised (%d)"
            % (sv(wm, "lvp.incorrect"), sv(wm, "lvp.mispredictSquashes")),
        )
    if k == 3:
        bound(
            label,
            sv(w["lvp"], "lvp.mispredictSquashes") >= 3,
            "control: LVP-only recovered %d wrong predictions of the same "
            "program" % sv(w["lvp"], "lvp.mispredictSquashes"),
        )
    if k == 4:
        bound(
            label,
            sv(wm, "lvp.mispredictSquashes") >= 3
            and sv(wm, "lvp.mispredictSquashes")
            == sv(w["lvp"], "lvp.mispredictSquashes"),
            "LVP-selected consumers recover wrong predictions as in "
            "LVP-only: %d recoveries (META) vs %d (LVP-only)"
            % (
                sv(wm, "lvp.mispredictSquashes"),
                sv(w["lvp"], "lvp.mispredictSquashes"),
            ),
        )
        # every recovery redirect is in the META trace, names a producer
        # whose prediction was incorrect, and its consumer took the LVP path
        bound(
            label,
            len(meta.lvp_rec) == sv(wm, "lvp.mispredictSquashes")
            or len(meta.lvp_rec) >= 3,
            "recovery redirects in the trace: %d" % len(meta.lvp_rec),
        )
        bad = [
            p
            for _, p in meta.lvp_rec
            if p not in meta.lvp_val or meta.lvp_val[p][3]
        ]
        bound(
            label,
            not bad,
            "each recovery follows an incorrect validation "
            "(%d violations)" % len(bad),
        )
    if k == 5:
        bound(
            label,
            sel_va == 0 and sel_lvp == 0 and sel_none > 0,
            "no prediction is used: %d consumers evaluated, all none"
            % sel_none,
        )
    if k in (6, 9, 10):
        want = 70 if k == 6 else 170
        bound(
            label,
            sel_va >= want
            and sv(wm, "vastra.fwdAdmitted") == sel_va
            and sel_lvp == 0,
            "V-ASTRA serves %d consumers by forwarding (fwdAdmitted %d), "
            "LVP none" % (sel_va, sv(wm, "vastra.fwdAdmitted")),
        )
        # the consumer's request is in the LSQ before its producer commits
        early = tot = 0
        for s, a in meta.accept.items():
            if a[0][1] != "vastra":
                continue
            prod = a[0][2]
            c, p = meta.inst.get(s, {}), meta.inst.get(prod, {})
            if "init" in c and "commit" in p:
                # the request entered the LSQ (a bypassed consumer sends
                # nothing to memory, but it is still a request in the LSQ)
                tot += 1
                early += c["init"] < p["commit"]
        bound(
            label,
            tot > 0 and early == tot,
            "the request of every forwarded consumer (%d) entered the LSQ "
            "before its producer committed" % tot,
        )
    if k in (9, 10):
        bound(
            label,
            sv(wm, "meta.vastraOverLvp") >= 0.9 * sel_va,
            "V-ASTRA served %d consumers whose source LVP also predicted"
            % sv(wm, "meta.vastraOverLvp"),
        )
    if k == 10:
        wrong = [
            s
            for s, a in meta.accept.items()
            if a[0][1] == "vastra"
            and a[0][2] in meta.lvp_val
            and not meta.lvp_val[a[0][2]][3]
        ]
        bound(
            label,
            len(wrong) >= 3,
            "%d consumers were served by V-ASTRA while LVP's prediction for "
            "their producer was validated incorrect (no recovery)"
            % len(wrong),
        )
        bound(label, not meta.lvp_rec, "no LVP recovery in the META run")
    if k == 7:
        bound(
            label,
            sel_va >= 70 and sel_lvp >= 250,
            "both sources serve consumers in one program (V-ASTRA %d, LVP "
            "%d)" % (sel_va, sel_lvp),
        )
    return 0


def meta_events(t):
    return bool(t.accept or t.dec or t.outcome)


def directed_forward(d):
    runs = {m: load(d, m) for m in ("np", "lvp", "va", "meta")}
    equivalence("forward", d, runs)
    meta = runs["meta"]
    invariants("forward META", meta, None)
    w = {m: cf.windows(os.path.join(d, m, "stats.txt"))[0] for m in runs}
    window_identity("forward META", w["meta"])
    va, me = runs["va"], meta
    # the forwarding behaviour of V-ASTRA-only is that of META: the same
    # producers are published and failed, the same loads are admitted
    # (programs where LVP is never confident for these loads)
    pub = lambda t: sorted(
        s for s, e in t.fwd.items() if any(n == "publish" for n, _, _ in e)
    )
    adm = lambda t: sorted(
        s for s, e in t.fwd.items() if any(n == "admit" for n, _, _ in e)
    )
    check(
        len(pub(me)) > 0 and len(adm(me)) > 0,
        "forward META: values published (%d) and forwarded (%d)"
        % (len(pub(me)), len(adm(me))),
    )
    info(
        "forward: V-ASTRA-only published %d admitted %d; META published %d "
        "admitted %d LVP consumers %d"
        % (
            len(pub(va)),
            len(adm(va)),
            len(pub(me)),
            len(adm(me)),
            sum(1 for a in me.accept.values() if a[0][1] == "lvp"),
        )
    )
    # older-store conflict and abandoned candidates never publish
    rejected = [s for s, r in me.decide.items() if r == "storeconflict"]
    check(
        len(rejected) > 0
        and not any(
            s in me.fwd and any(n == "publish" for n, _, _ in me.fwd[s])
            for s in rejected
        ),
        "forward META: %d candidates rejected by an older store: none has a "
        "record that was published" % len(rejected),
    )
    aband = [
        s
        for s in me.fwd
        if any(n == "fail" and "abandoned" in r for n, _, r in me.fwd[s])
    ]
    check(
        len(aband) > 0
        and not any(
            any(n == "publish" for n, _, _ in me.fwd[s]) for s in aband
        )
        and not any(a[0][2] in aband for a in me.accept.values()),
        "forward META: %d abandoned candidates: never published, no "
        "consumer took their value" % len(aband),
    )
    failed_prod = [
        s for s in me.fwd if any(n == "fail" for n, _, _ in me.fwd[s])
    ]
    check(
        not any(
            a[0][2] in failed_prod and a[0][1] == "vastra"
            for a in me.accept.values()
        ),
        "forward META: no consumer took a value from any of the %d failed "
        "records" % len(failed_prod),
    )
    va_acc = {s for s, a in me.accept.items() if a[0][1] == "vastra"}
    chain = [s for s in va_acc if me.accept[s][0][2] in va_acc]
    check(
        len(chain) > 0,
        "forward META: %d forwarded loads took their value from another "
        "forwarded load (chain; producer identity %s)"
        % (
            len(chain),
            "ok" if all(me.accept[s][0][2] < s for s in chain) else "WRONG",
        ),
    )
    check(
        all(me.accept[s][0][2] < s for s in me.accept),
        "forward META: every consumer's producer is older than it",
    )
    outs = {
        k: sv(w["meta"], "meta." + k)
        for k in ("vastraCommitted", "vastraSquashed", "vastraFaulted")
    }
    check(
        outs["vastraSquashed"] > 0 and outs["vastraCommitted"] > 0,
        "forward META: V-ASTRA consumers committed and were squashed "
        "(wrong path, and by a producer's translation fault): %s" % outs,
    )
    pending = sv(w["meta"], "meta.vastraPending")
    failed = sv(w["meta"], "meta.vastraFailed")
    info(
        "forward META: consumers that found a pending record %d, failed "
        "record %d" % (pending, failed)
    )
    return 0


def lifecycle_one(d):
    label = os.path.basename(d.rstrip("/"))
    runs = {m: load(d, m) for m in ("np", "meta")}
    equivalence(label, d, runs)
    meta = runs["meta"]
    invariants(label + " META", meta, None)
    wins = cf.windows(os.path.join(d, "meta", "stats.txt"))
    check(len(wins) >= 1, "%s: %d statistics windows" % (label, len(wins)))
    for i, w in enumerate(wins):
        window_identity("%s META window %d" % (label, i), w)
    info(
        "%s: consumers evaluated %d (V-ASTRA %d, LVP %d, none %d); "
        "recoveries %d"
        % (
            label,
            sum(sv(w, "meta.consumersEvaluated") for w in wins),
            sum(sv(w, "meta.selVAstra") for w in wins),
            sum(sv(w, "meta.selLVP") for w in wins),
            sum(sv(w, "meta.selNone") for w in wins),
            sum(sv(w, "lvp.mispredictSquashes") for w in wins),
        )
    )
    return 0


def prov_identity(label, w):
    c = sv(w, "meta.provisionalBases")
    check(
        c + sv(w, "meta.provisionalCarryIn")
        == sv(w, "meta.provisionalValidated")
        + sv(w, "meta.provisionalDropped")
        + sv(w, "meta.provisionalInFlight"),
        "%s: provisional bases %d + carry-in %d == validated %d + dropped "
        "%d + in flight %d"
        % (
            label,
            c,
            sv(w, "meta.provisionalCarryIn"),
            sv(w, "meta.provisionalValidated"),
            sv(w, "meta.provisionalDropped"),
            sv(w, "meta.provisionalInFlight"),
        ),
    )


def astra_lvp_one(d):
    """metaAstraLvpLoads: off (the current META), train, candidate"""
    label = os.path.basename(d.rstrip("/"))
    modes = [
        m
        for m in ("np", "off", "train", "cand")
        if os.path.exists(os.path.join(d, m + ".rc"))
    ]
    runs = {m: load(d, m) for m in modes}
    equivalence(label, d, runs)
    tot = {}
    for m in modes:
        wins = cf.windows(os.path.join(d, m, "stats.txt"))
        keys = (
            "meta.provisionalBases",
            "meta.provisionalValidated",
            "meta.provisionalDropped",
            "lvp.mispredictSquashes",
            "astra.baseUnavailableLoads",
            "vastra.candidates",
            "vastra.syntheticResponses",
            "vastra.fwdAdmitted",
            "meta.selLVP",
            "meta.selVAstra",
        )
        tot[m] = {
            k: sum(int(w.get("system.cpu." + k, 0)) for w in wins)
            for k in keys
        }
        if m == "np":
            continue
        invariants("%s %s" % (label, m), runs[m], None)
        for i, w in enumerate(wins):
            window_identity("%s %s window %d" % (label, m, i), w)
            prov_identity("%s %s window %d" % (label, m, i), w)
    if label == "k12":
        # the forced misprediction: wrong used predictions in every mode;
        # only in candidate mode are the consumers V-ASTRA candidates that
        # were bypassed before the validation
        for m in ("off", "train", "cand"):
            _, st = recovery_problems(runs[m])
            check(
                st["wrong_used"] >= 3,
                "k12 %s: forced mispredictions occur (%d wrong used "
                "predictions, each recovered)" % (m, st["wrong_used"]),
            )
            if m == "cand":
                check(
                    st["consumers_bypassed"] >= 3
                    and st["strict_order"] == st["consumers_bypassed"],
                    "k12 cand: consumers bypassed with an unvalidated "
                    "operand (%d) all follow bypass <= validation <= "
                    "redirect <= discard (%d) and none committed"
                    % (st["consumers_bypassed"], st["strict_order"]),
                )
            else:
                check(
                    st["consumers_bypassed"] == 0,
                    "k12 %s: no consumer is bypassed (control)" % m,
                )
    check(
        tot["off"]["meta.provisionalBases"] == 0,
        "%s: off creates no provisional base (current META unchanged)" % label,
    )
    for m in ("train", "cand"):
        if m not in runs:
            continue
        t, t0, r = tot[m], tot["off"], runs[m]
        bases = t["meta.provisionalBases"]
        check(
            t["meta.provisionalValidated"] + t["meta.provisionalDropped"]
            == bases,
            "%s %s: %d provisional bases, %d validated at the load's "
            "response, %d dropped (squashed or faulted first)"
            % (
                label,
                m,
                bases,
                t["meta.provisionalValidated"],
                t["meta.provisionalDropped"],
            ),
        )
        # an LVP-served load never publishes a forwarding record
        lvp_seq = {s for s, a in r.accept.items() if a[0][1] == "lvp"}
        rec = [
            s
            for s in lvp_seq
            if any(n == "create" for n, _, _ in r.fwd.get(s, []))
        ]
        check(
            not rec,
            "%s %s: no LVP-served load publishes a V-ASTRA "
            "record (%d LVP loads, %d records)"
            % (label, m, len(lvp_seq), len(rec)),
        )
        cands = [
            s for s in lvp_seq if r.decfull.get(s, ("",))[0] == "candidate"
        ]
        if m == "train":
            check(
                not cands,
                "%s train: no LVP-served load is a V-ASTRA "
                "candidate (%d)" % (label, len(cands)),
            )
        else:
            check(
                all(
                    r.decfull[s][1] == r.decfull[s][2] == r.accept_val[s]
                    for s in cands
                ),
                "%s cand: every LVP-served V-ASTRA candidate has ASTRA's "
                "predicted base equal to the LVP operand it used (%d "
                "candidates)" % (label, len(cands)),
            )
        info(
            "%s %s: provisional %d, LVP loads %d, candidates among them %d, "
            "ASTRA bases unavailable %d (off %d), candidates %d (off %d), "
            "synthetic responses %d (off %d), recoveries %d (off %d)"
            % (
                label,
                m,
                bases,
                len(lvp_seq),
                len(cands),
                t["astra.baseUnavailableLoads"],
                t0["astra.baseUnavailableLoads"],
                t["vastra.candidates"],
                t0["vastra.candidates"],
                t["vastra.syntheticResponses"],
                t0["vastra.syntheticResponses"],
                t["lvp.mispredictSquashes"],
                t0["lvp.mispredictSquashes"],
            )
        )
    return 0


def selftest(path):
    """The recovery-ordering check against deliberately broken copies of a
    retained trace: the original must pass, each broken copy must fail.  The
    copies are temporary files; nothing retained is modified."""
    import gzip
    import shutil
    import tempfile

    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", errors="replace") as f:
        lines = f.readlines()
    tmp = tempfile.mkdtemp(prefix="meta-selftest-")

    def parse(ls):
        p = os.path.join(tmp, "t.txt")
        with open(p, "w") as f:
            f.writelines(ls)
        return M(p)

    base = parse(lines)
    problems, st = recovery_problems(base)
    check(
        not problems and st["wrong_used"] > 0 and st["consumers_bypassed"] > 0,
        "selftest: the original trace passes and has wrong used predictions "
        "with bypassed consumers (%s, %d problems)" % (st, len(problems)),
    )
    used = {}
    for c, a in base.accept.items():
        if a[0][1] == "lvp":
            used.setdefault(a[0][2], []).append(c)
    target = next(
        (
            (p, cs)
            for p, cs in used.items()
            if p in base.lvp_val
            and not base.lvp_val[p][3]
            and any(c in base.bypass for c in cs)
        ),
        None,
    )
    check(
        target is not None,
        "selftest: a wrong used prediction with a " "bypassed consumer exists",
    )
    if target is None:
        shutil.rmtree(tmp)
        return
    p, cs = target
    c = next(c for c in cs if c in base.bypass)
    vt = base.lvp_val[p][0]
    tag = "/%d." % c

    def drop(pred):
        return [l for l in lines if not pred(l)]

    def retick(pred, tick):
        out = []
        for l in lines:
            if pred(l):
                l = re.sub(r"^\s*\d+:", "%d:" % tick, l, count=1)
            out.append(l)
        return out

    is_redirect = lambda l: ("Recovery redirect" in l and "/%d." % p in l)
    is_discard = lambda l: ("Discarding" in l and tag in l)
    is_accept = lambda l: ("META accept exec: %d " % c) in l
    cases = {
        "no recovery redirect": drop(is_redirect),
        "consumer response handled instead of discarded": [
            l.replace("Discarding mem inst:", "Memory response inst:")
            if is_discard(l)
            else l
            for l in lines
        ],
        "consumer never discarded": drop(is_discard),
        "consumer accepted after the validation": retick(is_accept, vt + 5000),
        "redirect before the validation": retick(
            is_redirect, max(vt - 5000, 0)
        ),
        "redirect for a producer that was never validated": lines
        + [
            "%d: system.cpu.execute: Recovery redirect inst: 0/1.1/1/%d.%d "
            "pc: 0x0 (ld) exec: %d next PC: 0\n"
            % (vt, 999999999, 999999999, 999999999)
        ],
    }
    for name, ls in cases.items():
        pr, _ = recovery_problems(parse(ls))
        check(
            len(pr) > 0,
            "selftest: the check detects: %s (%d problems, "
            "e.g. %s)" % (name, len(pr), pr[:1]),
        )
    shutil.rmtree(tmp)


def align_one(d):
    """Kernel 13 with check_alignment (run_meta.sh align): an early LVP-served
    load faults in initiateAcc (misaligned predicted address, no request in
    the LSQ) and is executed again at the head with its real, aligned
    operand.  No mode may take an architectural fault, panic or change the
    result; a provisional ASTRA base left by the faulting attempt is dropped,
    never trained, never published, never used for a bypass."""
    import gzip

    label = "align"
    runs = {m: load(d, m) for m in ("np", "off", "train", "cand")}
    equivalence(label, d, runs)
    pc_c = pcs(d)["k_C"]
    for m in runs:
        p = trace_path(d, m)
        opener = gzip.open if p.endswith(".gz") else open
        early = arch = 0
        early_seq = set()
        trained = []  # (seq, base) of ASTRA updates of C
        prov = {"created": 0, "dropped": 0, "validated": 0}
        last_init = None
        with opener(p, "rt", errors="replace") as f:
            for line in f:
                g = re.search(
                    r"Initiating memRef inst: \S+/(\d+)\.\d+ pc: "
                    r"0x([0-9a-f]+)",
                    line,
                )
                if g:
                    last_init = (int(g.group(1)), int(g.group(2), 16))
                    continue
                if "Fault in early executing inst" in line:
                    early += 1
                    if last_init and last_init[1] == pc_c:
                        early_seq.add(last_init[0])
                    continue
                if "Fault in execute:" in line:
                    arch += 1
                    continue
                if "ASTRA base (provisional, LVP operand)" in line:
                    prov["created"] += 1
                    continue
                if "ASTRA base (provisional) dropped" in line:
                    prov["dropped"] += 1
                    continue
                if "ASTRA base validated" in line:
                    prov["validated"] += 1
                    continue
                g = re.search(
                    r"ASTRA update tid: \d+ exec: (\d+) pc: "
                    r"0x([0-9a-f]+) base: 0x([0-9a-f]+)",
                    line,
                )
                if g and int(g.group(2), 16) == pc_c:
                    trained.append((int(g.group(1)), int(g.group(3), 16)))
        check(arch == 0, "align %s: no architectural fault (%d)" % (m, arch))
        if m == "np":
            check(early == 0, "align np: no early fault (control: %d)" % early)
            continue
        check(
            len(early_seq) > 0 and early == len(early_seq),
            "align %s: the early faults (%d) are all C's, on %d instances "
            "that were then executed at the head" % (m, early, len(early_seq)),
        )
        t = runs[m]
        # every C instance that faulted early later committed (it handled
        # its response) and was never served by a forwarding record
        bad = [
            s
            for s in early_seq
            if "commit" not in t.inst.get(s, {})
            or any(n == "create" for n, _, _ in t.fwd.get(s, []))
        ]
        check(
            not bad,
            "align %s: each early-faulting C committed at the "
            "head and published no forwarding record (%d violations)"
            % (m, len(bad)),
        )
        mis = [b for _, b in trained if b % 8]
        check(
            not mis,
            "align %s: ASTRA never trained C on a misaligned "
            "(provisional) base: %d updates of C, %d misaligned"
            % (m, len(trained), len(mis)),
        )
        byp = [s for s in t.bypass if t.inst.get(s, {}).get("pc") == pc_c]
        check(
            not [s for s in byp if s in early_seq],
            "align %s: no early-faulting C was bypassed (%d bypasses of C "
            "overall)" % (m, len(byp)),
        )
        wins = cf.windows(os.path.join(d, m, "stats.txt"))
        for i, w in enumerate(wins):
            prov_identity("align %s window %d" % (m, i), w)
            window_identity("align %s window %d" % (m, i), w)
        # whole run, from the trace (the statistics windows are the ROI and
        # the cumulative end of run, so they cannot simply be added)
        if m == "off":
            check(
                prov == {"created": 0, "dropped": 0, "validated": 0},
                "align off: no provisional base (%s)" % prov,
            )
        else:
            check(
                prov["dropped"] == len(early_seq)
                and prov["created"] == prov["dropped"] + prov["validated"],
                "align %s: the provisional base of every early-faulting "
                "attempt was dropped at its re-execution (%s, %d early "
                "faults)" % (m, prov, len(early_seq)),
            )
        invariants("align " + m, t, None)


def main(argv):
    if len(argv) >= 3 and argv[1] == "align-one":
        align_one(argv[2])
    elif len(argv) >= 3 and argv[1] == "selftest":
        selftest(argv[2])
    elif len(argv) >= 3 and argv[1] == "astra-lvp-one":
        astra_lvp_one(argv[2])
    elif len(argv) >= 3 and argv[1] == "lifecycle-one":
        lifecycle_one(argv[2])
    elif len(argv) >= 3 and argv[1] == "directed-one":
        directed_one(argv[2], argv[3])
    elif len(argv) >= 3 and argv[1] == "directed-forward":
        directed_forward(argv[2])
    else:
        print(
            "usage: check_meta.py directed-one DIR K | directed-forward DIR",
            file=sys.stderr,
        )
        return 2
    print("%s: %d failure(s)" % (argv[1], failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
