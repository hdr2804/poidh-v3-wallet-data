# Poidh v3 — Wallet Data (Mainnet · Arbitrum · Base)

One consolidated CSV with, for every wallet that interacted with the **PoidhV3**
protocol: ETH paid into completed bounties, ETH earned as a bounty winner (gross,
before the 2.5% protocol fee), and poidh v3 claim NFTs currently held — per chain and
in total.

Built for poidh Base bounty **#1540 "poidh v3 Ethereum Data"**. Cutoff = the bounty's
creation time, **2026-11-08 03:59:54 UTC** (unix 1794110394); snapshot blocks —
Mainnet 26,367,617 · Arbitrum 522,271,780 · Base 54,600,096.

## Headline numbers

| | Mainnet | Arbitrum | Base | Total |
|---|---|---|---|---|
| Bounties created | 46 | 161 | 555 | 762 |
| Bounties completed | 27 | 113 | 321 | **461** |
| ETH paid | 3.381683 | 2.969041 | 6.01943544252522 | **12.37015944252522** |
| ETH earned | 3.381683 | 2.969041 | 6.01943544252522 | **12.37015944252522** |
| Claim NFTs held | 407 | 732 | 4,166 | 5,305 |
| — of which escrowed by the core contract | 380 | 619 | 3,845 | 4,844 |

**Reconciliation: total paid == total earned to the wei**, globally and per chain —
enforced per bounty during construction (net contributions must equal the gross
amount credited to the winner; 461/461 pass).

The CSV has **1,438 wallet rows** (472 with nonzero activity, listed first; the rest
are wallets whose only v3 activity — e.g. an unaccepted claim — carries true zeros
under the dataset's definitions). Claim NFTs held by the core contracts themselves
(escrow for unaccepted claims) sit on the contracts' own rows, never attributed to
individual users.

## Files

- `poidh-v3-wallet-data.csv` — the dataset (columns exactly as specified in the bounty)
- `METHODOLOGY.md` — sources, snapshot blocks, rules, reconciliation, edge cases
- `claim-summary.png` — headline summary image
- `scripts/` — the full pipeline (public RPCs only, no API keys)

## Watch out: v2 ≠ v3

The poidh indexer/frontend merges **PoidhV2** and **PoidhV3** into one bounty
sequence (Base ids 0–985 and Arbitrum ids 0–179 are v2). This dataset covers the v3
contracts only — see METHODOLOGY.md §2 for the contract addresses and how the
generations were separated.
