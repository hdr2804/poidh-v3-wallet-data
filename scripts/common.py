"""Shared RPC helpers for the poidh v3 dataset build.

Endpoints (probed 2026-11-09):
- publicnode: head/state-latest + block headers OK; archive (old logs/state) BLOCKED (needs token).
- arb1.arbitrum.io/rpc: eth_getLogs up to 10,000,000-block spans OK (archive logs).
- rpc.mevblocker.io: mainnet eth_getLogs at 100k spans OK (archive logs).
- base.gateway.tenderly.co: eth_getLogs max 1000-block spans (no key).
- base/arbitrum/eth drpc free: getLogs effectively capped ~100 blocks. Not used for history.
"""
import time
import requests
from eth_hash.auto import keccak

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Content-Type": "application/json",
}

PUBLICNODE = {
    1: "https://ethereum-rpc.publicnode.com",
    42161: "https://arbitrum-one-rpc.publicnode.com",
    8453: "https://base-rpc.publicnode.com",
}
LOG_RPC = {1: "https://rpc.mevblocker.io", 42161: "https://arb1.arbitrum.io/rpc"}
TENDERLY = "https://base.gateway.tenderly.co"

CORE = {
    1: "0xe731dfadbff20542e10d09d26fc71445c70d4232",
    42161: "0x5555fa783936c260f77385b4e153b9725fef1719",
    8453: "0x5555fa783936c260f77385b4e153b9725fef1719",
}
NFT = {
    1: "0x9c5f45d5e1382e4058d334d93c6c01442012a4d9",
    42161: "0x27e117cc9a8da363442e7bd0618939e3eeeacf6a",
    8453: "0x27e117cc9a8da363442e7bd0618939e3eeeacf6a",
}
CUTOFF = 1794110394  # 2026-11-08 03:59:54 UTC


def topic(sig: str) -> str:
    return "0x" + keccak(sig.encode()).hex()


def selector(sig: str) -> str:
    return "0x" + keccak(sig.encode()).hex()[:8]


class Rpc:
    def __init__(self, url, max_retries=5):
        self.url = url
        self.max_retries = max_retries
        self.s = requests.Session()
        self.s.headers.update(UA)
        self._id = 0

    def call(self, method, params):
        last = None
        for attempt in range(self.max_retries):
            self._id += 1
            try:
                r = self.s.post(
                    self.url,
                    json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
                    timeout=90,
                )
                j = r.json()
                if "error" in j:
                    err = str(j["error"])
                    # transient classes worth retrying
                    if any(k in err for k in ("temporarily", "Too Many", "rate", "timeout", "Timeout", "-32005", "limit")):
                        last = RuntimeError(err)
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    raise RuntimeError(f"{method} error: {err}")
                return j["result"]
            except (requests.RequestException, ValueError) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"{method} failed after retries: {last}")

    def block_ts(self, n):
        b = self.call("eth_getBlockByNumber", [hex(n), False])
        return int(b["timestamp"], 16)

    def head(self):
        return int(self.call("eth_blockNumber", []), 16)

    def snapshot_block(self, cutoff=CUTOFF):
        """Largest block with timestamp <= cutoff (binary search on headers)."""
        lo, hi = 0, self.head()
        # invariant: ts(lo) <= cutoff < ts(hi)  (lo=0 genesis always <= cutoff)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.block_ts(mid) <= cutoff:
                lo = mid
            else:
                hi = mid
        return lo

    def get_logs(self, address, frm, to, topics=None):
        flt = {"address": address, "fromBlock": hex(frm), "toBlock": hex(to)}
        if topics:
            flt["topics"] = topics
        return self.call("eth_getLogs", [flt])

    def get_logs_chunked(self, address, frm, to, topics=None, chunk=100000):
        out = []
        cur = frm
        while cur <= to:
            end = min(cur + chunk - 1, to)
            try:
                out.extend(self.get_logs(address, cur, end, topics))
            except RuntimeError:
                if end - cur < 1000:
                    raise
                # bisect the failing chunk
                mid = (cur + end) // 2
                out.extend(self.get_logs_chunked(address, cur, mid, topics, chunk=max(1000, (mid - cur + 1))))
                out.extend(self.get_logs_chunked(address, mid + 1, end, topics, chunk=max(1000, (end - mid))))
                cur = end + 1
                continue
            cur = end + 1
        return out

    def eth_call(self, to, data, block="latest"):
        blk = block if block == "latest" else hex(block)
        return self.call("eth_call", [{"to": to, "data": data}, blk])

    def receipt(self, txhash):
        return self.call("eth_getTransactionReceipt", [txhash])


def word(data_hex: str, i: int) -> int:
    """i-th 32-byte word of a hex string (no 0x assumption issues)."""
    h = data_hex[2:] if data_hex.startswith("0x") else data_hex
    return int(h[i * 64:(i + 1) * 64], 16)


def addr_word(data_hex: str, i: int) -> str:
    h = data_hex[2:] if data_hex.startswith("0x") else data_hex
    return "0x" + h[i * 64 + 24:(i + 1) * 64].lower()


def topic_addr(t: str) -> str:
    return "0x" + t[-40:].lower()


def topic_uint(t: str) -> int:
    return int(t, 16)
