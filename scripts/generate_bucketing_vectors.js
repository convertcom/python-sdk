/*
 * Machine-derives MurmurHash3-32 golden vectors from a faithful port of the
 * npm `murmurhash` package's `v3` algorithm (MIT, Gary Court / Austin Appleby) —
 * the same function the Convert JS SDK imports as `Murmurhash.v3` in
 * packages/utils/src/string-utils.ts `generateHash` (default seed 9999).
 *
 * The npm package processes input via `charCodeAt(i) & 0xff` over UTF-16 code
 * units (NOT UTF-8 bytes) and mixes in `key.length` (code-unit count). The
 * pure-Python `murmurhash3_32` must replicate this exactly for byte-exact parity.
 *
 * Usage: node scripts/generate_bucketing_vectors.js > tests/parity/fixtures/bucketing_vectors.json
 */
function murmurhash3_32_gc(key, seed) {
  let remainder = key.length & 3;
  let bytes = key.length - remainder;
  let h1 = seed;
  const c1 = 0xcc9e2d51;
  const c2 = 0x1b873593;
  let i = 0;
  let k1, h1b;
  while (i < bytes) {
    k1 =
      (key.charCodeAt(i) & 0xff) |
      ((key.charCodeAt(++i) & 0xff) << 8) |
      ((key.charCodeAt(++i) & 0xff) << 16) |
      ((key.charCodeAt(++i) & 0xff) << 24);
    ++i;
    k1 = (((k1 & 0xffff) * c1) + ((((k1 >>> 16) * c1) & 0xffff) << 16)) & 0xffffffff;
    k1 = (k1 << 15) | (k1 >>> 17);
    k1 = (((k1 & 0xffff) * c2) + ((((k1 >>> 16) * c2) & 0xffff) << 16)) & 0xffffffff;
    h1 ^= k1;
    h1 = (h1 << 13) | (h1 >>> 19);
    h1b = (((h1 & 0xffff) * 5) + ((((h1 >>> 16) * 5) & 0xffff) << 16)) & 0xffffffff;
    h1 = ((h1b & 0xffff) + 0x6b64) + ((((h1b >>> 16) + 0xe654) & 0xffff) << 16);
  }
  k1 = 0;
  switch (remainder) {
    case 3: k1 ^= (key.charCodeAt(i + 2) & 0xff) << 16;
    case 2: k1 ^= (key.charCodeAt(i + 1) & 0xff) << 8;
    case 1:
      k1 ^= key.charCodeAt(i) & 0xff;
      k1 = (((k1 & 0xffff) * c1) + ((((k1 >>> 16) * c1) & 0xffff) << 16)) & 0xffffffff;
      k1 = (k1 << 15) | (k1 >>> 17);
      k1 = (((k1 & 0xffff) * c2) + ((((k1 >>> 16) * c2) & 0xffff) << 16)) & 0xffffffff;
      h1 ^= k1;
  }
  h1 ^= key.length;
  h1 ^= h1 >>> 16;
  h1 = (((h1 & 0xffff) * 0x85ebca6b) + ((((h1 >>> 16) * 0x85ebca6b) & 0xffff) << 16)) & 0xffffffff;
  h1 ^= h1 >>> 13;
  h1 = (((h1 & 0xffff) * 0xc2b2ae35) + ((((h1 >>> 16) * 0xc2b2ae35) & 0xffff) << 16)) & 0xffffffff;
  h1 ^= h1 >>> 16;
  return h1 >>> 0;
}

const inputs = [
  "", "a", "ab", "abc", "abcd", "test_visitor", "用户123",
  "the quick brown fox", "0", "12345",
  "e1visitor-1", "e2visitor-1", "100456visitor_42",
  "visitor-aaaaaaaa", "visitor-zzzzzzzz",
  "exp_100visitor_001", "exp_100visitor_002", "exp_100visitor_999"
];
const seeds = [9999, 0, 1, 12345];
const vectors = [];
for (const seed of seeds) {
  for (const value of inputs) {
    vectors.push({ value, seed, expected: murmurhash3_32_gc(value, seed) });
  }
}
const out = {
  generated_from: {
    reference: "npm `murmurhash` package v3 algorithm (faithful port), as imported by Convert JS SDK packages/utils/src/string-utils.ts generateHash",
    semantics: "charCodeAt(i) & 0xff over UTF-16 code units; length mix uses code-unit count",
    default_seed: 9999,
    output: "unsigned 32-bit integer [0, 2^32)",
    generator: "scripts/generate_bucketing_vectors.js",
    sourced: "machine-derived via node (story 1.4; long-term ownership: story 3.5 / qs-05)"
  },
  vectors
};
console.log(JSON.stringify(out, null, 2));
