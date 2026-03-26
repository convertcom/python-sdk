from enum import Enum


class RuleError(str, Enum):
    NO_DATA_FOUND = "convert.com_no_data_found"
    NEED_MORE_DATA = "convert.com_need_more_data"


class BucketingError(str, Enum):
    VARIAION_NOT_DECIDED = "convert.com_variation_not_decided"


class FeatureStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class VariationChangeType(str, Enum):
    FULLSTACK_FEATURE = "fullStackFeature"


class SegmentsKeys(str, Enum):
    COUNTRY = "country"
    BROWSER = "browser"
    DEVICES = "devices"
    SOURCE = "source"
    CAMPAIGN = "campaign"
    VISITOR_TYPE = "visitorType"
    CUSTOM_SEGMENTS = "customSegments"


class SystemEvents(str, Enum):
    READY = "ready"
    CONFIG_UPDATED = "config.updated"
    API_QUEUE_RELEASED = "api.queue.released"
    BUCKETING = "bucketing"
    CONVERSION = "conversion"
    SEGMENTS = "segments"
    LOCATION_ACTIVATED = "location.activated"
    LOCATION_DEACTIVATED = "location.deactivated"
    AUDIENCES = "audiences"
    DATA_STORE_QUEUE_RELEASED = "datastore.queue.released"
