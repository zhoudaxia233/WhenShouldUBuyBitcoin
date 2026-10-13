// Tests for reading the cold wallet balance from an extended public key in the
// browser. The key never leaves the browser: addresses are derived locally and
// only the summed balance goes to the server.

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

function loadWatch() {
    const source = readFileSync(
        join(process.cwd(), "dca_service", "src", "dca_service", "static", "cold_wallet_watch.js"),
        "utf8",
    );
    const module = { exports: {} };
    new Function("module", source)(module);
    return module.exports;
}

const {
    parseExtendedPublicKey,
    deriveAddress,
    ripemd160,
    scanBalance,
    mempoolAddressStats,
    maskKey,
    PACE_MS,
} = loadWatch();

// BIP84 test vector: "abandon abandon ... about", account m/84'/0'/0'.
const BIP84_ZPUB =
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs";
// The same account key as Ledger Live shows it for a native segwit account.
const BIP84_AS_XPUB =
    "xpub6CatWdiZiodmUeTDp8LT5or8nmbKNcuyvz7WyksVFkKB4RHwCD3XyuvPEbvqAQY3rAPshWcMLoP2fMFMKHPJ4ZeZXYVUhLv1VMrjPC7PW6V";
const BIP84_AS_YPUB =
    "ypub6XR9pJPUsVBFKweLeV85HtwdxjjmKEuUr6djm9mNdkh47X7ASsD6byaXFotRAKByFoWgSzCuoTjaYdrv2yoJroLAPtBuHFjVm5vNmhyNehE";
// BIP32 test vector 1, master node: a second, unrelated wallet.
const BIP32_TV1_XPUB =
    "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8";
const ZPRV_VERSION =
    "zprvAdG4iTXWBoARxkkzNpNh8r6Qag3irQB8PzEMkAFeTRXxHpbF9z4QgEvBRphj53hJFiBVJ1gYbNLfpUvgs1imuBRbkDZx1qjw6x6nQFUc6rX";

