# Subscription bridge admission

The existing Chat Completions bridge accepts these optional JSON settings:

```json
{
  "concurrency": 2,
  "queue_capacity": 4,
  "queue_wait_timeout_seconds": 20,
  "request_timeout_seconds": 165,
  "timeout_seconds": 240
}
```

Requests beyond the running limit wait in a bounded FIFO queue. A full queue
returns 429; queue expiry returns 503. Both include `Retry-After: 2`, a request
ID, and `inference_started: false`. Disconnected queued requests are removed.
No inference is replayed by the bridge. After inference starts, its slot remains
occupied until it actually ends, including when its client disconnects.

`request_timeout_seconds` covers body reading, waiting and inference. Waiting
consumes that budget; the remaining time caps the existing inference timeout.
If omitted, the total budget defaults to `timeout_seconds` (240 seconds by
default). Deployments must choose a total below their shortest caller timeout.
The isolated integration environment uses 165 seconds because the native L1
runner has a 180-second timeout, leaving 15 seconds for transport/cleanup. Its
original configured inference timeout stays 240 seconds; each invocation is
capped by the remaining total budget. Native L1/L2/L3 scheduling is unchanged.

Operational JSON logs contain generated request IDs, admission counts, model,
waiting/elapsed milliseconds and numeric usage when available. They exclude
credentials, prompt text and CLI output. `/health` exposes admission counters;
they reset on process restart and are not a replacement for a persisted test
budget ledger.
