"""Authoritative NFT ownership: ownerOf(tokenId) at the snapshot block, all chains.

Resume-capable + failure-tolerant:
- chains whose out/owners-{cid}.json already exists are skipped;
- per-token failures are collected and retried in a serial second pass;
- progress is checkpointed to out/owners-{cid}.partial.json every 250 results.
ownerOf reverts => token never minted or burned => null.
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "scripts")
from common import Rpc, NFT, selector

SNAP = {int(k): v for k, v in json.load(open("out/snapshots.json")).items()}
EPS = {
    1: ["https://rpc.mevblocker.io", "https://eth.drpc.org", "https://mainnet.gateway.tenderly.co", "https://1.rpc.thirdweb.com"],
    42161: ["https://arbitrum.gateway.tenderly.co", "https://42161.rpc.thirdweb.com", "https://arbitrum.drpc.org"],
    8453: ["https://base-rpc.publicnode.com", "https://base.drpc.org", "https://base.gateway.tenderly.co", "https://8453.rpc.thirdweb.com"],
}
REVERT_MARKERS = ("revert", "invalid token", "nonexistent", "erc721", "execution")
_local = threading.local()
OWNEROF = selector("ownerOf(uint256)")


def rpc_for(cid, i):
    if not hasattr(_local, "rpcs"):
        _local.rpcs = {}
    if cid not in _local.rpcs:
        _local.rpcs[cid] = [Rpc(u, max_retries=2) for u in EPS[cid]]
    lst = _local.rpcs[cid]
    return lst[i % len(lst)]


def try_owner(cid, token_id, snap_block, i):
    """Returns (owner|None, ok). ok=False means transport-level failure."""
    data = OWNEROF + "%064x" % token_id
    for k in range(len(EPS[cid])):
        try:
            r = rpc_for(cid, i + k).eth_call(NFT[cid], data, snap_block)
            return "0x" + r[-40:].lower(), True
        except Exception as e:
            msg = str(e).lower()
            if any(m in msg for m in REVERT_MARKERS):
                return None, True
            time.sleep(0.5)
    return None, False


def sweep(cid):
    final_path = f"out/owners-{cid}.json"
    if os.path.exists(final_path):
        print(f"chain {cid}: already done, skipping", flush=True)
        return
    snap_block = SNAP[cid]["snapshot_block"]
    top = SNAP[cid]["claim_counter"]
    partial_path = f"out/owners-{cid}.partial.json"
    owners = {}
    if os.path.exists(partial_path):
        owners = {int(k): v for k, v in json.load(open(partial_path)).items()}
        print(f"chain {cid}: resuming with {len(owners)} checkpointed results", flush=True)
    todo = [t for t in range(1, top) if t not in owners]
    print(f"chain {cid}: ownerOf sweep {len(todo)} tokenIds at block {snap_block}", flush=True)
    failed = []

    def work(p):
        tid, i = p
        owner, ok = try_owner(cid, tid, snap_block, i)
        return tid, owner, ok

    done = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        for tid, owner, ok in ex.map(work, [(t, i) for i, t in enumerate(todo)]):
            if ok:
                owners[tid] = owner
            else:
                failed.append(tid)
            done += 1
            if done % 250 == 0:
                json.dump(owners, open(partial_path, "w"))
                print(f"  {done}/{len(todo)} (failed so far: {len(failed)})", flush=True)
    # serial retry pass for failures, slower and patient
    still = []
    for tid in failed:
        owner, ok = None, False
        for attempt in range(6):
            owner, ok = try_owner(cid, tid, snap_block, attempt)
            if ok:
                break
            time.sleep(3 * (attempt + 1))
        if ok:
            owners[tid] = owner
        else:
            still.append(tid)
    json.dump(owners, open(partial_path, "w"))
    if still:
        print(f"chain {cid}: {len(still)} tokenIds STILL failing: {still[:20]}", flush=True)
        raise SystemExit(f"ownerOf sweep incomplete for chain {cid}: {len(still)} failures")
    held = sum(1 for v in owners.values() if v)
    json.dump(owners, open(final_path, "w"))
    os.remove(partial_path)
    print(f"chain {cid}: {held} tokens exist at snapshot -> {final_path}", flush=True)


for cid in (1, 42161, 8453):
    sweep(cid)
