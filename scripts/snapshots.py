import json, sys
sys.path.insert(0, "scripts")
from common import Rpc, PUBLICNODE, CORE, NFT, selector, CUTOFF

MARGIN = {1: 40000, 42161: 2000000, 8453: 2500000}
HEADER_EP = {1: PUBLICNODE[1], 42161: "https://arb1.arbitrum.io/rpc", 8453: PUBLICNODE[8453]}
CALL_EPS = {
    1: ["https://rpc.mevblocker.io", "https://eth.drpc.org", "https://mainnet.gateway.tenderly.co", "https://1.rpc.thirdweb.com", PUBLICNODE[1]],
    42161: ["https://arbitrum.gateway.tenderly.co", "https://42161.rpc.thirdweb.com", "https://arbitrum.drpc.org", PUBLICNODE[42161]],
    8453: [PUBLICNODE[8453], "https://base.drpc.org", "https://base.gateway.tenderly.co", "https://8453.rpc.thirdweb.com"],
}

def call_at(cid, data, block):
    last = None
    for ep in CALL_EPS[cid]:
        try:
            return Rpc(ep).eth_call(CORE[cid], data, block), ep
        except Exception as e:
            last = e
    raise RuntimeError(f"all endpoints failed for chain {cid}: {last}")

out = {}
for cid in (1, 42161, 8453):
    rpc = Rpc(HEADER_EP[cid])
    head = rpc.head()
    lo = head - MARGIN[cid]
    assert rpc.block_ts(lo) <= CUTOFF
    hi = head
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if rpc.block_ts(mid) <= CUTOFF:
            lo = mid
        else:
            hi = mid
    snap = lo
    bc, ep1 = call_at(cid, selector("bountyCounter()"), snap)
    cc, _ = call_at(cid, selector("claimCounter()"), snap)
    nft, _ = call_at(cid, selector("poidhNft()"), snap)
    out[cid] = {"snapshot_block": snap, "snapshot_ts": rpc.block_ts(snap),
                "next_block_ts": rpc.block_ts(snap + 1),
                "bounty_counter": int(bc, 16), "claim_counter": int(cc, 16),
                "core_poidhNft": "0x" + nft[-40:], "archive_call_endpoint": ep1}
    print(f"chain {cid}: snapshot {snap} ts {out[cid]['snapshot_ts']} next {out[cid]['next_block_ts']} | bounties@snap {out[cid]['bounty_counter']} | claimCounter {out[cid]['claim_counter']} | poidhNft {out[cid]['core_poidhNft']} (task NFT {NFT[cid]}) via {ep1}")
json.dump(out, open("out/snapshots.json", "w"), indent=1)
print("saved out/snapshots.json")
