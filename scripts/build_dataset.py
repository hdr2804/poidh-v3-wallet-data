"""Build the poidh v3 wallet dataset from fetched chain data.

Inputs (out/):
  snapshots.json, owners-{cid}.json,
  raw/logs-{1,42161}-core.json, raw/logs-{1,42161}-nft.json   (full log scans)
  raw/base-v3-receipts.json, raw/base-bounty-classification.json (Base receipt path)
  raw/indexer-{cid}-bounties.json, raw/indexer-{cid}-claims.json (cross-checks)

Rules (from PoidhV3.sol, verified source):
  - A bounty is COMPLETED iff it emitted ClaimAccepted at block <= snapshot.
  - earned[winner] += ClaimAccepted.bountyAmount (gross, before the 2.5% fee).
  - paid: solo bounty  -> issuer paid BountyCreated.amount (must equal gross).
          open bounty  -> issuer's initial amount + each BountyJoined amount
                          - each WithdrawFromOpenBounty amount, per participant
                          (must sum to the gross). Canceled/active bounties and
                          RefundClaimed amounts never enter paid/earned.
  - nfts_held: ownerOf() at the snapshot block (authoritative); log/receipt
    Transfer replay is the cross-check and burn detector.
All money math is integer wei; decimals are formatted only at CSV write time.
"""
import csv
import json
import sys
from collections import defaultdict

sys.path.insert(0, "scripts")
from common import CORE, NFT, topic, topic_addr, topic_uint, word, addr_word

SNAP = {int(k): v for k, v in json.load(open("out/snapshots.json")).items()}
CHAINS = {1: "mainnet", 42161: "arbitrum", 8453: "base"}
ZERO = "0x" + "0" * 40

T = {
    "BountyCreated": topic("BountyCreated(uint256,address,string,string,uint256,uint256,bool,uint256)"),
    "BountyJoined": topic("BountyJoined(uint256,address,uint256,uint256,uint256)"),
    "WithdrawFromOpenBounty": topic("WithdrawFromOpenBounty(uint256,address,uint256,uint256,uint256)"),
    "ClaimAccepted": topic("ClaimAccepted(uint256,uint256,address,address,uint256,uint256,uint256,uint256)"),
    "BountyCancelled": topic("BountyCancelled(uint256,address,uint256,uint256)"),
    "RefundClaimed": topic("RefundClaimed(uint256,address,uint256,uint256)"),
    "ClaimCreated": topic("ClaimCreated(uint256,address,uint256,address,string,string,uint256,string,uint256)"),
    "VoteCast": topic("VoteCast(address,uint256,uint256,bool,uint256,uint256)"),
    "Transfer": topic("Transfer(address,address,uint256)"),
}


def fmt_eth(wei: int) -> str:
    if wei == 0:
        return "0"
    sign = "-" if wei < 0 else ""
    wei = abs(wei)
    whole, frac = divmod(wei, 10**18)
    if frac == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{('%018d' % frac).rstrip('0')}"


def iter_core_logs(cid):
    """Yield normalized log dicts for the v3 core contract, block <= snapshot,
    in canonical (blockNumber, logIndex) order — event handlers below assume
    creation precedes joins/acceptance."""
    snap = SNAP[cid]["snapshot_block"]
    if cid in (1, 42161):
        logs = [l for l in json.load(open(f"out/raw/logs-{cid}-core.json"))
                if int(l["blockNumber"], 16) <= snap]
    else:
        receipts = json.load(open("out/raw/base-v3-receipts.json"))
        logs = []
        for txh, payload in receipts.items():
            rec = payload["receipt"]
            if int(rec["blockNumber"], 16) > snap:
                continue
            for l in rec["logs"]:
                if l["address"].lower() == CORE[cid].lower():
                    logs.append(l)
    logs.sort(key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16)))
    yield from logs


