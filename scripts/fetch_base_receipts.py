"""Base v3 receipts, hardened: short timeouts, endpoint rotation, checkpointing.

Reads out/raw/base-bounty-classification.json (written by fetch_base.py) for the
v3 bounty set, fetches receipts for every indexer transaction touching a v3
bounty, checkpoints to out/raw/base-v3-receipts.partial.json, and finally writes
out/raw/base-v3-receipts.json in the {tx: {meta, receipt}} shape build_dataset.py
expects. Safe to re-run: resumes from the checkpoint.
"""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
      "Content-Type": "application/json"}
EPS = ["https://base.drpc.org", "https://base.gateway.tenderly.co", "https://8453.rpc.thirdweb.com"]
_local = threading.local()


def session(i):
    if not hasattr(_local, "ss"):
        _local.ss = [requests.Session() for _ in EPS]
        for s in _local.ss:
            s.headers.update(UA)
    return _local.ss[i % len(EPS)]


def fetch_receipt(txh, i):
    last = None
    for k in range(len(EPS)):
        try:
            r = session(i + k).post(EPS[(i + k) % len(EPS)],
                                    json={"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt",
                                          "params": [txh]}, timeout=25)
            j = r.json()
            if "error" in j:
                last = RuntimeError(str(j["error"])[:120])
                continue
            if j["result"] is None:
                last = RuntimeError("null receipt")
                continue
            return j["result"]
        except Exception as e:
            last = e
    raise RuntimeError(f"{txh}: {last}")


cls = json.load(open("out/raw/base-bounty-classification.json"))
v3_ids = {int(k) for k, v in cls.items() if v["gen"] == "v3"}
txs = json.load(open("out/raw/indexer-8453-transactions.json"))
v3_txs = [t for t in txs if t["bountyId"] in v3_ids]
by_hash = {}
for t in v3_txs:
    by_hash.setdefault(t["tx"], t)
print(f"v3 bounties: {len(v3_ids)}; unique txs to fetch: {len(by_hash)}", flush=True)

partial_path = "out/raw/base-v3-receipts.partial.json"
receipts = {}
if os.path.exists(partial_path):
    receipts = json.load(open(partial_path))
    print(f"resuming: {len(receipts)} receipts checkpointed", flush=True)
todo = [(h, m) for h, m in by_hash.items() if h not in receipts]
print(f"remaining: {len(todo)}", flush=True)

lock = threading.Lock()
state = {"done": 0, "failed": []}


def work(p):
    txh, meta, i = p
    try:
        rec = fetch_receipt(txh, i)
        with lock:
            receipts[txh] = {"meta": meta, "receipt": rec}
            state["done"] += 1
            if state["done"] % 500 == 0:
                json.dump(receipts, open(partial_path, "w"))
                print(f"  {state['done']}/{len(todo)} checkpointed", flush=True)
    except Exception as e:
        with lock:
            state["failed"].append((txh, meta, str(e)[:100]))


with ThreadPoolExecutor(max_workers=16) as ex:
    list(ex.map(work, [(h, m, i) for i, (h, m) in enumerate(todo)]))
json.dump(receipts, open(partial_path, "w"))
print(f"phase 1 done: {len(receipts)} receipts, {len(state['failed'])} failed", flush=True)

# serial-ish retry of failures with patience
still = []
for txh, meta, err in state["failed"]:
    got = None
    for attempt in range(5):
        try:
            got = fetch_receipt(txh, attempt)
            break
        except Exception:
            time.sleep(2 * (attempt + 1))
    if got is not None:
        receipts[txh] = {"meta": meta, "receipt": got}
    else:
        still.append(txh)
json.dump(receipts, open(partial_path, "w"))
if still:
    print(f"STILL FAILING ({len(still)}): {still[:10]}", flush=True)
    raise SystemExit(f"{len(still)} receipts unrecoverable")

json.dump(receipts, open("out/raw/base-v3-receipts.json", "w"))
os.remove(partial_path)
print(f"saved {len(receipts)} receipts -> out/raw/base-v3-receipts.json", flush=True)
