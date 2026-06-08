Add missing `isIn` and `regexMatches` comparison operators to the rule evaluation engine.

These two operators were previously absent from the `_COMPARATORS` dispatch map, causing any Convert config that used an "is in list" or regular-expression audience rule to silently never match in Python (the engine returned `False` for unknown `match_type` values). Both operators now mirror the JS SDK and PHP SDK reference implementations exactly: pipe-delimited value splitting, case-insensitive matching, invalid-regex-returns-false safety, and full negation support.
