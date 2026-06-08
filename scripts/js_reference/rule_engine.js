/*
 * Faithful, dependency-free port of the Convert JavaScript SDK rule engine —
 * `RuleManager.isRuleMatched` (../javascript-sdk/packages/rules/src/rule-manager.ts)
 * and the `Comparisons` processor + `isNumeric`/`toNumber` helpers
 * (../javascript-sdk/packages/utils/src/comparisons.ts, string-utils.ts).
 *
 * This is a byte-faithful transcription of the JS reference source, NOT a
 * hand-authored set of golden values: it computes the reference answers by
 * RUNNING the same algorithm the JS SDK runs. It carries no npm dependencies so
 * it runs under a bare Node install at fixture-regeneration time only (never at
 * pytest time). Source of truth: javascript-sdk @ commit captured by the Python
 * orchestrator's `generated_from`.
 *
 * Exposes `isRuleMatched(data, ruleSet)` returning a strict boolean, mirroring
 * the JS default config (keys_case_sensitive = true, negation handled inside the
 * comparison via the `matching.negated` flag).
 */
'use strict';

// --- string-utils.ts: isNumeric / toNumber (faithful) ---------------------
function isNumeric(value) {
  const regex = /^-?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)$/;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value !== 'string' || !regex.test(value)) return false;
  const num = parseFloat(value.replace(/,/g, ''));
  return Number.isFinite(num);
}

function toNumber(value) {
  if (typeof value === 'number') return value;
  const parts = String(value).split(',');
  return parseFloat(
    parts[0] == '0'
      ? String(value).replace(/,/g, '.')
      : String(value).replace(/,/g, '')
  );
}

// --- object-utils.ts / array-utils.ts (faithful) --------------------------
function objectNotEmpty(object) {
  return (
    typeof object === 'object' &&
    object !== null &&
    Object.keys(object).length > 0
  );
}
function arrayNotEmpty(array) {
  return Array.isArray(array) && array.length > 0;
}

// --- comparisons.ts: Comparisons (faithful subset used by FullStack rules) -
const Comparisons = {
  _returnNegationCheck(value, negation = false) {
    return negation ? !value : value;
  },
  equals(value, testAgainst, negation) {
    if (Array.isArray(value))
      return this._returnNegationCheck(value.indexOf(testAgainst) !== -1, negation);
    if (objectNotEmpty(value))
      return this._returnNegationCheck(
        Object.keys(value).indexOf(String(testAgainst)) !== -1,
        negation
      );
    value = String(value).valueOf().toLowerCase();
    testAgainst = String(testAgainst).valueOf().toLowerCase();
    return this._returnNegationCheck(value === testAgainst, negation);
  },
  less(value, testAgainst, negation) {
    value = isNumeric(value) ? toNumber(value) : value;
    testAgainst = isNumeric(testAgainst) ? toNumber(testAgainst) : testAgainst;
    if (typeof value !== typeof testAgainst) return false;
    return this._returnNegationCheck(value < testAgainst, negation);
  },
  lessEqual(value, testAgainst, negation) {
    value = isNumeric(value) ? toNumber(value) : value;
    testAgainst = isNumeric(testAgainst) ? toNumber(testAgainst) : testAgainst;
    if (typeof value !== typeof testAgainst) return false;
    return this._returnNegationCheck(value <= testAgainst, negation);
  },
  contains(value, testAgainst, negation) {
    value = String(value).valueOf().toLowerCase();
    testAgainst = String(testAgainst).valueOf().toLowerCase();
    if (testAgainst.replace(/^([\s]*)|([\s]*)$/g, '').length === 0)
      return this._returnNegationCheck(true, negation);
    return this._returnNegationCheck(value.indexOf(testAgainst) !== -1, negation);
  },
  startsWith(value, testAgainst, negation) {
    value = String(value).valueOf().toLowerCase();
    testAgainst = String(testAgainst).valueOf().toLowerCase();
    return this._returnNegationCheck(value.indexOf(testAgainst) === 0, negation);
  },
  endsWith(value, testAgainst, negation) {
    value = String(value).valueOf().toLowerCase();
    testAgainst = String(testAgainst).valueOf().toLowerCase();
    return this._returnNegationCheck(
      value.indexOf(testAgainst, value.length - testAgainst.length) !== -1,
      negation
    );
  },
  exists(value, _testAgainst, negation) {
    const valueExists = value !== undefined && value !== null && value !== '';
    return this._returnNegationCheck(valueExists, negation);
  },
  not_exists(value, _testAgainst, negation) {
    const valueNotExists = value === undefined || value === null || value === '';
    return this._returnNegationCheck(valueNotExists, negation);
  }
};
// Aliases mirroring the JS static-property aliases.
Comparisons.equalsNumber = Comparisons.equals;
Comparisons.matches = Comparisons.equals;
Comparisons.doesNotExist = Comparisons.not_exists;

const EXISTENCE = new Set(['exists', 'not_exists', 'doesNotExist']);

// --- rule-manager.ts: isRuleMatched (faithful, default config) ------------
function isValidRule(rule) {
  const hasMatching =
    rule && typeof rule.matching === 'object' &&
    typeof rule.matching.match_type === 'string' &&
    typeof rule.matching.negated === 'boolean';
  if (!hasMatching) return false;
  const matchType = rule.matching.match_type;
  if (matchType === 'exists' || matchType === 'not_exists' || matchType === 'doesNotExist')
    return true;
  return Object.prototype.hasOwnProperty.call(rule, 'value');
}

function processRuleItem(data, rule) {
  if (!isValidRule(rule)) return false;
  const negation = rule.matching.negated || false;
  const matching = rule.matching.match_type;
  if (typeof Comparisons[matching] !== 'function') return false;
  if (data && typeof data === 'object') {
    if (objectNotEmpty(data)) {
      for (const key of Object.keys(data)) {
        // default keys_case_sensitive = true -> strict key compare
        if (key === rule['key']) {
          return Comparisons[matching](data[key], rule.value, negation);
        }
      }
    }
    if (EXISTENCE.has(matching)) {
      return Comparisons[matching](undefined, rule.value, negation);
    }
  }
  return false;
}

function processORWHEN(data, subset) {
  if (!subset || !arrayNotEmpty(subset.OR_WHEN)) return false;
  let match;
  for (const item of subset.OR_WHEN) {
    match = processRuleItem(data, item);
    if (match === true) return true;
  }
  return match === false ? false : false;
}

function processAND(data, subset) {
  if (!subset || !arrayNotEmpty(subset.AND)) return false;
  for (const block of subset.AND) {
    const match = processORWHEN(data, block);
    if (match !== true) return false;
  }
  return true;
}

function isRuleMatched(data, ruleSet) {
  if (!ruleSet || !arrayNotEmpty(ruleSet.OR)) return false;
  let match;
  for (const branch of ruleSet.OR) {
    match = processAND(data, branch);
    if (match === true) return true;
  }
  return match !== false ? !!match : false;
}

module.exports = {isRuleMatched, Comparisons, isNumeric, toNumber};
