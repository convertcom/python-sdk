/*
 * Faithful, dependency-free port of the bucketing hash + visitor-based bucket
 * selection from the Convert JavaScript SDK
 * (../javascript-sdk/packages/bucketing/src/bucketing-manager.ts and the npm
 * `murmurhash` v3 algorithm imported via packages/utils/src/string-utils.ts
 * `generateHash`, default seed 9999).
 *
 * Byte-faithful transcription of the JS reference algorithm — the reference
 * answers are COMPUTED, never hand-authored. No npm dependency: runs under a
 * bare Node install at fixture-regeneration time only.
 */
'use strict';

const DEFAULT_HASH_SEED = 9999;
const DEFAULT_MAX_TRAFFIC = 10000;
const DEFAULT_MAX_HASH = 4294967296; // 2 ** 32

function murmurhash3_32(key, seed) {
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
