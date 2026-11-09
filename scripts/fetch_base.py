"""Base (8453) v3 data via transaction receipts.

Why: no free RPC offers wide-range archive eth_getLogs on Base (publicnode needs a
token, drpc caps ~100 blocks, tenderly/thirdweb cap 1000). Receipts, however, are
served by ordinary full nodes. The poidh indexer enumerates every protocol
transaction; we fetch the receipt of every transaction that touches a v3 bounty
and decode the v3 events straight from the logs. Completeness is then *proven* by
the per-bounty reconciliation in build_dataset.py (net contributions must equal
the ClaimAccepted gross for every completed bounty) and by matching the on-chain
bountyCounter at the snapshot block.

Classification trap handled here: the indexer merges PoidhV2 (0xb502c585...) and
PoidhV3 (0x5555fa78...) bounties into one id sequence, interleaved by time after
the v3 launch (2026-01). Every bounty created at/after 2026-01-10 is classified
by the emitter address in its creation receipt.
"""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "scripts")
from common import Rpc, CORE

CID = 8453
V3 = CORE[CID].lower()
CLASSIFY_AFTER = 1768000000  # 2026-01-10; v3 launched 2026-01-22 on Base
EPS = ["https://base.drpc.org", "https://base.gateway.tenderly.co", "https://8453.rpc.thirdweb.com"]
_local = threading.local()


def rpc_for(i):
    if not hasattr(_local, "rpcs"):
        _local.rpcs = [Rpc(u, max_retries=3) for u in EPS]
    return _local.rpcs[i % len(EPS)]


def get_receipt(txh, i):
    last = None
    for k in range(len(EPS)):
        try:
            return rpc_for(i + k).receipt(txh)
        except Exception as e:
            last = e
    raise RuntimeError(f"receipt {txh} failed everywhere: {last}")


bounties = json.load(open("out/raw/indexer-8453-bounties.json"))
txs = json.load(open("out/raw/indexer-8453-transactions.json"))
created_tx = {}
for t in txs:
    if t["action"] == "bounty created":
        created_tx.setdefault(t["bountyId"], t)

todo = [b for b in bounties if b["createdAt"] >= CLASSIFY_AFTER and b["id"] in created_tx]
print(f"classifying {len(todo)} base bounties created >= {CLASSIFY_AFTER}", flush=True)


def classify(b, i):
    rec = get_receipt(created_tx[b["id"]]["tx"], i)
    emitters = {l["address"].lower() for l in rec["logs"]}
    gen = "v3" if V3 in emitters else ("v2" if emitters else "unknown")
    return b["id"], {"indexer_id": b["id"], "on_chain_id": b["onChainId"], "gen": gen,
                     "created_at": b["createdAt"], "creation_tx": created_tx[b["id"]]["tx"],
                     "creation_block": int(rec["blockNumber"], 16)}


classification = {}
with ThreadPoolExecutor(max_workers=12) as ex:
    for n, (bid, info) in enumerate(ex.map(lambda p: classify(*p), [(b, i) for i, b in enumerate(todo)])):
        classification[bid] = info
        if n % 200 == 0:
            print(f"  classified {n}/{len(todo)}", flush=True)

v3_ids = {bid for bid, v in classification.items() if v["gen"] == "v3"}
json.dump(classification, open("out/raw/base-bounty-classification.json", "w"), indent=1)
print(f"v3 bounties identified: {len(v3_ids)} (of {len(todo)} classified)", flush=True)

# Fetch receipts for EVERY indexer transaction touching a v3 bounty.
v3_txs = [t for t in txs if t["bountyId"] in v3_ids]
print(f"fetching {len(v3_txs)} receipts for v3 bounty transactions", flush=True)


def fetch(t, i):
    rec = get_receipt(t["tx"], i)
    return t["tx"], {"meta": t, "receipt": rec}


receipts = {}
with ThreadPoolExecutor(max_workers=12) as ex:
    for n, (txh, payload) in enumerate(ex.map(lambda p: fetch(*p), [(t, i) for i, t in enumerate(v3_txs)])):
        receipts[txh] = payload
        if n % 1000 == 0:
            print(f"  receipts {n}/{len(v3_txs)}", flush=True)

json.dump(receipts, open("out/raw/base-v3-receipts.json", "w"))
print(f"saved {len(receipts)} receipts -> out/raw/base-v3-receipts.json", flush=True)
