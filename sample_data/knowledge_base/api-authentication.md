---
title: "Troubleshoot API authentication"
category: api_failure
tags: [api, authentication, token]
summary: "Safe checks for 401 and 403 API responses."
---
# Authentication failures

Confirm the token environment, expiration, scopes, and workspace membership. Compare the API host with the environment where the token was created.

## Secret handling

Ask only for a redacted token prefix and request ID. Never place a complete API key in tickets or logs.
