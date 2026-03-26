from enum import Enum


class RuleError(str, Enum):
    NO_DATA_FOUND = "convert.com_no_data_found"
    NEED_MORE_DATA = "convert.com_need_more_data"


class BucketingError(str, Enum):
    VARIAION_NOT_DECIDED = "convert.com_variation_not_decided"
