"""Compare what the collector sent with what the SaaS stored: missing, duplicates, hash mismatches.
  python3 tools/verify_delivery.py --collector-db data/collector_alpha.db --saas-url http://localhost:8000 --tenant tenant-alpha
  python3 tools/verify_delivery.py --collector-db ... --saas-db data/mock_saas.db --tenant tenant-alpha
Exit code 0 only when missing = 0, duplicates = 0 and hash mismatches = 0."""
import argparse
import json
import sqlite3
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from contracts.hashing import canonical_hash  # noqa: E402


def collector_rows(db_path):
    c = sqlite3.connect(db_path)
    rows = c.execute("SELECT payload_id, sha256 FROM egress WHERE status IN ('SENT','QUEUED') ").fetchall()
    return {a: b for a, b in rows}, [a for (a,) in c.execute("SELECT payload_id FROM egress WHERE status='SENT'")]


def saas_rows(a):
    if a.saas_db:
        c = sqlite3.connect(a.saas_db)
        return [(p, s) for p, s in c.execute("SELECT payload_id, sha256 FROM events WHERE tenant_id=?", (a.tenant,))]
    key = a.key or f"dev-key-{a.tenant.split('-')[-1]}"
    from contracts.signing import sign                         # signed like the collector; the key itself is never sent
    req = urllib.request.Request(f"{a.saas_url}/api/ids", headers=sign(key, "GET", "/api/ids"))
    with urllib.request.urlopen(req, timeout=10) as r:
        return [(x["payload_id"], x["sha256"]) for x in json.loads(r.read())]


def verify(sent: dict, sent_ids: list, saas: list):
    got = Counter(p for p, _ in saas)
    got_hash = {p: h for p, h in saas}
    missing = [p for p in sent_ids if p not in got]
    dups = [p for p, n in got.items() if n > 1]
    mism = [p for p in sent_ids if p in got_hash and got_hash[p] != sent[p]]
    return missing, dups, mism


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collector-db", required=True)
    ap.add_argument("--saas-url", default="http://localhost:8000")
    ap.add_argument("--saas-db")
    ap.add_argument("--tenant", default="tenant-alpha")
    ap.add_argument("--key", help="collector key for /api/ids (default dev-key-<tenant>)")
    ap.add_argument("--export", help="write [{payload_id, sha256}] of everything SENT, for the tracker's Reconcile box")
    a = ap.parse_args()
    sent, sent_ids = collector_rows(a.collector_db)
    if a.export:
        Path(a.export).write_text(json.dumps([{"payload_id": i, "sha256": sent[i]} for i in sent_ids]))
        print(f"exported {len(sent_ids)} sent ids to {a.export}")
    saas = saas_rows(a)
    missing, dups, mism = verify(sent, sent_ids, saas)
    print(f"collector SENT: {len(sent_ids)}   saas received: {len(saas)}")
    print(f"missing: {len(missing)}   duplicates: {len(dups)}   hash mismatches: {len(mism)}")
    for name, l in (("missing", missing), ("duplicate", dups), ("mismatch", mism)):
        for p in l[:10]:
            print(f"  {name}: {p}")
    sys.exit(0 if not (missing or dups or mism) else 1)
