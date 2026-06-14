/*
 * Emits machine-derived bucketing hash vectors (JSON array on stdout) using the
 * faithful JS-reference port in ./bucketing.js. Input classes mirror the qs-04
 * I/O matrix: ASCII, Unicode, empty, numeric-string, and the
 * `${experience_id}${visitor_id}` composite — at seed 9999 plus alternates.
 */
'use strict';
const {murmurhash3_32} = require('./bucketing');

const inputs = [
  '', 'a', 'ab', 'abc', 'abcd', 'test_visitor', '用户123',
  'café', '🎯emoji',
  'the quick brown fox', '0', '12345',
  'e1visitor-1', 'e2visitor-1', '100456visitor_42',
  'visitor-aaaaaaaa', 'visitor-zzzzzzzz',
  'exp_100visitor_001', 'exp_100visitor_002', 'exp_100visitor_999'
];
const seeds = [9999, 0, 1, 12345];

const vectors = [];
for (const seed of seeds) {
  for (const value of inputs) {
    vectors.push({value, seed, expected: murmurhash3_32(value, seed)});
  }
}
process.stdout.write(JSON.stringify(vectors));
