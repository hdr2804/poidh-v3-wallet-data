"""Render the claim summary image from out/stats.json with PIL."""
import json

from PIL import Image, ImageDraw, ImageFont

stats = json.load(open("out/stats.json"))
chains = stats["chains"]
tot = stats["totals"]

W, H = 1600, 1080
BG = (13, 17, 23)
CARD = (22, 28, 38)
FG = (232, 237, 243)
DIM = (148, 163, 184)
ACCENT = (88, 166, 255)
GREEN = (63, 201, 127)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)


def font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(path, size)


def text(x, y, s, size, color=FG, bold=False, anchor="la"):
    d.text((x, y), s, font=font(size, bold), fill=color, anchor=anchor)


text(70, 56, "POIDH v3 — WALLET DATA", 44, ACCENT, bold=True)
text(70, 122, "Every ETH payment, earning and claim NFT across Mainnet · Arbitrum · Base", 27, DIM)
text(70, 162, "Cutoff: bounty #1540 creation — 8 Nov 2026, 03:59:54 UTC (per-chain snapshot blocks)", 24, DIM)

# headline stats row
hy = 232
boxes = [
    ("UNIQUE WALLETS", f"{tot['unique_wallets']:,}"),
    ("COMPLETED BOUNTIES", f"{sum(c['bounties_completed'] for c in chains.values()):,}"),
    ("PAID = EARNED (ETH)", f"{tot['paid_eth']}"),
    ("RECONCILED", "TO THE WEI ✓" if tot["reconciled"] else "MISMATCH ✗"),
]
bw = (W - 140 - 3 * 24) // 4
for i, (label, value) in enumerate(boxes):
    x = 70 + i * (bw + 24)
    d.rounded_rectangle([x, hy, x + bw, hy + 148], radius=14, fill=CARD)
    text(x + 22, hy + 20, label, 19 if len(label) > 22 else 20, DIM, bold=True)
    text(x + 22, hy + 58, value, 33 if len(value) < 13 else (26 if len(value) < 17 else 23), GREEN if i >= 2 else FG, bold=True)

# per-chain table
ty = 436
text(70, ty, "PER CHAIN", 24, DIM, bold=True)
rows = [
    ("", "bounties", "completed", "ETH paid", "ETH earned", "NFTs held", "escrowed*"),
    ("Mainnet", f"{chains['mainnet']['bounties_created']}", f"{chains['mainnet']['bounties_completed']}",
     chains['mainnet']['paid_eth'], chains['mainnet']['earned_eth'],
     f"{chains['mainnet']['nft_total_held']:,}", f"{chains['mainnet']['nft_protocol_held']:,}"),
    ("Arbitrum", f"{chains['arbitrum']['bounties_created']}", f"{chains['arbitrum']['bounties_completed']}",
     chains['arbitrum']['paid_eth'], chains['arbitrum']['earned_eth'],
     f"{chains['arbitrum']['nft_total_held']:,}", f"{chains['arbitrum']['nft_protocol_held']:,}"),
    ("Base", f"{chains['base']['bounties_created']}", f"{chains['base']['bounties_completed']}",
     chains['base']['paid_eth'], chains['base']['earned_eth'],
     f"{chains['base']['nft_total_held']:,}", f"{chains['base']['nft_protocol_held']:,}"),
]
colx = [70, 290, 440, 600, 880, 1170, 1350]
ry = ty + 44
for ri, row in enumerate(rows):
    y = ry + ri * 62
    if ri == 0:
        for cx, cell in zip(colx, row):
            text(cx, y, cell, 21, DIM, bold=True)
    else:
        d.rounded_rectangle([60, y - 8, W - 60, y + 46], radius=10, fill=CARD)
        for cx, cell in zip(colx, row):
            text(cx, y, cell, 22, FG, bold=(cx == 70))
    if ri == 0:
        d.line([60, y + 40, W - 60, y + 40], fill=DIM, width=1)

fy = ry + 4 * 62 + 26
text(70, fy, "* escrowed = claim NFTs still held by the poidh v3 core contract (unaccepted claims) —", 22, DIM)
text(70, fy + 32, "counted on the contract's own CSV rows, never attributed to individual users.", 22, DIM)
text(70, fy + 84, "Method: on-chain event logs + transaction receipts, cross-checked against the poidh indexer", 22, DIM)
text(70, fy + 116, "and ownerOf() state reads. Gross amounts (before the 2.5% protocol fee). Full CSV + methodology in the repo.", 22, DIM)
text(70, H - 56, "Snapshot blocks — Mainnet 26,367,617 · Arbitrum 522,271,780 · Base 54,600,096", 22, ACCENT)

img.save("out/claim-summary.png")
print("saved out/claim-summary.png")
