/*
 * Bucketing hash + visitor-based bucket selection oracle for the Convert
 * JavaScript SDK (../javascript-sdk/packages/bucketing/src/bucketing-manager.ts
 * and packages/utils/src/string-utils.ts `generateHash`, default seed 9999).
 *
 * murmurhash3_32 delegates to the REAL npm `murmurhash@^2.0.1` package, which
 * encodes the input string to UTF-8 bytes via `new TextEncoder().encode(value)`
 * and mixes in the UTF-8 byte length — NOT charCodeAt over UTF-16 code units.
 * This file requires the `murmurhash` package to be installed in the
 * `scripts/js_reference/node_modules/` directory (run `npm install` there before
 * regenerating fixtures). The NODE_PATH environment variable can also be used to
 * point to a pre-installed location. See tests/parity/README.md for prerequisites.
 *
 * The reference answers are COMPUTED by running the real npm oracle — never
 * hand-authored.
 */
'use strict';

const murmurhash = require('murmurhash');

const DEFAULT_HASH_SEED = 9999;
const DEFAULT_MAX_TRAFFIC = 10000;
const DEFAULT_MAX_HASH = 4294967296; // 2 ** 32

function murmurhash3_32(key, seed) {
  return murmurhash.v3(String(key), seed);
}

function getBucketValueForVisitor(visitorId, experienceId, seed = DEFAULT_HASH_SEED) {
  const composite = `${experienceId}${visitorId}`;
  const hashValue = murmurhash3_32(composite, seed);
  return Math.trunc((hashValue / DEFAULT_MAX_HASH) * DEFAULT_MAX_TRAFFIC);
}

function selectBucket(buckets, value, redistribute = 0) {
  // buckets: array of [bucketId, percentage] in iteration order.
  let cumulative = 0;
  for (const [bucketId, percentage] of buckets) {
    cumulative += percentage * 100 + redistribute;
    if (value < cumulative) return bucketId;
  }
  return null;
}

module.exports = {
  murmurhash3_32,
  getBucketValueForVisitor,
  selectBucket,
  DEFAULT_HASH_SEED,
  DEFAULT_MAX_TRAFFIC,
  DEFAULT_MAX_HASH
};
