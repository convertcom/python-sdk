Fixed a tracking-delivery defect that caused live conversions to fail with HTTP 403.

**Defect 1 — tracking posted to the config CDN instead of the metrics endpoint.**
`send_tracking()` was posting to the same host as config fetches
(`https://cdn-4.convertexperiments.com`), which is a config-serving CDN that
returns 403 for tracking POSTs. Tracking events must go to the separate metrics
endpoint: `https://[project_id].metrics.convertexperiments.com/v1/track/{sdkKey}`,
where `[project_id]` is substituted with the real project id at request time
(JS/PHP SDK parity). `TransportConfig` gains a new `track_base_url` field
(default: `https://[project_id].metrics.convertexperiments.com/v1`) that can be
overridden for custom deployments.

**Defect 2 — missing bot-filter User-Agent header.**
The metrics server runs a bot filter that silently drops requests not carrying
a `User-Agent` starting with `ConvertAgent/`. Every tracking POST now sets
`User-Agent: ConvertAgent/1.0` (JS/PHP SDK parity), preventing the "200 OK but
event never recorded" silent discard.
