"""Full eth_getLogs scans of the v3 core + NFT contracts on Mainnet and Arbitrum.

Mainnet: rpc.mevblocker.io (100k-ish spans). Arbitrum: arb1.arbitrum.io/rpc (<=10M spans).
No topic0 filter: fetch every event the contracts emitted in range; decode later.
Ranges: from a safely pre-deployment block to the snapshot block (inclusive).
"""
import json
import sys

sys.path.insert(0, "scripts")
from common import Rpc, CORE, NFT

SNAP = {int(k): v for k, v in json.load(open("out/snapshots.json")).items()}
JOBS = [
    # (chain, contract kind, rpc url, from_block, chunk)
    (1, "core", "https://rpc.mevblocker.io", 25_000_000, 200_000),
    (1, "nft", "https://rpc.mevblocker.io", 25_000_000, 200_000),
    (42161, "core", "https://arb1.arbitrum.io/rpc", 423_000_000, 5_000_000),
    (42161, "nft", "https://arb1.arbitrum.io/rpc", 423_000_000, 5_000_000),
]

for cid, kind, url, frm, chunk in JOBS:
    addr = CORE[cid] if kind == "core" else NFT[cid]
    to = SNAP[cid]["snapshot_block"]
    rpc = Rpc(url)
    logs = rpc.get_logs_chunked(addr, frm, to, topics=None, chunk=chunk)
    logs.sort(key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16)))
    path = f"out/raw/logs-{cid}-{kind}.json"
    json.dump(logs, open(path, "w"))
    print(f"chain {cid} {kind}: {len(logs)} logs [{frm}..{to}] -> {path}", flush=True)
