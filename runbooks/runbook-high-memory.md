# Runbook: Increasing memory usage (possible memory leak)

## Symptoms

- Container memory usage metric rises steadily over time without
  stabilizing.
- The container is restarted by the orchestrator for exceeding the
  memory limit (OOMKilled, in the case of Kubernetes/Docker).
- Increased latency shortly before crashing, caused by more frequent
  garbage collection (in GC-based languages, such as Python, Java,
  Node.js).

## Likely causes

1. **Actual memory leak**: objects, connections, or caches that are
   never freed by the application.
2. **Unbounded cache size**: an internal caching structure grows
   indefinitely because it lacks an expiration policy (TTL) or maximum size.
3. **Accumulation of unclosed connections**: database, HTTP, or queue
   connections that are not closed properly.
4. **Processing large files/payloads**: the application loads entire
   files into memory instead of streaming them.

## Diagnosis

1. Observe whether memory growth is linear and steady (strong indicator
   of a leak) or fluctuates (normal cache/GC behavior).
2. Correlate the onset of growth with recent deployments.
3. If possible, capture a heap dump or memory profile at peak usage to
   identify which objects are accumulating.

## Recommended actions

- **Immediate mitigation**: restarting the container temporarily frees
  memory, but does not address the root cause — it must be treated as a
  workaround, not a solution.
- **Short term**: add size limits and TTLs to internal caches.
- **Medium term**: review code for unclosed connections/resources (use
  context managers, connection pooling with bounds).
- Monitor memory trends over days, not just minutes — slow leaks only
  become obvious over longer time windows.

## Severity

High if the container is being restarted repeatedly (OOMKill loop).
Medium if growth is slow and there is still margin before reaching the limit.
