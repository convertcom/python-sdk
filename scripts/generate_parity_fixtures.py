"""Generate checked-in JavaScript parity fixtures for the Python SDK test suite."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JS_SDK_ROOT = REPO_ROOT.parent / "javascript-sdk"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "tests" / "parity" / "fixtures"
FIXTURE_FILES = (
    "bucketing_vectors.json",
    "feature_vectors.json",
    "rule_vectors.json",
    "state_vectors.json",
)

JS_EXPORT_SCRIPT = r"""
const path = require("path");

const packageRoot = process.cwd();
const ConvertModule = require(path.join(packageRoot, "index.ts"));
const ConvertSDK = ConvertModule.default;
const { EntityType } = ConvertModule;
const testConfig = require(path.join(packageRoot, "tests/test-config.json"));

process.on("warning", () => {});
const stdout = process.stdout.write.bind(process.stdout);
console.log = () => {};
console.error = () => {};

function createSdk() {
  return new ConvertSDK({
    data: testConfig.data,
    environment: testConfig.environment,
    api: {
      endpoint: {
        config: "http://127.0.0.1:1",
        track: "http://127.0.0.1:1",
      },
    },
    network: {
      tracking: false,
    },
    events: {
      batch_size: 50,
      release_interval: 86400000,
    },
    logger: {
      logLevel: 5,
      customLoggers: [],
    },
  });
}

async function createContext(visitorId, visitorAttributes) {
  const sdk = createSdk();
  await sdk.onReady();
  return {
    sdk,
    context: sdk.createContext(visitorId, visitorAttributes || {}),
  };
}

function normalizeExperience(result) {
  if (!result) {
    return null;
  }
  return {
    experience_id: String(result.experienceId),
    experience_key: String(result.experienceKey),
    variation_id: String(result.id),
    variation_key: String(result.key),
  };
}

function normalizeFeature(result) {
  if (!result || result.status !== "enabled") {
    return {
      matched: false,
    };
  }
  return {
    matched: true,
    experience_id: String(result.experienceId),
    experience_key: String(result.experienceKey),
    feature_id: String(result.id),
    feature_key: String(result.key),
    status: String(result.status),
    variables: result.variables,
  };
}

function normalizeSegmentMatches(dataManager, visitorId, data) {
  const tracked = dataManager.getData(visitorId) || {};
  const matchedIds = tracked.segments?.customSegments || [];
  const byId = new Map(
    (data.segments || []).map((segment) => [String(segment.id), String(segment.key)])
  );
  return {
    matched_segment_keys: matchedIds.map((segmentId) => byId.get(String(segmentId))).filter(Boolean),
  };
}

function normalizeEntity(entity) {
  if (!entity) {
    return null;
  }
  return {
    id: String(entity.id),
    key: String(entity.key),
  };
}

