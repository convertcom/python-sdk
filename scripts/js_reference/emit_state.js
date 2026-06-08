/*
 * Emits machine-derived Epic-3 state / entity-lookup + custom-segment vectors
 * (JSON array on stdout) by RUNNING faithful JS-reference ports of
 * DataManager._getEntityByField / getEntity / getEntityById / getEntities
 * (../javascript-sdk/packages/data/src/data-manager.ts) and
 * SegmentsManager.setCustomSegments (packages/segments/src/segments-manager.ts,
 * delegating to the rule_engine.js RuleManager port).
 *
 * `expected` is the JS reference result — computed, never hand-authored. The
 * no-match contract is encoded as Story 3.4 actually ships it: JS `null` ->
 * Python `None` (single) / empty `[]` (multi); multi-key/id skips non-matches
 * (no null placeholders). NOT the deferred FR50 typed-reason object.
 */
'use strict';
const {isRuleMatched} = require('./rule_engine');

// --- DataManager._getEntityByField (faithful): linear scan, String-equality,
//     null on no match ----------------------------------------------------
function getEntitiesList(config, entityType) {
  return config[entityType] || [];
}
function getEntityByField(config, identity, entityType, field) {
  const list = getEntitiesList(config, entityType);
  if (Array.isArray(list) && list.length) {
    for (const item of list) {
      if (item && String(item[field]) === String(identity)) return item;
    }
  }
  return null;
}
function getEntity(config, key, entityType) {
  return getEntityByField(config, key, entityType, 'key');
}
function getEntityById(config, id, entityType) {
  return getEntityByField(config, id, entityType, 'id');
}
function getEntities(config, keys, entityType) {
  const out = [];
  for (const key of keys) {
    const e = getEntity(config, key, entityType);
    if (e) out.push(e); // skip non-matches; no null placeholders
  }
  return out;
}

// --- SegmentsManager.setCustomSegments (faithful subset; no persisted store
//     so customSegments starts empty) -------------------------------------
function selectCustomSegments(config, segmentKeys, segmentRule) {
  const segments = getEntities(config, segmentKeys, 'segments');
  const customSegments = [];
  const segmentIds = [];
  let segmentsMatched = false;
  for (const segment of segments) {
    if (segmentRule && !segmentsMatched) {
      segmentsMatched = isRuleMatched(segmentRule, segment && segment.rules);
    }
    if (!segmentRule || segmentsMatched) {
      const segmentId = segment && segment.id != null ? String(segment.id) : undefined;
      if (segmentId === undefined) continue;
      if (customSegments.includes(segmentId) || segmentIds.includes(segmentId)) continue;
      segmentIds.push(segmentId);
    }
  }
  return segmentIds;
}

// --- Shared config (input to BOTH SDKs) ------------------------------------
const config = {
  account_id: '100123',
  project: {id: '200456', key: 'proj-key'},
  experiences: [
    {id: 'e1', key: 'exp-one', variations: [{id: 'v1', key: 'var-one'}]},
    {id: 'e2', key: 'exp-two', variations: []}
  ],
  features: [{id: 'f1', key: 'feat-one', variables: []}],
  goals: [{id: 'g1', key: 'goal-one'}, {id: 'g2', key: 'goal-two'}],
  audiences: [{id: 'a1', key: 'aud-one'}],
  segments: [
    {id: 's1', key: 'seg-ruleless'},
    {
      id: 's2',
      key: 'seg-country-us',
      rules: {
        OR: [{AND: [{OR_WHEN: [
          {matching: {match_type: 'equals', negated: false}, key: 'country', value: 'US'}
        ]}]}]
      }
    }
  ]
};

// --- by-key / by-id / multi-key entity-lookup vectors ----------------------
const lookupCases = [
  // single by-key hits across all five entity types
  ['key_experiences_hit', {op: 'get_entity', entity_type: 'experiences', key: 'exp-one'}],
  ['key_features_hit', {op: 'get_entity', entity_type: 'features', key: 'feat-one'}],
  ['key_goals_hit', {op: 'get_entity', entity_type: 'goals', key: 'goal-one'}],
  ['key_audiences_hit', {op: 'get_entity', entity_type: 'audiences', key: 'aud-one'}],
  ['key_segments_hit', {op: 'get_entity', entity_type: 'segments', key: 'seg-ruleless'}],
  // single by-key misses
  ['key_unknown_miss', {op: 'get_entity', entity_type: 'experiences', key: 'nope'}],
  ['key_wrong_type_miss', {op: 'get_entity', entity_type: 'goals', key: 'exp-one'}],
  // single by-id hits + misses
  ['id_experiences_hit', {op: 'get_entity_by_id', entity_type: 'experiences', id: 'e1'}],
  ['id_features_hit', {op: 'get_entity_by_id', entity_type: 'features', id: 'f1'}],
  ['id_unknown_miss', {op: 'get_entity_by_id', entity_type: 'features', id: 'zz'}],
  // multi-key: all match, partial (skip unknown), all unknown (empty)
  ['multi_all_match', {op: 'get_entities', entity_type: 'goals', keys: ['goal-one', 'goal-two']}],
  ['multi_partial_skip_unknown', {op: 'get_entities', entity_type: 'goals', keys: ['goal-one', 'nope']}],
  ['multi_all_unknown_empty', {op: 'get_entities', entity_type: 'goals', keys: ['x', 'y']}],
  ['multi_empty_keys_empty', {op: 'get_entities', entity_type: 'goals', keys: []}]
];

function runLookup(op) {
  if (op.op === 'get_entity') {
    const e = getEntity(config, op.key, op.entity_type);
    return e == null ? null : (e.id != null ? String(e.id) : null);
  }
  if (op.op === 'get_entity_by_id') {
    const e = getEntityById(config, op.id, op.entity_type);
    return e == null ? null : (e.id != null ? String(e.id) : null);
  }
  if (op.op === 'get_entities') {
    return getEntities(config, op.keys, op.entity_type).map((e) => String(e.id));
  }
  throw new Error(`unknown op ${op.op}`);
}

// --- custom-segment vectors (Python/JS provably agree: rule-less, single
//     match, no-match) -------------------------------------------------------
const segmentCases = [
  ['segment_ruleless_unconditional', {op: 'select_custom_segments', segment_keys: ['seg-ruleless'], segment_rule: null}],
  ['segment_rule_match', {op: 'select_custom_segments', segment_keys: ['seg-country-us'], segment_rule: {country: 'US'}}],
  ['segment_rule_no_match', {op: 'select_custom_segments', segment_keys: ['seg-country-us'], segment_rule: {country: 'CA'}}],
  ['segment_unknown_key_empty', {op: 'select_custom_segments', segment_keys: ['nope'], segment_rule: null}]
];

function runSegment(op) {
  return selectCustomSegments(config, op.segment_keys, op.segment_rule);
}

const vectors = [];
for (const [id, op] of lookupCases) {
  vectors.push({id, config, operation: op, expected: runLookup(op)});
}
for (const [id, op] of segmentCases) {
  vectors.push({id, config, operation: op, expected: runSegment(op)});
}
process.stdout.write(JSON.stringify(vectors));