def iter_nft_logs(cid):
    snap = SNAP[cid]["snapshot_block"]
    if cid in (1, 42161):
        for l in json.load(open(f"out/raw/logs-{cid}-nft.json")):
            if int(l["blockNumber"], 16) <= snap:
                yield l
    else:
        receipts = json.load(open("out/raw/base-v3-receipts.json"))
        for txh, payload in receipts.items():
            rec = payload["receipt"]
            if int(rec["blockNumber"], 16) > snap:
                continue
            for l in rec["logs"]:
                if l["address"].lower() == NFT[cid].lower():
                    yield l


stats = {"chains": {}, "problems": [], "crosschecks": []}
wallets = {}  # addr -> {cid: {"paid": int, "earned": int, "nfts": int}}
# Maximal interaction universe (for all-zero rows): every address that appears
# in any v3 protocol role. Paid/earned/NFT values still follow the brief's
# strict definitions, so pure claim creators / issuers of uncompleted bounties
# / voters appear with true zeros rather than being silently dropped.
universe = {"issuers": set(), "contributors": set(), "creators": set(), "voters": set()}


def W(addr, cid):
    return wallets.setdefault(addr, {}).setdefault(cid, {"paid": 0, "earned": 0, "nfts": 0})


total_paid = total_earned = 0
for cid, cname in CHAINS.items():
    bounties = {}  # id -> dict
    accepted = {}
    n_created = n_cancelled = 0
    refund_events = 0
    for l in iter_core_logs(cid):
        t0 = l["topics"][0].lower()
        data = l["data"]
        if t0 == T["BountyCreated"]:
            bid = topic_uint(l["topics"][1])
            universe["issuers"].add(topic_addr(l["topics"][2]))
            bounties[bid] = {
                "issuer": topic_addr(l["topics"][2]),
                "amount": word(data, 2),
                "is_open": word(data, 4) == 1,
                "joins": defaultdict(int),
                "withdrawals": defaultdict(int),
            }
            n_created += 1
        elif t0 == T["BountyJoined"]:
            bid = topic_uint(l["topics"][1])
            universe["contributors"].add(topic_addr(l["topics"][2]))
            if bid in bounties:
                bounties[bid]["joins"][topic_addr(l["topics"][2])] += word(data, 0)
        elif t0 == T["WithdrawFromOpenBounty"]:
            bid = topic_uint(l["topics"][1])
            universe["contributors"].add(topic_addr(l["topics"][2]))
            if bid in bounties:
                bounties[bid]["withdrawals"][topic_addr(l["topics"][2])] += word(data, 0)
        elif t0 == T["ClaimAccepted"]:
            bid = topic_uint(l["topics"][1])
            gross, payout, fee = word(data, 1), word(data, 2), word(data, 3)
            if bid in accepted:
                stats["problems"].append(f"{cname} bounty {bid}: DUPLICATE ClaimAccepted")
            accepted[bid] = {"winner": topic_addr(l["topics"][3]), "claim_id": topic_uint(l["topics"][2]),
                             "gross": gross, "payout": payout, "fee": fee}
            if payout + fee != gross:
                stats["problems"].append(f"{cname} bounty {bid}: payout+fee != gross")
            if fee != gross * 250 // 10000:
                stats["problems"].append(f"{cname} bounty {bid}: fee != floor(2.5% of gross)")
        elif t0 == T["BountyCancelled"]:
            n_cancelled += 1
        elif t0 == T["RefundClaimed"]:
            refund_events += 1
            universe["contributors"].add(topic_addr(l["topics"][2]))
        elif t0 == T["ClaimCreated"]:
            universe["creators"].add(topic_addr(l["topics"][2]))
        elif t0 == T["VoteCast"]:
            universe["voters"].add(topic_addr(l["topics"][1]))

    # --- cross-check: creations vs on-chain counter at snapshot
    expected = SNAP[cid]["bounty_counter"]
    stats["crosschecks"].append(
        f"{cname}: BountyCreated events <= snapshot = {n_created}, bountyCounter@snapshot = {expected}, match = {n_created == expected}")

    chain_paid = chain_earned = 0
    n_solo = n_open = 0
    for bid, acc in accepted.items():
        b = bounties.get(bid)
        if b is None:
            stats["problems"].append(f"{cname} bounty {bid}: ClaimAccepted without BountyCreated")
            continue
        gross = acc["gross"]
        contrib = {b["issuer"]: b["amount"]}
        for p, amt in b["joins"].items():
            contrib[p] = contrib.get(p, 0) + amt
        for p, amt in b["withdrawals"].items():
            contrib[p] = contrib.get(p, 0) - amt
        s = sum(contrib.values())
        if s != gross:
            stats["problems"].append(
                f"{cname} bounty {bid}: net contributions {s} != gross {gross} (diff {s - gross})")
        if b["is_open"]:
            n_open += 1
        else:
            n_solo += 1
        for p, amt in contrib.items():
            if amt:
                W(p, cid)["paid"] += amt
                chain_paid += amt
        W(acc["winner"], cid)["earned"] += gross
        chain_earned += gross

    # --- NFT holdings: ownerOf sweep (authoritative)
    owners = {int(k): v for k, v in json.load(open(f"out/owners-{cid}.json")).items()}
    nft_counts = defaultdict(int)
    for tid, owner in owners.items():
        if owner:
            nft_counts[owner] += 1
    for addr, n in nft_counts.items():
        W(addr, cid)["nfts"] += n

    # --- NFT replay cross-check (transfers), incl. burn + direct-transfer detection
    replay = {}
    n_burned = 0
    logs_nft = sorted(iter_nft_logs(cid), key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16)))
    for l in logs_nft:
        if l["topics"][0].lower() != T["Transfer"]:
            continue
        to = topic_addr(l["topics"][2])
        tid = topic_uint(l["topics"][3])
        replay[tid] = to
    mismatches = []
    for tid, owner in owners.items():
        r = replay.get(tid)
        if owner is None:
            if r == ZERO:
                n_burned += 1
            elif r is not None:
                mismatches.append((tid, "sweep:none", r))
        elif r != owner:
            mismatches.append((tid, owner, r))
    replay_only = [tid for tid in replay if tid not in owners]
    stats["crosschecks"].append(
        f"{cname}: NFT ownerOf-vs-replay mismatches = {len(mismatches)} (first 5: {mismatches[:5]}), "
        f"replay-only tokenIds = {len(replay_only)}, burned = {n_burned}")

    stats["chains"][cname] = {
        "snapshot_block": SNAP[cid]["snapshot_block"],
        "bounties_created": n_created,
        "bounties_completed": len(accepted),
        "completed_solo": n_solo,
        "completed_open": n_open,
        "bounties_cancelled_events": n_cancelled,
        "refund_claimed_events": refund_events,
        "paid_wei": chain_paid,
        "earned_wei": chain_earned,
        "paid_eth": fmt_eth(chain_paid),
        "earned_eth": fmt_eth(chain_earned),
        "nft_tokens_existing": sum(1 for v in owners.values() if v),
        "nft_protocol_held": nft_counts.get(CORE[cid].lower(), 0),
        "nft_total_held": sum(nft_counts.values()),
        "nft_burned": n_burned,
    }
    total_paid += chain_paid
    total_earned += chain_earned
    print(f"{cname}: completed {len(accepted)} (solo {n_solo}, open {n_open}), "
          f"paid {fmt_eth(chain_paid)} ETH, earned {fmt_eth(chain_earned)} ETH, "
          f"NFTs held {sum(nft_counts.values())} (protocol escrow {nft_counts.get(CORE[cid].lower(), 0)})", flush=True)

