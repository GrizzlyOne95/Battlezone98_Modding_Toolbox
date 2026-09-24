"""Build the worlds in parallel -- one process each, because the BC1 encode is
the whole cost and it is single-threaded numpy.

Worker count is an argument and deliberately low by default. Seven encoders
saturating memory bandwidth for half an hour is the shape of load this host hard
locks under, and a lock costs far more than the extra wall time: two workers at
below-normal priority leaves the machine usable and still finishes overnight-free.
"""
import json, os, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)


def one(args):
    mat, out_root = args
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    import build2
    from worlds2 import WORLDS
    req = json.load(open(os.path.join(HERE, "required.json")))
    t0 = time.time()
    rep = build2.build(mat, WORLDS[mat], os.path.join(out_root, mat),
                       req.get(mat, []), quiet=True)
    rep["seconds"] = round(time.time() - t0, 1)
    return mat, rep


if __name__ == "__main__":
    out_root = sys.argv[1]
    workers = int(os.environ.get("CC2_WORKERS", "2"))
    only = sys.argv[2:]
    from worlds2 import WORLDS
    mats = [m for m in WORLDS if not only or m in only]
    os.makedirs(out_root, exist_ok=True)
    # Resume: a world that already wrote its build_report.json is complete, so a
    # run interrupted by a host lock picks up where it stopped instead of
    # re-encoding hours of finished atlases.
    done, todo = {}, []
    for m in mats:
        rp = os.path.join(out_root, m, "build_report.json")
        if os.path.exists(rp):
            done[m] = json.load(open(rp))
        else:
            todo.append(m)
    mats = todo
    print("building %d worlds with %d workers: %s" % (len(mats), workers, ", ".join(mats)),
          flush=True)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, (m, out_root)) for m in mats]
        for f in as_completed(futs):
            mat, rep = f.result()
            done[mat] = rep
            tot = sum(rep["atlas_" + c]["bytes"] for c in "DNSE") / 1048576
            print("%-24s %5d^2 grid %d  %3d/%3d cells  %6.1f MB  %5.0f s"
                  % (mat, rep["atlas_px"], rep["grid"], rep["tiles"], rep["cells"],
                     tot, rep["seconds"]), flush=True)
    json.dump(done, open(os.path.join(out_root, "all_reports.json"), "w"), indent=1)
    print("TOTAL %.1f MB across %d worlds"
          % (sum(sum(r["atlas_" + c]["bytes"] for c in "DNSE") for r in done.values()) / 1048576,
             len(done)))
