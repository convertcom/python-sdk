# AUTO-GENERATED FROM backend apiDoc/serving — DO NOT EDIT. Regenerate via the serving workflow.

# TypedDict stubs for the Convert serving config response.
# Generated from dist/types.gen.ts (already discriminator-corrected by fix-discriminants.js).
# Entity field sets are REFLECTED from the TypeScript AST (qs-03 D1 / F14) — never
# hand-listed. A backend field rename/removal changes the reflected TypedDict, which
# the python-sdk contract probe catches via mypy/pyright on the probe that subscripts
# the renamed/removed key. Discriminator unions (goal_type, ga_integration_type,
# feature_variable_type) are sourced from the corrected TS and preserved per-variant
# (ConfigGoal admits all 10 type values — AC4).
#
# All TypedDict classes use total=False so every field is Optional — real config
# carrying extra/undeclared fields never false-positives (AC2). The probe binds
# SYNTHETIC values and accesses only the spec-declared fields the SDK depends on.
# TypedDict literal-key subscription (config["field"]) is the drift signal.

from __future__ import annotations

from typing import Any, List, Literal, Optional, TypedDict


class ConfigResponseData(TypedDict, total=False):
    account_id: Optional[str]
    project: Optional[ConfigProject]
    goals: Optional[List[ConfigGoal]]
    locations: Optional[List[ConfigLocation]]
    audiences: Optional[List[ConfigAudience]]
    segments: Optional[List[ConfigSegment]]
    experiences: Optional[List[ConfigExperience]]
    archived_experiences: Optional[List[str]]
    features: Optional[List[ConfigFeature]]
    is_debug: Optional[bool]

class ConfigProjectCustomDomain(TypedDict, total=False):
    domain: Optional[str]
    version: Optional[str]

class ConfigProjectDomains(TypedDict, total=False):
    tld: Optional[str]
    hosts: Optional[Any]

class ConfigProjectSettingsIntegrationsVisitorInsights(TypedDict, total=False):
    tracking_id: Optional[Any]

class ConfigProjectSettingsIntegrationsKissmetrics(TypedDict, total=False):
    enabled: Optional[bool]

class ConfigProjectSettingsIntegrations(TypedDict, total=False):
    google_analytics: Optional[Any]
    visitor_insights: Optional[ConfigProjectSettingsIntegrationsVisitorInsights]
    kissmetrics: Optional[ConfigProjectSettingsIntegrationsKissmetrics]

class ConfigProjectSettingsOutliers(TypedDict, total=False):
    order_value: Optional[Any]
    products_ordered_count: Optional[Any]

class ConfigProjectSettings(TypedDict, total=False):
    allow_crossdomain_tracking: Optional[bool]
    data_anonymization: Optional[bool]
    do_not_track: Optional[str]
    global_privacy_control: Optional[str]
    do_not_track_referral: Optional[bool]
    integrations: Optional[ConfigProjectSettingsIntegrations]
    min_order_value: Optional[float]
    max_order_value: Optional[float]
    outliers: Optional[ConfigProjectSettingsOutliers]
    placeholders: Optional[List[str]]
    global_javascript_placeholders: Optional[List[str]]
    include_jquery: Optional[bool]
    include_jquery_v1: Optional[bool]
    disable_spa_functionality: Optional[bool]
    version: Optional[str]
    tracking_script: Optional[Any]

class ConfigProject(TypedDict, total=False):
    id: Optional[str]
    name: Optional[str]
    type: Optional[str]
    utc_offset: Optional[Any]
    custom_domain: Optional[ConfigProjectCustomDomain]
    domains: Optional[List[ConfigProjectDomains]]
    global_javascript: Optional[str]
    settings: Optional[ConfigProjectSettings]

class ConfigExperienceSettingsOutliers(TypedDict, total=False):
    order_value: Optional[Any]
    products_ordered_count: Optional[Any]

class ConfigExperienceSettingsSplitUrlSettings(TypedDict, total=False):
    split_regex_support: Optional[bool]

class ConfigExperienceSettingsMatchingOptions(TypedDict, total=False):
    audiences: Optional[Any]
    locations: Optional[Any]

class ConfigExperienceSettings(TypedDict, total=False):
    min_order_value: Optional[float]
    max_order_value: Optional[float]
    outliers: Optional[ConfigExperienceSettingsOutliers]
    placeholders: Optional[List[str]]
    split_url_settings: Optional[ConfigExperienceSettingsSplitUrlSettings]
    matching_options: Optional[ConfigExperienceSettingsMatchingOptions]

class ConfigExperience(TypedDict, total=False):
    id: Optional[str]
    name: Optional[str]
    key: Optional[str]
    locations: Optional[List[str]]
    site_area: Optional[Any]
    audiences: Optional[List[str]]
    goals: Optional[List[str]]
    multipage_pages: Optional[List[Any]]
    status: Optional[Any]
    global_js: Optional[str]
    global_css: Optional[str]
    type: Optional[Any]
    version: Optional[float]
    variations: Optional[List[ExperienceVariation]]
    integrations: Optional[List[Any]]
    environments: Optional[List[str]]
    environment: Optional[str]
    settings: Optional[ConfigExperienceSettings]

class ExperienceVariation(TypedDict, total=False):
    id: Optional[str]
    name: Optional[str]
    key: Optional[str]
    traffic_allocation: Optional[float]
    status: Optional[Any]
    changes: Optional[List[FeatureChangeData]]

class FeatureChangeDataData(TypedDict, total=False):
    feature_id: Optional[float]
    variables_data: Optional[Any]

class FeatureChangeData(TypedDict, total=False):
    id: Optional[float]
    type: Optional[str]
    data: Optional[FeatureChangeDataData]

class ConfigGoal(TypedDict, total=False):
    id: Optional[str]
    name: Optional[str]
    key: Optional[str]
    type: Optional[Literal["dom_interaction", "scroll_percentage", "revenue", "advanced", "visits_page", "code_trigger", "ga_import", "submits_form", "clicks_link", "clicks_element"]]
    rules: Optional[Any]

class ConfigAudience(TypedDict, total=False):
    id: Optional[str]
    key: Optional[str]
    name: Optional[str]
    type: Optional[Any]
    rules: Optional[Any]

class ConfigLocation(TypedDict, total=False):
    id: Optional[str]
    key: Optional[str]
    name: Optional[str]
    trigger: Optional[Any]
    rules: Optional[Any]

class ConfigSegment(TypedDict, total=False):
    id: Optional[str]
    key: Optional[str]
    name: Optional[str]
    rules: Optional[Any]

class ConfigFeature(TypedDict, total=False):
    id: Optional[str]
    name: Optional[str]
    key: Optional[str]
    variables: Optional[List[FeatureVariable]]

class FeatureVariable(TypedDict, total=False):
    key: Optional[str]
    type: Optional[Literal["boolean", "float", "json", "integer", "string"]]

class ExperienceIntegrationGaServing(TypedDict, total=False):
    enabled: Optional[bool]
    provider: Optional[Any]
    type: Optional[Literal["ga3", "ga4"]]
    measurementId: Optional[str]

class GaSettings(TypedDict, total=False):
    enabled: Optional[bool]
    auto_revenue_tracking: Optional[bool]
    track_first_exposure_only: Optional[bool]
    type: Optional[Literal["ga3", "ga4"]]
    measurementId: Optional[str]
    no_wait_pageview: Optional[bool]