# --- indexer cross-check: accepted claims per chain (v3 scope)
for cid, cname in CHAINS.items():
    idx_bounties = json.load(open(f"out/raw/indexer-{cid}-bounties.json"))
    idx_claims = json.load(open(f"out/raw/indexer-{cid}-claims.json"))
    if cid == 8453:
        cls = json.load(open("out/raw/base-bounty-classification.json"))
        v3_indexer_ids = {int(k) for k, v in cls.items() if v["gen"] == "v3"}
        n_acc = sum(1 for c in idx_claims if c["isAccepted"] and c["bountyId"] in v3_indexer_ids)
        scope = "receipt-classified v3 bounty ids"
    elif cid == 42161:
        onchain = {b["id"]: b["onChainId"] for b in idx_bounties}
        n_acc = sum(1 for c in idx_claims if c["isAccepted"] and onchain.get(c["bountyId"], 10**9) < 10000
                    and c["bountyId"] >= 180)
        scope = "indexer ids >= 180 (v3 era; v2/v3 boundary verified by creation receipts)"
    else:
        n_acc = sum(1 for c in idx_claims if c["isAccepted"])
        scope = "all (single v3 generation)"
    stats["crosschecks"].append(
        f"{cname}: indexer accepted claims in v3 scope ({scope}) = {n_acc}; on-chain ClaimAccepted = {stats['chains'][cname]['bounties_completed']}")

