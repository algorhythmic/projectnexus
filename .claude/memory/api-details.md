# Platform API Reference

## Kalshi
- Production: `https://trading-api.kalshi.com/trade-api/v2`
- Demo: `https://demo-api.kalshi.com/trade-api/v2`
- WebSocket: `wss://trading-api.kalshi.com/trade-api/ws/v2`
- Auth: RSA-PSS SHA-256, message = `timestamp_ms + METHOD + path`
- Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
- Rate limits (Basic): 20 reads/sec, 10 writes/sec — we use 15/sec
- Pagination: cursor-based (not page-number)
- ~3,500 markets, defined trading hours

## Polymarket (Phase 3)
- CLOB WS: `wss://ws-subscriptions-clob.polymarket.com`
- RTDS WS: `wss://ws-live-data.polymarket.com`
- REST: `https://gamma-api.polymarket.com`
- Auth: EIP-712 wallet signatures (L1) + HMAC-SHA256 API creds (L2)
- Rate: ~100 req/min free, $99/mo premium for WS feeds
- ~1,000+ active markets, 24/7

## Key API Limitation
Neither platform offers a firehose webhook. Both require:
1. Periodic REST polling (30-60s) to discover new markets
2. WebSocket subscriptions for real-time updates on tracked markets
