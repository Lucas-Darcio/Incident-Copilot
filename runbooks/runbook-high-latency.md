# Runbook: High request latency

## Symptoms

- Average response time or p95/p99 above normal, but the service
  continues to respond (unlike being "down").
- Users report slowness without explicit errors.
- Internal queues (if any) begin to accumulate items.

## Likely causes

1. **Slow database query**: missing index, poorly optimized query, or
   larger data volume than expected.
2. **Resource contention**: container CPU or memory close to the
   limit, causing slower processing (correlate with high CPU/memory
   runbooks).
3. **Slow external dependency**: call to an API or external service
   with degraded response time.
4. **Lack of parallelism/insufficient connections**: connection pool
   (database, HTTP) too small, causing an internal waiting queue
   even before processing the request.

## Diagnosis

1. Check if latency is correlated with high CPU or memory in the same
   container (in this case, treat as a symptom of another runbook).
2. Measure the latency of each external dependency separately (database,
   cache, APIs) to isolate where the bottleneck is.
3. Check the configured connection pool size versus the volume of
   concurrent requests.

## Recommended actions

- **If it is a database bottleneck**: review slow queries and indices
  before taking any infrastructure action.
- **If it is resource contention**: follow the corresponding runbook
  (high CPU or memory).
- **If it is a slow external dependency**: consider a more aggressive
  timeout and fallback, so as not to propagate slowness to the user.
- **Temporary mitigation**: increasing the connection pool size can
  relieve the symptom quickly, but does not replace investigating the
  root cause.

## Severity

Medium to high, depending on the impact on the user-perceived response
time and whether there is a trend of continuous degradation.