async function main() {
  const shared = {
    source: {
      javascript_sdk_root: "../javascript-sdk/packages/js-sdk",
      javascript_config: "tests/test-config.json",
      generation_command: "uv run python scripts/generate_parity_fixtures.py",
    },
    environment: testConfig.environment,
    config_data: testConfig.data,
  };

  const bucketing = await createContext("XXX", {
    browser: "chrome",
    country: "US",
  });
  const bucketingVariant = bucketing.context.runExperience("test-experience-ab-fullstack-2", {
    locationProperties: { url: "https://convert.com/" },
    visitorProperties: { varName3: "something" },
  });

  const secondBucket = await createContext("visitor-1", {
    browser: "chrome",
    country: "US",
  });
  const secondVariant = secondBucket.context.runExperience("test-experience-ab-fullstack-2", {
    locationProperties: { url: "https://convert.com/" },
    visitorProperties: { varName3: "something" },
  });

  const featureEnabled = await createContext("XXX", {
    browser: "chrome",
    country: "US",
  });
  const enabledFeature = featureEnabled.context.runFeature("feature-2", {
    locationProperties: { url: "https://convert.com/" },
    visitorProperties: { varName3: "something" },
  });

  const featureNoMatch = await createContext("XXX", {
    browser: "chrome",
    country: "US",
  });
  const disabledFeature = featureNoMatch.context.runFeature("feature-2");

  const segmentMatch = await createContext("XXX", {
    browser: "chrome",
    country: "US",
  });
  segmentMatch.context.runCustomSegments(["test-segments-1"], {
    ruleData: { enabled: true },
  });

  const segmentMiss = await createContext("XXX", {
    browser: "chrome",
    country: "US",
  });
  segmentMiss.context.runCustomSegments(["test-segments-1"], {
    ruleData: { enabled: false },
  });

  const entityLookup = await createContext("XXX", {
    browser: "chrome",
    country: "US",
  });

  const payload = {
    bucketing_vectors: {
      ...shared,
      scenarios: [
        {
          name: "ab_fullstack_original_page_for_xxx",
          visitor_id: "XXX",
          context_visitor_attributes: {
            browser: "chrome",
            country: "US",
          },
          request_visitor_attributes: {
            varName3: "something",
          },
          location_attributes: {
            url: "https://convert.com/",
          },
          experience_key: "test-experience-ab-fullstack-2",
          expected: normalizeExperience(bucketingVariant),
        },
        {
          name: "ab_fullstack_variation_one_for_visitor_1",
          visitor_id: "visitor-1",
          context_visitor_attributes: {
            browser: "chrome",
            country: "US",
          },
          request_visitor_attributes: {
            varName3: "something",
          },
          location_attributes: {
            url: "https://convert.com/",
          },
          experience_key: "test-experience-ab-fullstack-2",
          expected: normalizeExperience(secondVariant),
        },
      ],
    },
    feature_vectors: {
      ...shared,
      scenarios: [
        {
          name: "feature_2_enabled_from_original_page",
          visitor_id: "XXX",
          context_visitor_attributes: {
            browser: "chrome",
            country: "US",
          },
          request_visitor_attributes: {
            varName3: "something",
          },
          location_attributes: {
            url: "https://convert.com/",
          },
          feature_key: "feature-2",
          expected: normalizeFeature(enabledFeature),
        },
        {
          name: "feature_2_not_matched_without_request_context",
          visitor_id: "XXX",
          context_visitor_attributes: {
            browser: "chrome",
            country: "US",
          },
          request_visitor_attributes: {},
          location_attributes: {},
          feature_key: "feature-2",
          expected: normalizeFeature(disabledFeature),
        },
      ],
    },
    rule_vectors: {
      ...shared,
      scenarios: [
        {
          name: "custom_segment_matches_when_enabled_true",
          visitor_id: "XXX",
          context_visitor_attributes: {
            browser: "chrome",
            country: "US",
          },
          segment_keys: ["test-segments-1"],
          rule_data: {
            enabled: true,
          },
          expected: normalizeSegmentMatches(segmentMatch.sdk._dataManager, "XXX", testConfig.data),
        },
        {
          name: "custom_segment_does_not_match_when_enabled_false",
          visitor_id: "XXX",
          context_visitor_attributes: {
            browser: "chrome",
            country: "US",
          },
          segment_keys: ["test-segments-1"],
          rule_data: {
            enabled: false,
          },
          expected: normalizeSegmentMatches(segmentMiss.sdk._dataManager, "XXX", testConfig.data),
        },
      ],
    },
    state_vectors: {
      ...shared,
      scenarios: [
        {
          name: "entity_lookup_by_key_and_id",
          visitor_id: "XXX",
          context_visitor_attributes: {
            browser: "chrome",
            country: "US",
          },
          lookups_by_key: [
            {
              label: "audience",
              entity_type: "audience",
              lookup_key: "adv-audience",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntity("adv-audience", EntityType.AUDIENCE)
              ),
            },
            {
              label: "segment",
              entity_type: "segment",
              lookup_key: "test-segments-1",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntity("test-segments-1", EntityType.SEGMENT)
              ),
            },
            {
              label: "feature",
              entity_type: "feature",
              lookup_key: "feature-2",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntity("feature-2", EntityType.FEATURE)
              ),
            },
            {
              label: "goal",
              entity_type: "goal",
              lookup_key: "adv-goal-country-browser",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntity(
                  "adv-goal-country-browser",
                  EntityType.GOAL
                )
              ),
            },
            {
              label: "experience",
              entity_type: "experience",
              lookup_key: "test-experience-ab-fullstack-3",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntity(
                  "test-experience-ab-fullstack-3",
                  EntityType.EXPERIENCE
                )
              ),
            },
            {
              label: "variation",
              entity_type: "variation",
              lookup_key: "100299461-variation-1",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntity(
                  "100299461-variation-1",
                  EntityType.VARIATION
                )
              ),
            },
          ],
          lookups_by_id: [
            {
              label: "audience",
              entity_type: "audience",
              entity_id: "100299433",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntityById("100299433", EntityType.AUDIENCE)
              ),
            },
            {
              label: "segment",
              entity_type: "segment",
              entity_id: "200299434",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntityById("200299434", EntityType.SEGMENT)
              ),
            },
            {
              label: "feature",
              entity_type: "feature",
              entity_id: "10025",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntityById("10025", EntityType.FEATURE)
              ),
            },
            {
              label: "goal",
              entity_type: "goal",
              entity_id: "100215961",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntityById("100215961", EntityType.GOAL)
              ),
            },
            {
              label: "experience",
              entity_type: "experience",
              entity_id: "100218246",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntityById("100218246", EntityType.EXPERIENCE)
              ),
            },
            {
              label: "variation",
              entity_type: "variation",
              entity_id: "100299461",
              expected: normalizeEntity(
                entityLookup.context.getConfigEntityById("100299461", EntityType.VARIATION)
              ),
            },
          ],
        },
      ],
    },
  };

  stdout(JSON.stringify(payload));
  process.exit(0);
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate checked-in parity fixtures from the sibling JavaScript SDK repo."
    )
    parser.add_argument(
        "--javascript-sdk-root",
        type=Path,
        default=DEFAULT_JS_SDK_ROOT,
        help="Path to the sibling javascript-sdk repository.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where parity fixture JSON files should be written.",
    )
    return parser.parse_args()


def export_js_reference_payload(javascript_sdk_root: Path) -> dict[str, Any]:
    package_root = javascript_sdk_root / "packages" / "js-sdk"
    if not package_root.is_dir():
        raise FileNotFoundError(
            f"JavaScript SDK package root not found: {package_root}"
        )

    env = dict(os.environ)
    env.setdefault("NODE_NO_WARNINGS", "1")
    result = subprocess.run(
        ["node", "-r", "ts-node/register", "-e", JS_EXPORT_SCRIPT],
        cwd=package_root,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(result.stdout)


def write_fixture_files(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for fixture_name in FIXTURE_FILES:
        fixture_payload = payload[fixture_name.replace(".json", "")]
        fixture_path = output_dir / fixture_name
        fixture_path.write_text(
            json.dumps(fixture_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    args = parse_args()
    payload = export_js_reference_payload(args.javascript_sdk_root.resolve())
    write_fixture_files(args.output_dir.resolve(), payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
