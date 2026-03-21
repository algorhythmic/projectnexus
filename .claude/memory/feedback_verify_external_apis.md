---
name: Verify external API response shapes before coding
description: Always validate actual API responses from external services before writing code that depends on their data — don't trust docs, specs, or existing code comments.
type: feedback
---

When a fix or feature depends on data from an external API, verify the actual response shape with a live call before writing code.

**Why:** During the N/A price fix (2026-03-19), we planned and implemented changes assuming `yes_price` was being extracted correctly from the Kalshi REST API. The spec doc, CLAUDE.md, and existing code all referenced field names (`yes_ask`, `yes_bid`, `last_price`) that Kalshi had since renamed to `_dollars` suffixed versions (`yes_ask_dollars`, etc.). A single test call during planning would have caught this immediately, saving a full deploy-debug-redeploy cycle.

**How to apply:** Before planning any fix that depends on external API data flowing correctly, run a quick probe (e.g., `fly ssh console` one-liner, `curl`, or a test script) to confirm the actual response shape matches assumptions. This applies to Kalshi, Polymarket, Convex, and any other external service. Treat existing code and documentation as potentially stale — the live API is the source of truth.
