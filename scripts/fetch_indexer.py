"""Fetch all indexer records (bounties, claims, transactions) per chain -> out/raw/."""
import json
import sys
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
BASE = "https://indexer.poidh.xyz/api/v1"


def fetch_all(kind, cid):
    out, off = [], 0
    while True:
        for attempt in range(5):
            try:
                r = requests.get(f"{BASE}/{kind}?chainId={cid}&limit=100&offset={off}", headers=UA, timeout=60)
                page = r.json()
                break
            except Exception as e:
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
        if not page:
            break
        out.extend(page)
        off += 100
        if len(page) < 100:
            break
    return out


for cid in (1, 42161, 8453):
    for kind in ("bounties", "claims", "transactions"):
        rows = fetch_all(kind, cid)
        path = f"out/raw/indexer-{cid}-{kind}.json"
        json.dump(rows, open(path, "w"))
        print(f"chain {cid} {kind}: {len(rows)} -> {path}", flush=True)
