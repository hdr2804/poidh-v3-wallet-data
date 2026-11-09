# Poidh v3 Wallet Dataset — Methodology

Dataset for poidh Base bounty **#1540 "poidh v3 Ethereum Data"**: one consolidated CSV,
one row per wallet, with ETH paid, ETH earned, and poidh v3 claim NFTs held — per chain
(Mainnet, Arbitrum, Base) and in total. All figures are derived from primary on-chain
sources; the poidh indexer was used as an independent cross-check (and, on Base, as a
transaction enumerator — see §3).

## 1. Cutoff and snapshot blocks

Cutoff = the creation time of bounty #1540: **unix 1794110394 (2026-11-08 03:59:54 UTC)**.
For each chain the snapshot block is the last block whose timestamp is ≤ the cutoff:

| Chain | Snapshot block | Block timestamp | Next block |
|---|---|---|---|
| Mainnet (1) | 26,367,617 | 1794110387 | 1794110399 |
| Arbitrum (42161) | 522,271,780 | 1794110394 | 1794110395 |
| Base (8453) | 54,600,096 | 1794110394 | 1794110395 |

Every event and state read in this dataset is filtered to `block ≤ snapshot block`.
Anything after the cutoff (e.g. 2 further Base bounties, 1 further Base claim acceptance)
is excluded.

## 2. Contracts in scope — and the v2 trap

| Chain | v3 Core (PoidhV3) | v3 NFT (PoidhClaimNFT) |
|---|---|---|
| Mainnet | `0xe731dfadbff20542e10d09d26fc71445c70d4232` | `0x9c5f45d5e1382e4058d334d93c6c01442012a4d9` |
| Arbitrum | `0x5555fa783936c260f77385b4e153b9725fef1719` | `0x27e117cc9a8da363442e7bd0618939e3eeeacf6a` |
| Base | `0x5555fa783936c260f77385b4e153b9725fef1719` | `0x27e117cc9a8da363442e7bd0618939e3eeeacf6a` |

The core's own `poidhNft()` view returns exactly the NFT addresses above on all three
chains, and `bountyCounter()` at the snapshot blocks reads 46 / 161 / 555 — the
`BountyCreated` event counts in this dataset match those counters exactly.

