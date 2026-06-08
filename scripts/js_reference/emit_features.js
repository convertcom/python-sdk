/*
 * Emits machine-derived feature-resolution vectors (JSON array on stdout) by
 * RUNNING the faithful JS-reference bucketing port (./bucketing.js) over shared
 * configs and replicating the JS feature-resolution path: find experiences whose
 * variation carries a `fullStackFeature` change for the feature, bucket the
 * visitor with the same composite-hash + selectBucket the JS SDK uses, and read
 * + cast `variables_data` by the declared variable types.
 *
 * `expected` is the JS reference result (status + cast variables, or null on a
 * miss) — computed, never hand-authored. Each vector carries the config + visitor
 * inputs the Python `resolve_feature` surface consumes, so parity is exercised
 * through the real Python pipeline (which runs the byte-identical Python hash).
 */
'use strict';
const {getBucketValueForVisitor, selectBucket} = require('./bucketing');

function isFullstackChange(change) {
  return String(change.type || '').toLowerCase() === 'fullstackfeature';
}

function featureChangeFor(variation, featureId) {
  for (const change of variation.changes || []) {
    if (!isFullstackChange(change)) continue;
    const data = change.data || {};
    if (String(data.feature_id) === String(featureId)) return data;
  }
  return null;
}

function castValue(value, declaredType) {
  if (declaredType == null) return value;
  const kind = String(declaredType).toLowerCase();
  try {
    if (kind === 'boolean') {
      if (typeof value === 'boolean') return value;
      return ['true', '1', 'yes'].includes(String(value).trim().toLowerCase());
    }
    if (kind === 'integer' || kind === 'int') return parseInt(value, 10);
    if (kind === 'float' || kind === 'double' || kind === 'number') return parseFloat(value);
    if (kind === 'string') return String(value);
    if (kind === 'json') {
      if (typeof value === 'object') return value;
      return JSON.parse(value);
    }
  } catch (e) {
    return value;
  }
  return value;
}

function variableTypes(feature) {
  const types = {};
  for (const v of feature.variables || []) {
    if (v.key != null && v.type != null) types[String(v.key)] = String(v.type);
  }
  return types;
}

function buildBuckets(experience) {
  // RUNNING variations with traffic_allocation > 0; missing allocation = 100%.
  const buckets = [];
  for (const variation of experience.variations || []) {
    const status = variation.status;
    const running = status == null || String(status).toLowerCase() === 'running';
    if (!running) continue;
    let alloc = variation.traffic_allocation;
    let hasTraffic;
    if (alloc == null) hasTraffic = true;
    else {
      const n = Number(alloc);
      hasTraffic = Number.isNaN(n) ? true : n > 0;
    }
    if (!hasTraffic) continue;
    if (!variation.id) continue;
    let pct = Number(alloc);
    if (alloc == null || Number.isNaN(pct)) pct = 100.0;
    buckets.push([String(variation.id), pct]);
  }
  return buckets;
}

function resolveFeature(config, featureKey, visitorId) {
  const feature = (config.features || []).find((f) => String(f.key) === String(featureKey));
  if (!feature) return null;
  const featureId = feature.id;
  if (featureId == null) return null;

  for (const experience of config.experiences || []) {
    // does this experience declare the feature change?
    let declares = false;
    for (const variation of experience.variations || []) {
      if (featureChangeFor(variation, featureId) != null) {
        declares = true;
        break;
      }
    }
    if (!declares) continue;

    // qualification: MVP configs here are unrestricted (no audiences/site_area).
    const audiences = experience.audiences || [];
    const siteArea = experience.site_area;
    if (siteArea || audiences.length) {
      // Restricted experiences are out of the feature-vector MVP matrix.
      continue;
    }

    const expId = experience.id;
    if (!expId) continue;
    const buckets = buildBuckets(experience);
    if (!buckets.length) continue;

    const value = getBucketValueForVisitor(String(visitorId), String(expId));
    const variationId = selectBucket(buckets, value);
    if (variationId == null) continue;

    const variation = (experience.variations || []).find((v) => String(v.id) === String(variationId));
    if (!variation) continue;
    const change = featureChangeFor(variation, featureId);
    if (change == null) continue;

    const types = variableTypes(feature);
    const rawVars = change.variables_data || {};
    const variables = {};
    for (const k of Object.keys(rawVars)) {
      variables[String(k)] = castValue(rawVars[k], types[String(k)]);
    }
    return {
      feature_key: String(feature.key != null ? feature.key : featureKey),
      feature_id: String(featureId),
      status: 'enabled',
      variables,
      experience_key: String(experience.key),
      variation_key: variation.key != null ? String(variation.key) : null
    };
  }
  return null;
}

// --- Shared configs (inputs to BOTH SDKs; the SDKs compute the result) -----
const enabledConfig = {
  account_id: '100123',
  project: {id: '200456'},
  features: [
    {
      id: '10024',
      key: 'checkout-banner',
      variables: [
        {key: 'enabled', type: 'boolean'},
        {key: 'caption', type: 'string'},
        {key: 'max_items', type: 'integer'},
        {key: 'meta', type: 'json'}
      ]
    }
  ],
  experiences: [
    {
      id: 'e1',
      key: 'banner-experiment',
      variations: [
        {
          id: 'v1',
          key: 'control',
          traffic_allocation: 100.0,
          changes: [
            {
              id: 'c1',
              type: 'fullStackFeature',
              data: {
                feature_id: '10024',
                variables_data: {
                  enabled: 'true',
                  caption: 'Hello',
                  max_items: '7',
                  meta: '{"a":1}'
                }
              }
            }
          ]
        }
      ]
    }
  ]
};

const undeclaredConfig = {
  account_id: '100123',
  project: {id: '200456'},
  features: [{id: '10099', key: 'orphan-feature', variables: []}],
  experiences: []
};

const cases = [
  ['enabled_with_cast_variables', enabledConfig, 'checkout-banner', 'visitor-feat-1'],
  ['enabled_other_visitor', enabledConfig, 'checkout-banner', 'visitor-feat-2'],
  ['undeclared_feature_miss', enabledConfig, 'no-such-feature', 'visitor-feat-1'],
  ['feature_without_experience_miss', undeclaredConfig, 'orphan-feature', 'visitor-feat-1']
];

const vectors = cases.map(([id, config, featureKey, visitorId]) => ({
  id,
  config,
  feature_key: featureKey,
  visitor_id: visitorId,
  expected: resolveFeature(config, featureKey, visitorId)
}));
process.stdout.write(JSON.stringify(vectors));
