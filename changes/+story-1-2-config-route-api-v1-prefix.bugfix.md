Fixed `HttpxTransport._build_route()` to emit `/api/v1/config/{sdkKey}` instead
of `/config/{sdkKey}`. The real Convert config-serving CDN returns 404 for the
old path and 200 for the correct `/api/v1/config/{sdkKey}` path (confirmed by
live staging test and the PHP SDK generated client). This only affects `sdk_key`
(remote) initialization; the `data=` (direct-config) path is unaffected.
