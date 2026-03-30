# Convert Python SDK

This package is the Python port of the Convert Fullstack SDK.

Current functionality includes:

- deterministic MurmurHash3-based bucketing
- JS-equivalent rule comparisons and traversal
- static-config and `sdkKey` initialization
- experience and feature evaluation through visitor contexts
- conversion tracking and API queue release
- in-memory and datastore-backed visitor persistence
- helper `DataStore` and `FileLogger` utilities
- configurable logger clients and log levels

The SDK entrypoint is `ConvertSDK`, which can create visitor contexts and evaluate the same CDN config shape used by the JavaScript SDK.