**The trap:** the poidh indexer merges two protocol generations into one bounty
sequence. On Base, indexer bounties 0–985 are **PoidhV2** (core
`0xb502c5856f7244dccdd0264a541cc25675353d39`, verified on Sourcify as contract name
"PoidhV2", solc 0.8.19); on Arbitrum, indexer bounties 0–179 are PoidhV2 (core
`0x0aa50ce0d724cc28f8f7af4630c32377b4d5c27d`). PoidhV3 launched on Base and Arbitrum in
January 2026 (first v3 bounties: Base block 41,070,501; Arbitrum block 423,445,058) and
on Mainnet in May 2026 (first bounty block 25,091,218). Any dataset built from the
indexer (or from the frontend's continuous numbering) without separating the
generations silently includes ~1,160 v2 bounties. This dataset is **v3 only**: on Base,
every bounty created on/after 2026-01-10 (557 records) was classified by the emitter
address in its creation receipt — all 557 are v3 (indexer ids 986–1542 ↔ on-chain ids
0–556), and the Arbitrum boundary was verified the same way (v2 ends exactly at
indexer 179; on-chain counters prove no interleaving there: 180 v2 + 161 v3 = 341
indexer records).

## 3. Sources

Two+ independent sources per chain, cross-checked (§6):

- **Verified contract source** (Sourcify, full match): `PoidhV3.sol` / `PoidhClaimNFT.sol`
  — event semantics were read from the code, not guessed (see §4).
- **Mainnet**: full `eth_getLogs` scans of both contracts, block 25,000,000 → snapshot,
  via `rpc.mevblocker.io`.
- **Arbitrum**: full `eth_getLogs` scans, block 423,000,000 → snapshot, via
  `arb1.arbitrum.io/rpc` (10M-block spans).
- **Base**: no free RPC offers wide-range archive `eth_getLogs` on Base (publicnode
  requires a personal token for archive requests; drpc free caps ranges at ~100 blocks;
  tenderly/thirdweb cap at 1,000). Base was therefore built from **transaction
  receipts**: the indexer enumerates every protocol transaction; the receipt of every
  transaction touching a v3 bounty (6,078 unique txs) was fetched from ordinary full
  nodes (drpc / tenderly / thirdweb) and the v3 events decoded from the logs, filtered
  by emitter address. Completeness is not assumed — it is proven by the per-bounty
  reconciliation in §5 (a single missing join or withdrawal anywhere breaks it) and by
  the counter checks in §6.
- **NFT ownership**: `ownerOf(tokenId)` archive `eth_call` at the snapshot block for
  every claim id (1 … claimCounter−1) on all three chains — the state truth — with
  full Transfer-event replay as the cross-check.
- **poidh indexer API** (`indexer.poidh.xyz/api/v1`): independent counts of bounties,
  claims and accepted claims in v3 scope.

All money math is integer wei; decimal ETH strings are produced only when writing the
CSV (exact decimal expansion, no floats anywhere).

## 4. Rules implemented (from PoidhV3.sol)

- **Completed** = the bounty emitted `ClaimAccepted` at a block ≤ snapshot. The
  contract finalizes a bounty at most once.
- **ETH earned**: the winner (`claimIssuer`) is credited the **gross**
  `ClaimAccepted.bountyAmount` — i.e. before the 2.5% protocol fee, as specified.
  (Per bounty, `payout + fee == bountyAmount` and `fee == floor(bountyAmount × 250 /
  10000)` were asserted; 461/461 pass. Total fees inside the gross:
  0.3092539860631305 ETH; winners' net payouts total 12.0609054564620895 ETH.)
- **ETH paid** (completed bounties only):
  - *Solo bounty*: the issuer paid the full `BountyCreated.amount` (asserted equal to
    the gross for every solo completion).
  - *Open (crowdfunded) bounty*: each contributor is attributed their **actual net
    contribution** = issuer's initial amount (slot 0) + Σ `BountyJoined` − Σ
    `WithdrawFromOpenBounty`. Joins/withdrawals are impossible while a vote is open
    and after finalization, so the net vector at acceptance is exactly what the
    contract paid out of.
- **Excluded**: contributions to bounties that were canceled (`BountyCancelled`) or
  still active at the snapshot, and all refunds (`RefundClaimed` — by construction
  these only occur on canceled open bounties) never enter paid/earned.
- **NFTs held** = current ownership at the snapshot block. Claim NFTs are minted to
  the core contract as escrow (`mintToEscrow`) and released to the **bounty issuer**
  on acceptance; unaccepted claims' NFTs therefore sit in the core contract. Per the
  brief, protocol-held NFTs are **not** attributed to users: the core contracts carry
  their own CSV rows (Mainnet core: 380 NFTs; the shared Arbitrum/Base core address:
  619 on Arbitrum + 3,845 on Base = 4,464). No tokens were burned (0 transfers to the
  zero address as final state; every minted token still exists).
- **Currencies**: PoidhV3 accepts native ETH only (all funding functions are
  `payable`; `receive()` reverts). There are no ERC20 or other-currency bounties
  inside these contracts. The separate DEGEN-chain deployment is outside the brief's
  contract list and is not included.

## 5. Reconciliation (hard check)

For **every** completed bounty, attributed paid (sum of net contributions) is asserted
equal to the gross amount credited to the winner. Result: **461/461 bounties pass**;
zero discrepancies.

| Chain | Bounties created | Completed (solo / open) | Canceled | Active at snapshot | ETH paid | ETH earned |
|---|---|---|---|---|---|---|
| Mainnet | 46 | 27 (1 / 26) | 12 | 7 | 3.381683 | 3.381683 |
| Arbitrum | 161 | 113 (14 / 99) | 36 | 12 | 2.969041 | 2.969041 |
| Base | 555 | 321 (36 / 285) | 137 | 97 | 6.01943544252522 | 6.01943544252522 |
| **Total** | **762** | **461** | **185** | **116** | **12.37015944252522** | **12.37015944252522** |

Global: total paid **12,370,159,442,525,220,000 wei** == total earned
**12,370,159,442,525,220,000 wei**, per chain and across all chains.

## 6. Cross-checks performed

- `BountyCreated` counts (46 / 161 / 555) == `bountyCounter()` at snapshot blocks. ✔
- Accepted claims, indexer (v3 scope) vs on-chain `ClaimAccepted`: Mainnet 27 = 27;
  Arbitrum 113 = 113; Base 322 vs 321 — the one extra indexer acceptance is a claim
  accepted **after** the snapshot block (exactly 1 post-cutoff `ClaimAccepted` found
  in the Base receipts), correctly excluded by the cutoff. ✔
- NFT `ownerOf` sweep vs Transfer replay: Mainnet 0 mismatches, Arbitrum 0, Base 12 —
  the 12 are genuine post-acceptance **direct user-to-user transfers** (invisible to
  the indexer and to protocol receipts). The CSV uses `ownerOf`, the state truth. ✔
- NFT totals are internally consistent per chain: tokens existing = claims created
  (407 / 732 / 4,166); escrowed = tokens − completed (each acceptance releases
  exactly one NFT). ✔

## 7. Wallet universe (row inclusion)

The CSV has **1,438 rows**: every wallet that appears in any v3 protocol role —
bounty issuers (197), open-bounty contributors incl. refunded/withdrawn (190), claim
creators (1,236), voters (58), winners (257), and current NFT holders (roles overlap).
**472 wallets** have nonzero paid/earned/NFT values and are listed first (by activity);
the remaining 966 rows are wallets whose only v3 activity carries true zeros under the
brief's definitions (e.g. a claim creator whose claim was never accepted: paid 0,
earned 0, and their claim NFT is escrowed by the protocol, so held = 0). Including
them makes the file complete under any reading of "all relevant wallets"; filtering to
nonzero rows is a one-line operation for anyone who wants the narrow set. All values
in every row are exact regardless.

## 8. Limitations and edge cases

- **Base receipts vs log scan**: the receipt path depends on the indexer's transaction
  enumeration for *discovery*; soundness does not — the per-bounty reconciliation
  (§5), the counter equality (§6), and the indexer-vs-chain accepted-claim comparison
  would each expose a missing money event. NFT ownership on Base does not depend on
  the indexer at all (full `ownerOf` sweep).
- **Aggregator-routed transactions**: some users interact through aggregator
  contracts, producing receipts with hundreds of unrelated logs; only logs emitted by
  the v3 core / NFT contracts were decoded.
- **Pending withdrawals are not earnings**: winners are credited at acceptance
  (pull-payment balance); whether/when they later call `withdraw()` is irrelevant to
  the brief's gross-earned definition and is not tracked. The treasury's fee balance
  is likewise not "earned" — fees are reported inside the gross (§4).
- **The `round` field** in v3 events is the per-bounty vote-round counter, not a
  protocol generation marker; generations are distinguished by contract address (§2).
- One Arbitrum `WithdrawalTo` and one NFT `ApprovalForAll` event exist in range; both
  are irrelevant to the dataset's quantities and were ignored by design.

## 9. Reproduce

```
python3 scripts/snapshots.py         # snapshot blocks + counters (archive calls)
python3 scripts/fetch_indexer.py     # indexer bounties/claims/transactions, all chains
python3 scripts/fetch_logs.py        # Mainnet + Arbitrum full log scans
python3 scripts/fetch_base.py        # Base v2/v3 classification (creation receipts)
python3 scripts/fetch_base_receipts.py  # Base v3 receipts (checkpointed, resumable)
python3 scripts/fetch_owners.py      # ownerOf sweeps at snapshot blocks
python3 scripts/build_dataset.py     # decode, attribute, reconcile -> CSV + stats
python3 scripts/make_image.py        # claim summary image
```

Outputs: `out/poidh-v3-wallet-data.csv`, `out/stats.json`, `out/claim-summary.png`.
Build date: 2026-11-09. All RPC endpoints used are public; no API keys.
