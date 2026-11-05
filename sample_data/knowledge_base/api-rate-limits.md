---
title: "Handle API rate limits"
category: api_failure
tags: [api, "429", retry]
summary: "Recommended behavior after an HTTP 429 response."
---
# Rate-limit responses

Clients should honor the Retry-After header, use exponential backoff with jitter, and avoid synchronized retry bursts. Reduce concurrency for large nightly jobs.

## Diagnostics

Collect the endpoint, request ID, response headers, and approximate request rate. Never collect API keys.
