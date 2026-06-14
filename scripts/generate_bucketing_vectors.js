/*
 * Machine-derives MurmurHash3-32 golden vectors from the REAL npm `murmurhash`
 * package (MIT, Gary Court / Austin Appleby) — the same package the Convert JS
 * SDK imports as `Murmurhash.v3` in
 * packages/utils/src/string-utils.ts `generateHash` (default seed 9999).
 *
 * The npm `murmurhash` package converts input to UTF-8 bytes via
 * `new TextEncoder().encode(value)` and mixes in the UTF-8 byte length.
 * This matches the PHP SDK (`unpack('C*')`). Values are machine-derived by
 * running the real package — NOT a re-implementation.
 *
 * Prerequisite: npm install murmurhash@^2.0.1
 *
 * Usage:
 *   npm install murmurhash@^2.0.1
 *   node scripts/generate_bucketing_vectors.js > tests/parity/fixtures/bucketing_vectors.json
 *
 * Or with an existing install:
 *   NODE_PATH=/path/to/node_modules node scripts/generate_bucketing_vectors.js > tests/parity/fixtures/bucketing_vectors.json
 */
const murmurhash = require('murmurhash');

const inputs = [
  "", "a", "ab", "abc", "abcd", "test_visitor", "用户123",
  "the quick brown fox", "0", "12345",
  "e1visitor-1", "e2visitor-1", "100456visitor_42",
  "visitor-aaaaaaaa", "visitor-zzzzzzzz",
  "exp_100visitor_001", "exp_100visitor_002", "exp_100visitor_999",
  "café", "🎯emoji"
];
const seeds = [9999, 0, 1, 12345];
const vectors = [];
for (const seed of seeds) {
  for (const value of inputs) {
    vectors.push({ value, seed, expected: murmurhash.v3(String(value), seed) });
  }
}
const out = {
  generated_from: {
    reference: "npm `murmurhash@^2.0.1` package `v3` (UTF-8 via TextEncoder, length mix = UTF-8 byte count), as imported by Convert JS SDK packages/utils/src/string-utils.ts generateHash",
    semantics: "UTF-8 bytes via TextEncoder().encode(); length mix uses UTF-8 byte count (matches PHP SDK unpack('C*'))",
    default_seed: 9999,
    output: "unsigned 32-bit integer [0, 2^32)",
    generator: "scripts/generate_bucketing_vectors.js",
    sourced: "machine-derived by running the real npm murmurhash package (story 1.4; long-term ownership: story 3.5 / qs-05)"
  },
  vectors
};
console.log(JSON.stringify(out, null, 2));