# --- materialize all-zero rows for the maximal interaction universe
n_nonzero = len(wallets)
for role, addrs in universe.items():
    for a in addrs:
        if a not in wallets:
            wallets[a] = {}
stats["universe"] = {
    "wallets_with_nonzero_activity": n_nonzero,
    "all_zero_rows_added": len(wallets) - n_nonzero,
    "role_counts": {role: len(addrs) for role, addrs in universe.items()},
    "total_rows": len(wallets),
}

stats["totals"] = {"paid_wei": total_paid, "earned_wei": total_earned,
                   "paid_eth": fmt_eth(total_paid), "earned_eth": fmt_eth(total_earned),
                   "reconciled": total_paid == total_earned,
                   "unique_wallets": len(wallets),
                   "wallets_with_nonzero_activity": n_nonzero}
print(f"TOTAL: paid {fmt_eth(total_paid)} == earned {fmt_eth(total_earned)} -> {total_paid == total_earned}; wallets {len(wallets)}")
print("problems:", len(stats["problems"]))
for p in stats["problems"][:20]:
    print("  !", p)

# --- CSV
cols = ["wallet_address"]
for cname in ("mainnet", "arbitrum", "base"):
    cols += [f"eth_paid_{cname}", f"eth_earned_{cname}", f"nfts_held_{cname}"]
# rebuild in the brief's exact column order:
cols = ["wallet_address",
        "eth_paid_mainnet", "eth_paid_arbitrum", "eth_paid_base", "eth_paid_total",
        "eth_earned_mainnet", "eth_earned_arbitrum", "eth_earned_base", "eth_earned_total",
        "nfts_held_mainnet", "nfts_held_arbitrum", "nfts_held_base", "nfts_held_total"]
cid_of = {"mainnet": 1, "arbitrum": 42161, "base": 8453}
rows = []
for addr, per in wallets.items():
    paid = {c: per.get(cid_of[c], {}).get("paid", 0) for c in cid_of}
    earn = {c: per.get(cid_of[c], {}).get("earned", 0) for c in cid_of}
    nfts = {c: per.get(cid_of[c], {}).get("nfts", 0) for c in cid_of}
    rows.append((addr, paid, earn, nfts))
rows.sort(key=lambda r: (0 if (sum(r[1].values()) + sum(r[2].values()) + sum(r[3].values())) > 0 else 1,
                         -(sum(r[1].values()) + sum(r[2].values())), r[0]))
with open("out/poidh-v3-wallet-data.csv", "w", newline="") as f:
    wcsv = csv.writer(f)
    wcsv.writerow(cols)
    for addr, paid, earn, nfts in rows:
        wcsv.writerow([addr,
                       fmt_eth(paid["mainnet"]), fmt_eth(paid["arbitrum"]), fmt_eth(paid["base"]),
                       fmt_eth(sum(paid.values())),
                       fmt_eth(earn["mainnet"]), fmt_eth(earn["arbitrum"]), fmt_eth(earn["base"]),
                       fmt_eth(sum(earn.values())),
                       nfts["mainnet"], nfts["arbitrum"], nfts["base"], sum(nfts.values())])
print(f"CSV rows: {len(rows)} -> out/poidh-v3-wallet-data.csv")
json.dump(stats, open("out/stats.json", "w"), indent=1)
print("stats -> out/stats.json")
