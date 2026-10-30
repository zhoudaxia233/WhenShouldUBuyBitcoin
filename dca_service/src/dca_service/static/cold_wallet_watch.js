/*
 * Cold wallet balance from an extended public key (Trezor zpub, Ledger xpub).
 *
 * The server keeps the key; the rest runs in the browser: the bc1q addresses
 * are derived here and their balances are read from mempool.space.
 *
 * Public derivation only (BIP32 CKDpub, BIP84 paths 0/i and 1/i). No private
 * key is ever handled; private extended keys are refused. The crypto is
 * written out here instead of loaded from a CDN so that no third-party script
 * runs next to the key.
 *
 * Classic script: in the browser it defines window.ColdWalletWatch; under
 * tests it exports the same helpers through a CommonJS-style module object.
 */
(function (root, factory) {
    var api = factory();
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    } else {
        root.ColdWalletWatch = api;
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var GAP_LIMIT = 20;
    var MEMPOOL_API = "https://mempool.space/api/address/";
    var RETRY_WAITS_MS = [2000, 4000, 8000, 16000, 32000];
    var PACE_MS = 500; // between address lookups, to stay under mempool.space's rate limit
    // No referrer, cookies or cached copies: mempool.space should learn the
    // addresses and nothing about this page.
    var FETCH_OPTIONS = { referrerPolicy: "no-referrer", credentials: "omit", cache: "no-store" };

    // ---- secp256k1 (public-key operations only) ----

    var P = 0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2fn;
    var N = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;
    var G = {
        x: 0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798n,
        y: 0x483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8n,
    };

    function mod(a, m) {
        var r = a % m;
        return r >= 0n ? r : r + m;
    }

    function powMod(base, exp, m) {
        var result = 1n;
        base = mod(base, m);
        while (exp > 0n) {
            if (exp & 1n) result = (result * base) % m;
            base = (base * base) % m;
            exp >>= 1n;
        }
        return result;
    }

    function invMod(a, m) {
        var lo = 1n, hi = 0n, low = mod(a, m), high = m;
        while (low > 1n) {
            var q = high / low;
            var nextLo = hi - lo * q, nextLow = high - low * q;
            hi = lo; high = low; lo = nextLo; low = nextLow;
        }
        return mod(lo, m);
    }

    // Jacobian coordinates; null is the point at infinity.
    function jDouble(p) {
        if (!p || p.y === 0n) return null;
        var ysq = (p.y * p.y) % P;
        var s = (4n * p.x * ysq) % P;
        var m = (3n * p.x * p.x) % P;
        var x = mod(m * m - 2n * s, P);
        var y = mod(m * (s - x) - 8n * ysq * ysq, P);
        var z = (2n * p.y * p.z) % P;
        return { x: x, y: y, z: z };
    }

    function jAdd(p, q) {
        if (!p) return q;
        if (!q) return p;
        var z1z1 = (p.z * p.z) % P, z2z2 = (q.z * q.z) % P;
        var u1 = (p.x * z2z2) % P, u2 = (q.x * z1z1) % P;
        var s1 = (p.y * q.z * z2z2) % P, s2 = (q.y * p.z * z1z1) % P;
        if (u1 === u2) return s1 === s2 ? jDouble(p) : null;
        var h = mod(u2 - u1, P), r = mod(s2 - s1, P);
        var hh = (h * h) % P, hhh = (h * hh) % P, v = (u1 * hh) % P;
        var x = mod(r * r - hhh - 2n * v, P);
        var y = mod(r * (v - x) - s1 * hhh, P);
        var z = (p.z * q.z * h) % P;
        return { x: x, y: y, z: z };
    }

    function toAffine(p) {
        if (!p) return null;
        var zi = invMod(p.z, P), zi2 = (zi * zi) % P;
        return { x: (p.x * zi2) % P, y: (p.y * zi2 * zi) % P };
    }

    function multiplyG(k) {
        var result = null;
        var addend = { x: G.x, y: G.y, z: 1n };
        while (k > 0n) {
            if (k & 1n) result = jAdd(result, addend);
            addend = jDouble(addend);
            k >>= 1n;
        }
        return result;
    }

    function decompress(bytes) {
        var x = bytesToBigInt(bytes.slice(1));
        if (x >= P) throw new Error("Invalid public key");
        var y = powMod(mod(x * x * x + 7n, P), (P + 1n) / 4n, P);
        if (mod(y * y, P) !== mod(x * x * x + 7n, P)) throw new Error("Invalid public key");
        if ((y & 1n) !== BigInt(bytes[0] & 1)) y = P - y;
        return { x: x, y: y };
    }

    function compress(point) {
        var out = new Uint8Array(33);
        out[0] = point.y & 1n ? 3 : 2;
        out.set(bigIntToBytes(point.x, 32), 1);
        return out;
    }

    // ---- Bytes and hashes ----

    function bytesToBigInt(bytes) {
        var n = 0n;
        for (var i = 0; i < bytes.length; i++) n = (n << 8n) | BigInt(bytes[i]);
        return n;
    }

    function bigIntToBytes(n, length) {
        var out = new Uint8Array(length);
        for (var i = length - 1; i >= 0; i--) {
            out[i] = Number(n & 0xffn);
            n >>= 8n;
        }
        return out;
    }

    function concat(a, b) {
        var out = new Uint8Array(a.length + b.length);
        out.set(a, 0);
        out.set(b, a.length);
        return out;
    }

    function subtle() {
        var c = typeof crypto !== "undefined" ? crypto : null;
        if (!c || !c.subtle) {
            throw new Error("This browser cannot compute addresses here (an HTTPS page is needed).");
        }
        return c.subtle;
    }

    async function hmacSha512(key, data) {
        var k = await subtle().importKey("raw", key, { name: "HMAC", hash: "SHA-512" }, false, ["sign"]);
        return new Uint8Array(await subtle().sign("HMAC", k, data));
    }

    var RL = [
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
        7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
        3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12,
        1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2,
        4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13,
    ];
    var RR = [
        5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12,
        6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2,
        15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13,
        8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14,
        12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11,
    ];
    var SL = [
        11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8,
        7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12,
        11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5,
        11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12,
        9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6,
    ];
    var SR = [
        8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6,
        9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11,
        9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5,
        15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8,
        8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11,
    ];
    var KL = [0x00000000, 0x5a827999, 0x6ed9eba1, 0x8f1bbcdc, 0xa953fd4e];
    var KR = [0x50a28be6, 0x5c4dd124, 0x6d703ef3, 0x7a6d76e9, 0x00000000];

    function rotl(x, n) {
        return (x << n) | (x >>> (32 - n));
    }

    function f(j, x, y, z) {
        if (j < 16) return x ^ y ^ z;
        if (j < 32) return (x & y) | (~x & z);
        if (j < 48) return (x | ~y) ^ z;
        if (j < 64) return (x & z) | (y & ~z);
        return x ^ (y | ~z);
    }

    function ripemd160(message) {
        var bitLength = message.length * 8;
        var padded = new Uint8Array(((message.length + 8) >> 6) * 64 + 64);
        padded.set(message);
        padded[message.length] = 0x80;
        var view = new DataView(padded.buffer);
        view.setUint32(padded.length - 8, bitLength >>> 0, true);
        view.setUint32(padded.length - 4, Math.floor(bitLength / 0x100000000), true);

        var h = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0];
        var x = new Array(16);
        for (var offset = 0; offset < padded.length; offset += 64) {
            for (var w = 0; w < 16; w++) x[w] = view.getUint32(offset + w * 4, true);
            var al = h[0], bl = h[1], cl = h[2], dl = h[3], el = h[4];
            var ar = al, br = bl, cr = cl, dr = dl, er = el;
            for (var j = 0; j < 80; j++) {
                var round = j >> 4;
                var t = (rotl((al + f(j, bl, cl, dl) + x[RL[j]] + KL[round]) | 0, SL[j]) + el) | 0;
                al = el; el = dl; dl = rotl(cl, 10); cl = bl; bl = t;
                t = (rotl((ar + f(79 - j, br, cr, dr) + x[RR[j]] + KR[round]) | 0, SR[j]) + er) | 0;
                ar = er; er = dr; dr = rotl(cr, 10); cr = br; br = t;
            }
            var tmp = (h[1] + cl + dr) | 0;
            h[1] = (h[2] + dl + er) | 0;
            h[2] = (h[3] + el + ar) | 0;
            h[3] = (h[4] + al + br) | 0;
            h[4] = (h[0] + bl + cr) | 0;
            h[0] = tmp;
        }
        var out = new Uint8Array(20);
        var outView = new DataView(out.buffer);
        for (var i = 0; i < 5; i++) outView.setUint32(i * 4, h[i] >>> 0, true);
        return out;
    }

    // ---- Encodings ----

    var BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    var BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";

    function base58Decode(text) {
        var n = 0n;
        for (var i = 0; i < text.length; i++) {
            var digit = BASE58.indexOf(text[i]);
            if (digit < 0) throw new Error("This is not an xpub or zpub.");
            n = n * 58n + BigInt(digit);
        }
        return bigIntToBytes(n, 82);
    }

    function bech32Polymod(values) {
        var gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
        var chk = 1;
        for (var i = 0; i < values.length; i++) {
            var top = chk >>> 25;
            chk = ((chk & 0x1ffffff) << 5) ^ values[i];
            for (var b = 0; b < 5; b++) if ((top >>> b) & 1) chk ^= gen[b];
        }
        return chk;
    }

    function segwitV0Address(program) {
        var data = [0];
        var acc = 0, bits = 0;
        for (var i = 0; i < program.length; i++) {
            acc = (acc << 8) | program[i];
            bits += 8;
            while (bits >= 5) {
                bits -= 5;
                data.push((acc >>> bits) & 31);
            }
        }
        if (bits > 0) data.push((acc << (5 - bits)) & 31);
        var hrp = [3, 3, 0, 2, 3]; // "bc" expanded: high bits, 0, low bits
        var mod = bech32Polymod(hrp.concat(data, [0, 0, 0, 0, 0, 0])) ^ 1;
        var out = "bc1";
        for (var d = 0; d < data.length; d++) out += BECH32[data[d]];
        for (var c = 0; c < 6; c++) out += BECH32[(mod >>> (5 * (5 - c))) & 31];
        return out;
    }

    // ---- Extended public keys ----

    var TRACKED = { "0488b21e": "xpub", "04b24746": "zpub" };
    var PRIVATE = ["0488ade4", "049d7878", "04b2430c", "0295b005", "02aa7a99", "04358394", "045f18bc"];

    function parseExtendedPublicKey(text) {
        var trimmed = String(text || "").trim();
        if (!/^[1-9A-HJ-NP-Za-km-z]{100,120}$/.test(trimmed)) {
            throw new Error("This is not an xpub or zpub.");
        }
        var raw = base58Decode(trimmed);
        var payload = raw.slice(0, 78);
        if (!checksumMatches(payload, raw.slice(78))) {
            throw new Error("The key's checksum does not match. Check it for a typo.");
        }
        var version = Array.from(payload.slice(0, 4), function (b) {
            return b.toString(16).padStart(2, "0");
        }).join("");
        if (PRIVATE.indexOf(version) >= 0) {
            throw new Error("This is a private key. Never paste it anywhere; export the xpub or zpub instead.");
        }
        if (!TRACKED[version]) {
            throw new Error("Only native segwit accounts (addresses starting with bc1q) can be tracked: paste the zpub or xpub of that account.");
        }
        var keyBytes = payload.slice(45, 78);
        if (keyBytes[0] !== 2 && keyBytes[0] !== 3) throw new Error("This is not an xpub or zpub.");
        return {
            prefix: TRACKED[version],
            chainCode: payload.slice(13, 45),
            publicKey: keyBytes,
        };
    }

    // Synchronous SHA-256, so parsing a key can reject typos while the user types.
    var SHA_K = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ];

    function sha256(message) {
        var padded = new Uint8Array(((message.length + 8) >> 6) * 64 + 64);
        padded.set(message);
        padded[message.length] = 0x80;
        var view = new DataView(padded.buffer);
        view.setUint32(padded.length - 4, message.length * 8, false);
        var h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
        var w = new Array(64);
        for (var offset = 0; offset < padded.length; offset += 64) {
            for (var i = 0; i < 16; i++) w[i] = view.getUint32(offset + i * 4, false);
            for (i = 16; i < 64; i++) {
                var s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
                var s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
                w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
            }
            var a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], ff = h[5], g = h[6], hh = h[7];
            for (i = 0; i < 64; i++) {
                var t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & ff) ^ (~e & g)) + SHA_K[i] + w[i]) | 0;
                var t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
                hh = g; g = ff; ff = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
            }
            h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0; h[2] = (h[2] + c) | 0; h[3] = (h[3] + d) | 0;
            h[4] = (h[4] + e) | 0; h[5] = (h[5] + ff) | 0; h[6] = (h[6] + g) | 0; h[7] = (h[7] + hh) | 0;
        }
        var out = new Uint8Array(32);
        var outView = new DataView(out.buffer);
        for (var k = 0; k < 8; k++) outView.setUint32(k * 4, h[k] >>> 0, false);
        return out;
    }

    function rotr(x, n) {
        return (x >>> n) | (x << (32 - n));
    }

    function checksumMatches(payload, checksum) {
        var hash = sha256(sha256(payload));
        for (var i = 0; i < 4; i++) if (hash[i] !== checksum[i]) return false;
        return true;
    }

    // BIP32 CKDpub for a non-hardened index.
    async function deriveChild(node, index) {
        var data = new Uint8Array(37);
        data.set(node.publicKey, 0);
        new DataView(data.buffer).setUint32(33, index, false);
        var i = await hmacSha512(node.chainCode, data);
        var tweak = bytesToBigInt(i.slice(0, 32));
        if (tweak >= N) throw new Error("Unusable derivation index");
        var parent = decompress(node.publicKey);
        var child = toAffine(jAdd(multiplyG(tweak), { x: parent.x, y: parent.y, z: 1n }));
        if (!child) throw new Error("Unusable derivation index");
        return { publicKey: compress(child), chainCode: i.slice(32) };
    }

    function addressOf(node) {
        return segwitV0Address(ripemd160(sha256(node.publicKey)));
    }

    async function deriveAddress(key, chain, index) {
        return addressOf(await deriveChild(await deriveChild(key, chain), index));
    }

    // ---- Balance ----

    function wait(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    // mempool.space rate-limits bursts, and its refusal carries no CORS header,
    // so in the browser it surfaces as a failed fetch: wait and retry.
    async function mempoolAddressStats(address, fetchImpl, sleep) {
        var get = fetchImpl || fetch;
        var pause = sleep || wait;
        var response = null;
        for (var attempt = 0; attempt < RETRY_WAITS_MS.length + 1; attempt++) {
            if (attempt > 0) await pause(RETRY_WAITS_MS[attempt - 1]);
            try {
                response = await get(MEMPOOL_API + address, FETCH_OPTIONS);
            } catch (e) {
                response = null;
            }
            if (response && response.ok) break;
        }
        if (!response || !response.ok) throw new Error("mempool.space did not answer. Try again in a few minutes.");
        var data = await response.json();
        var c = (data && data.chain_stats) || {}, m = (data && data.mempool_stats) || {};
        var balanceSats = c.funded_txo_sum - c.spent_txo_sum + m.funded_txo_sum - m.spent_txo_sum;
        var txCount = c.tx_count + m.tx_count;
        if (!Number.isSafeInteger(balanceSats) || balanceSats < 0 || !Number.isSafeInteger(txCount) || txCount < 0) {
            throw new Error("mempool.space sent an answer that is not a balance. Try again later.");
        }
        return { balanceSats: balanceSats, txCount: txCount };
    }

    function keyId(key) {
        return Array.from(key.publicKey).join(",") + "/" + Array.from(key.chainCode).join(",");
    }

    // Walks the receive (0) and change (1) chains of every key until gapLimit
    // addresses in a row have never been used, as wallets do. The same wallet
    // pasted twice (or as xpub and zpub) is counted once. A key with no
    // history at all is refused: it is the wrong account or a typo, and
    // counting it as 0 BTC would silently wipe the balance.
    async function scanBalance(keys, addressStats, options) {
        options = options || {};
        var gapLimit = options.gapLimit || GAP_LIMIT;
        var pause = options.sleep || wait;
        var onProgress = options.onProgress || function () {};
        var seen = {};
        var balanceSats = 0, usedAddresses = 0, checked = 0;
        for (var k = 0; k < keys.length; k++) {
            var id = keyId(keys[k]);
            if (seen[id]) continue;
            seen[id] = true;
            var usedForKey = 0;
            for (var chain = 0; chain <= 1; chain++) {
                var chainNode = await deriveChild(keys[k], chain);
                var gap = 0;
                for (var index = 0; gap < gapLimit; index++) {
                    if (checked > 0) await pause(PACE_MS);
                    var stats = await addressStats(addressOf(await deriveChild(chainNode, index)));
                    checked += 1;
                    onProgress(checked);
                    balanceSats += stats.balanceSats;
                    if (stats.txCount > 0) {
                        usedForKey += 1;
                        gap = 0;
                    } else {
                        gap += 1;
                    }
                }
            }
            if (usedForKey === 0) {
                throw new Error("Key " + (k + 1) + " has no transactions. Check that it is the native segwit (bc1q) account and that the first address matches your wallet app.");
            }
            usedAddresses += usedForKey;
        }
        return { balanceSats: balanceSats, usedAddresses: usedAddresses };
    }

    function maskKey(text) {
        var t = String(text || "").trim();
        return t.slice(0, 8) + "…" + t.slice(-7);
    }

    return {
        GAP_LIMIT: GAP_LIMIT,
        PACE_MS: PACE_MS,
        keyId: keyId,
        maskKey: maskKey,
        parseExtendedPublicKey: parseExtendedPublicKey,
        deriveAddress: deriveAddress,
        ripemd160: ripemd160,
        scanBalance: scanBalance,
        mempoolAddressStats: mempoolAddressStats,
    };
});