function hex(bytes) {
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

describe("ripemd160", () => {
    it("matches the reference test vectors", () => {
        const enc = new TextEncoder();
        expect(hex(ripemd160(enc.encode("")))).toBe("9c1185a5c5e9fc54612808977ee8f548b2258d31");
        expect(hex(ripemd160(enc.encode("abc")))).toBe("8eb208f7e05d987a9b044a8e98c6b087f15a0bfc");
        expect(hex(ripemd160(enc.encode("a".repeat(1000))))).toBe(
            "aa69deee9a8922e92f8105e007f76110f381e9cf",
        );
    });
});

describe("parseExtendedPublicKey", () => {
    it("accepts a Trezor zpub and a Ledger xpub", () => {
        expect(parseExtendedPublicKey(BIP84_ZPUB).prefix).toBe("zpub");
        expect(parseExtendedPublicKey(` ${BIP84_AS_XPUB}\n`).prefix).toBe("xpub");
    });

    it("refuses private keys without echoing them", () => {
        expect(() => parseExtendedPublicKey(ZPRV_VERSION)).toThrow(/private key/);
        try {
            parseExtendedPublicKey(ZPRV_VERSION);
        } catch (e) {
            expect(e.message).not.toContain(ZPRV_VERSION.slice(4, 20));
        }
    });

    it("refuses ypub and other address types it cannot track", () => {
        expect(() => parseExtendedPublicKey(BIP84_AS_YPUB)).toThrow(/bc1q/);
    });

    it("refuses a key with a typo", () => {
        const typo = BIP84_ZPUB.slice(0, -1) + (BIP84_ZPUB.endsWith("s") ? "t" : "s");
        expect(() => parseExtendedPublicKey(typo)).toThrow(/checksum/);
        expect(() => parseExtendedPublicKey("hello")).toThrow();
    });
});

describe("deriveAddress", () => {
    it("derives the BIP84 receive and change addresses", async () => {
        const key = parseExtendedPublicKey(BIP84_ZPUB);
        expect(await deriveAddress(key, 0, 0)).toBe("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu");
        expect(await deriveAddress(key, 0, 1)).toBe("bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g");
        expect(await deriveAddress(key, 1, 0)).toBe("bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el");
    });

    it("derives the same native segwit addresses from a Ledger xpub", async () => {
        const key = parseExtendedPublicKey(BIP84_AS_XPUB);
        expect(await deriveAddress(key, 0, 0)).toBe("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu");
    });
});

describe("scanBalance", () => {
    const noWait = async () => {};

    it("sums every used address and stops after the gap limit on both chains", async () => {
        const key = parseExtendedPublicKey(BIP84_ZPUB);
        const used = {
            bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu: { balanceSats: 0, txCount: 2 },
            bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g: { balanceSats: 150000, txCount: 1 },
            bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el: { balanceSats: 50000, txCount: 1 },
        };
        const asked = [];
        const stats = async (address) => {
            asked.push(address);
            return used[address] || { balanceSats: 0, txCount: 0 };
        };

        const result = await scanBalance([key], stats, { gapLimit: 3, sleep: noWait });

        expect(result.balanceSats).toBe(200000);
        expect(result.usedAddresses).toBe(3);
        // receive: 0,1 used + 3 empty; change: 0 used + 3 empty
        expect(asked.length).toBe(5 + 4);
    });

    it("adds up two different wallets, such as a Ledger and a Trezor", async () => {
        const ledger = parseExtendedPublicKey(BIP84_AS_XPUB);
        const trezor = parseExtendedPublicKey(BIP32_TV1_XPUB);
        const funded = new Set([
            await deriveAddress(ledger, 0, 0),
            await deriveAddress(trezor, 0, 0),
        ]);
        const stats = async (address) =>
            funded.has(address) ? { balanceSats: 1000, txCount: 1 } : { balanceSats: 0, txCount: 0 };

        const result = await scanBalance([ledger, trezor], stats, { gapLimit: 2, sleep: noWait });

        expect(result.balanceSats).toBe(2000);
    });

    it("counts a wallet once when its key is pasted twice or as both xpub and zpub", async () => {
        const keys = [
            parseExtendedPublicKey(BIP84_ZPUB),
            parseExtendedPublicKey(BIP84_AS_XPUB),
            parseExtendedPublicKey(BIP84_ZPUB),
        ];
        const stats = async (address) =>
            address === "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
                ? { balanceSats: 1000, txCount: 1 }
                : { balanceSats: 0, txCount: 0 };

        const result = await scanBalance(keys, stats, { gapLimit: 2, sleep: noWait });

        expect(result.balanceSats).toBe(1000);
    });

    it("refuses a key with no history instead of reporting 0 BTC", async () => {
        // A Ledger legacy, nested segwit or taproot account also exports an xpub;
        // read as bc1q it finds nothing, which must not wipe the balance.
        const keys = [parseExtendedPublicKey(BIP84_ZPUB), parseExtendedPublicKey(BIP32_TV1_XPUB)];
        const first = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu";
        const stats = async (address) =>
            address === first ? { balanceSats: 1000, txCount: 1 } : { balanceSats: 0, txCount: 0 };

        await expect(scanBalance(keys, stats, { gapLimit: 2, sleep: noWait })).rejects.toThrow(
            /Key 2 has no transactions/,
        );
    });

    it("spaces requests out and reports progress", async () => {
        const key = parseExtendedPublicKey(BIP84_ZPUB);
        const waits = [];
        const progress = [];
        const stats = async () => ({ balanceSats: 0, txCount: 0 });
        const first = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu";
        const statsWithHistory = async (address) =>
            address === first ? { balanceSats: 1, txCount: 1 } : stats(address);

        await scanBalance([key], statsWithHistory, {
            gapLimit: 2,
            sleep: async (ms) => { waits.push(ms); },
            onProgress: (checked) => progress.push(checked),
        });

        // 3 receive + 2 change addresses, a pause before every request but the first
        expect(waits).toEqual([PACE_MS, PACE_MS, PACE_MS, PACE_MS]);
        expect(progress).toEqual([1, 2, 3, 4, 5]);
    });
});

describe("maskKey", () => {
    it("shows only the start and end of a key", () => {
        expect(maskKey(BIP84_ZPUB)).toBe("zpub6rFR…AGutZYs");
    });
});

describe("mempoolAddressStats", () => {
    it("counts confirmed and pending funds from mempool.space", async () => {
        const urls = [];
        const fetchImpl = async (url) => {
            urls.push(url);
            return {
                ok: true,
                json: async () => ({
                    chain_stats: { funded_txo_sum: 300, spent_txo_sum: 100, tx_count: 2 },
                    mempool_stats: { funded_txo_sum: 0, spent_txo_sum: 50, tx_count: 1 },
                }),
            };
        };

        const stats = await mempoolAddressStats("bc1qexample", fetchImpl);

        expect(urls).toEqual(["https://mempool.space/api/address/bc1qexample"]);
        expect(stats).toEqual({ balanceSats: 150, txCount: 3 });
    });

    it("sends no referrer, cookies or cache, so mempool.space does not learn this page's URL", async () => {
        let options = null;
        const fetchImpl = async (url, opts) => {
            options = opts;
            return {
                ok: true,
                json: async () => ({
                    chain_stats: { funded_txo_sum: 0, spent_txo_sum: 0, tx_count: 0 },
                    mempool_stats: { funded_txo_sum: 0, spent_txo_sum: 0, tx_count: 0 },
                }),
            };
        };

        await mempoolAddressStats("bc1qexample", fetchImpl);

        expect(options).toEqual({ referrerPolicy: "no-referrer", credentials: "omit", cache: "no-store" });
    });

    it("rejects an answer that is not a valid balance", async () => {
        const fetchImpl = async () => ({ ok: true, json: async () => ({ chain_stats: {} }) });
        const sleep = async () => {};
        await expect(mempoolAddressStats("bc1qexample", fetchImpl, sleep)).rejects.toThrow(/mempool\.space/);
    });

    it("waits and retries when mempool.space rate-limits", async () => {
        // A rate-limited reply has no CORS header, so the browser throws instead of returning 429.
        let calls = 0;
        const fetchImpl = async () => {
            calls += 1;
            if (calls < 3) throw new TypeError("Failed to fetch");
            return {
                ok: true,
                json: async () => ({
                    chain_stats: { funded_txo_sum: 10, spent_txo_sum: 0, tx_count: 1 },
                    mempool_stats: { funded_txo_sum: 0, spent_txo_sum: 0, tx_count: 0 },
                }),
            };
        };
        const waits = [];
        const sleep = async (ms) => { waits.push(ms); };

        const stats = await mempoolAddressStats("bc1qexample", fetchImpl, sleep);

        expect(stats.balanceSats).toBe(10);
        expect(waits).toEqual([2000, 4000]);
    });

    it("fails clearly when mempool.space keeps refusing", async () => {
        const fetchImpl = async () => ({ ok: false, status: 429 });
        const sleep = async () => {};
        await expect(mempoolAddressStats("bc1qexample", fetchImpl, sleep)).rejects.toThrow(/mempool\.space/);
    });
});
