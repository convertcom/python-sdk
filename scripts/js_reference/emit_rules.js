/*
 * Emits machine-derived rule-evaluation vectors (JSON array on stdout) by
 * RUNNING the faithful JS-reference RuleManager port in ./rule_engine.js over a
 * matrix of (data, rule) inputs covering every comparison operator the Python
 * `is_rule_matched` surface supports, plus negation, nested AND/OR_WHEN,
 * missing-data, and numeric/string type-mismatch edges.
 *
 * `expected` is the JS reference boolean — computed, never hand-authored. Each
 * vector is self-describing so the parametrized parity test names the divergent
 * (id, data, rule) triple on failure.
 */
'use strict';
const {isRuleMatched} = require('./rule_engine');

// A single-operator rule set: OR -> AND -> OR_WHEN -> one item.
function rule(matchType, key, value, negated = false) {
  return {
    OR: [
      {
        AND: [
          {
            OR_WHEN: [
              {matching: {match_type: matchType, negated}, key, value}
            ]
          }
        ]
      }
    ]
  };
}

// A two-branch AND rule set (both OR_WHEN blocks must match).
function andRule(items) {
  return {
    OR: [
      {
        AND: items.map((it) => ({
          OR_WHEN: [
            {matching: {match_type: it.op, negated: it.neg || false}, key: it.key, value: it.value}
          ]
        }))
      }
    ]
  };
}

const cases = [
  // equals (case-insensitive)
  ['equals_hit_ci', {country: 'us'}, rule('equals', 'country', 'US')],
  ['equals_miss', {country: 'CA'}, rule('equals', 'country', 'US')],
  ['equals_negated_hit', {country: 'ca'}, rule('equals', 'country', 'US', true)],
  ['equals_negated_miss', {country: 'us'}, rule('equals', 'country', 'US', true)],
  ['equalsNumber_alias', {age: '30'}, rule('equalsNumber', 'age', '30')],
  ['matches_alias', {plan: 'PRO'}, rule('matches', 'plan', 'pro')],
  // contains / startsWith / endsWith
  ['contains_hit', {url: 'https://shop/CHECKOUT/cart'}, rule('contains', 'url', 'checkout')],
  ['contains_miss', {url: 'https://shop/home'}, rule('contains', 'url', 'checkout')],
  ['contains_empty_needle', {url: 'anything'}, rule('contains', 'url', '')],
  ['startsWith_hit', {path: '/Checkout/step1'}, rule('startsWith', 'path', '/checkout')],
  ['startsWith_miss', {path: '/home'}, rule('startsWith', 'path', '/checkout')],
  ['endsWith_hit', {file: 'REPORT.PDF'}, rule('endsWith', 'file', '.pdf')],
  ['endsWith_miss', {file: 'report.txt'}, rule('endsWith', 'file', '.pdf')],
  // less / lessEqual (numeric + type-mismatch)
  ['less_numeric_hit', {age: '17'}, rule('less', 'age', '18')],
  ['less_numeric_miss', {age: '21'}, rule('less', 'age', '18')],
  ['lessEqual_boundary_hit', {age: '18'}, rule('lessEqual', 'age', '18')],
  ['less_type_mismatch', {age: 'young'}, rule('less', 'age', '18')],
  // exists / not_exists / doesNotExist (incl. missing key)
  ['exists_present', {plan: 'pro'}, rule('exists', 'plan', '')],
  ['exists_missing_key', {other: 'x'}, rule('exists', 'plan', '')],
  ['exists_empty_value', {plan: ''}, rule('exists', 'plan', '')],
  ['not_exists_missing_key', {other: 'x'}, rule('not_exists', 'plan', '')],
  ['not_exists_present', {plan: 'pro'}, rule('not_exists', 'plan', '')],
  ['doesNotExist_alias_missing', {other: 'x'}, rule('doesNotExist', 'plan', '')],
  // nested AND (all branches must match)
  ['and_all_match', {country: 'us', plan: 'pro'},
    andRule([{op: 'equals', key: 'country', value: 'US'}, {op: 'equals', key: 'plan', value: 'pro'}])],
  ['and_one_miss', {country: 'us', plan: 'free'},
    andRule([{op: 'equals', key: 'country', value: 'US'}, {op: 'equals', key: 'plan', value: 'pro'}])],
  // multiple OR_WHEN items in a single block (any true)
  ['or_when_any_true', {tier: 'gold'},
    {OR: [{AND: [{OR_WHEN: [
      {matching: {match_type: 'equals', negated: false}, key: 'tier', value: 'silver'},
      {matching: {match_type: 'equals', negated: false}, key: 'tier', value: 'gold'}
    ]}]}]}],
  // empty/missing data
  ['empty_data_returns_false', {}, rule('equals', 'country', 'US')]
];

const vectors = cases.map(([id, data, ruleSet]) => ({
  id,
  data,
  rule: ruleSet,
  expected: isRuleMatched(data, ruleSet)
}));
process.stdout.write(JSON.stringify(vectors));
