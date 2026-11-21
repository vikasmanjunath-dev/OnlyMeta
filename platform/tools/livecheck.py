"""Realtime proof against a RUNNING stack (collector must use SOURCES=calm):
  python3 tools/livecheck.py --user alpha-admin --password ... [--base http://127.0.0.1:8000] [--collector http://127.0.0.1:8001]
Measures, in a real browser and without any reload: (1) live metric ticks, (2) fault -> Disrupted banner, (3) fault -> incident toast."""
import argparse
import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000"), ap.add_argument("--collector", default="http://127.0.0.1:8001")
    ap.add_argument("--user", required=True), ap.add_argument("--password", required=True), ap.add_argument("--node", default="db-01")
    ap.add_argument("--max", type=float, default=90)
    a = ap.parse_args()
    res, errs = [], []

    def check(name, ok, detail=""):
        res.append(ok)
        print(f"  [{'ok' if ok else 'FAIL'}] {name} {detail}")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1360, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(a.base + "/console")
        pg.fill("#lu", a.user), pg.fill("#lp", a.password), pg.click("#lgo")
        pg.wait_for_selector("#app.on")
        pg.goto(a.base + "/console#/fleet")
        pg.wait_for_selector(".node[data-node] [data-k=cpu] b", timeout=8000)
        pg.evaluate("window.__same=1")
        snap = lambda: pg.evaluate("[...document.querySelectorAll('.node [data-k]')].map(e=>e.textContent).join('|')")
        before, t0, ticked = snap(), time.time(), None
        while time.time() - t0 < 20:
            time.sleep(0.25)
            if snap() != before:
                ticked = time.time() - t0
                break
        check("metric values tick live, no reload", ticked is not None and pg.evaluate("window.__same===1"), f"{ticked:.1f}s" if ticked else "no change in 20s")
        pg.goto(a.base + "/console#/overview")
        pg.wait_for_selector(".banner")
        pg.evaluate("window.__same=1")
        req = urllib.request.Request(f"{a.collector}/api/chaos/scenario/fault?node={a.node}", method="POST", headers={"X-Chaos": "1", "Origin": a.base})
        t_inj = time.time()
        urllib.request.urlopen(req, timeout=10).read()
        t_poor = t_toast = None
        while time.time() - t_inj < a.max and (t_poor is None or t_toast is None):
            time.sleep(0.2)
            if t_poor is None and pg.inner_text("#ov").strip() == "POOR":
                t_poor = time.time() - t_inj
            if t_toast is None and pg.locator("#toasts .toast").count():
                t_toast = time.time() - t_inj
        check("fault -> Disrupted banner (no reload)", t_poor is not None and pg.evaluate("window.__same===1"), f"{t_poor:.1f}s" if t_poor else "timeout")
        check("fault -> toast notification", t_toast is not None, f"{t_toast:.1f}s" if t_toast else "timeout")
        pg.wait_for_selector(".att:has(.tk)", timeout=8000)
        check("attention list shows the open incident", "open" in pg.inner_text(".att:has(.tk)"))
        pg.evaluate("(()=>{const e=document.querySelector('.att .tk');e.dataset.s=0;e.dataset.t=Date.now()-5000})()")
        time.sleep(1.6)
        txt = pg.inner_text(".att .tk >> nth=0")
        check("incident timer counts up by itself", txt in ("6s", "7s"), txt)
        check("no page errors", not errs, str(errs[:2]))
        b.close()
    print(f"[livecheck] {sum(res)}/{len(res)} passed")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
