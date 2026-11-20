"""Headless-browser check of the Console against a RUNNING stack:  python3 tools/consolecheck.py --base http://127.0.0.1:8000 --user alpha-admin --password ... [--shots dir]
Signs in, visits every view, opens the palette, asks a question, creates and opens a public share link, and fails on any page error."""
import argparse
import sys
import time

from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000"), ap.add_argument("--user", required=True), ap.add_argument("--password", required=True)
    ap.add_argument("--shots")
    a = ap.parse_args()
    errs, res = [], []

    def check(name, ok, detail=""):
        res.append(ok)
        print(f"  [{'ok' if ok else 'FAIL'}] {name} {detail}")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1360, "height": 900})
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(a.base + "/console")
        pg.fill("#lu", a.user), pg.fill("#lp", a.password), pg.click("#lgo")
        pg.wait_for_selector("#app.on", timeout=8000)
        pg.wait_for_selector(".banner", timeout=8000)
        check("sign in + overview", "monitored" in pg.inner_text(".banner") or "Waiting" in pg.inner_text(".banner"))
        for r, h1 in (("incidents", "Incidents"), ("fleet", "Fleet"), ("ask", "Ask"), ("ops", "Operations"), ("settings", "Settings"), ("setup", "Connect a collector")):
            pg.goto(f"{a.base}/console#/{r}")
            time.sleep(1.2)
            check(f"view {r}", pg.inner_text("h1.pg") == h1)
            if a.shots:
                pg.screenshot(path=f"{a.shots}/{r}.png")
        pg.goto(a.base + "/console#/ask")
        time.sleep(0.8)
        pg.fill("input[aria-label=Question]", "What is wrong right now?")
        pg.keyboard.press("Enter")
        pg.wait_for_selector(".msg.a:not(.mu)", timeout=6000)
        check("ask answers", len(pg.inner_text(".msg.a")) > 10)
        pg.keyboard.press("Control+k")
        check("palette opens", pg.is_visible("#pm"))
        pg.keyboard.press("Escape")
        pg.goto(a.base + "/console#/settings")
        time.sleep(0.8)
        pg.click("text=Share links")
        time.sleep(0.6)
        pg.fill("input[aria-label=Label]", "consolecheck")
        pg.click("text=Create status link")
        pg.wait_for_selector("pre.code", timeout=5000)
        link = pg.inner_text("pre.code").strip()
        pub = b.new_page()
        pub.goto(link)
        time.sleep(1.5)
        txt = pub.inner_text("main")
        check("public status page renders", "Components" in txt.title() or "COMPONENTS" in txt, link.split("/s/")[0])
        check("public page leaks no user/ids", "alpha-admin" not in txt and "n-" not in txt.replace("on-", ""))
        pg.click("button:has-text('Revoke')")
        time.sleep(1)
        pub.reload()
        time.sleep(1)
        check("revoked link stops working", "unavailable" in pub.inner_text("main").lower())
        check("no page errors", not errs, str(errs[:3]))
        b.close()
    print(f"[consolecheck] {sum(res)}/{len(res)} passed")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())
