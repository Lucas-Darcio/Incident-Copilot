# Runbook: Service not responding to health checks (down)

## Symptoms

- Health check endpoint (`/health`) stops responding or starts returning an
  error.
- Client requests return timeouts or connection refused errors.
- Orchestrator (Docker/Kubernetes) marks the container as unhealthy.

## Likely causes

1. **Application crash**: an unhandled exception killed the main
   process.
2. **Deadlock or hang**: the process is still running, but can no longer
   process requests (exhausted thread pool, unreleased lock).
3. **Unavailable external dependency**: the service hangs waiting for a
   response from a database, queue, or external API that is down, with
   no timeout configured.
4. **Resource exhaustion**: lack of memory or available file descriptors
   prevents the process from accepting new connections.

## Diagnosis

1. Check if the process/container is still running or has already restarted on
   its own (recurrent restarts indicate a crash, not a hang).
2. Inspect the container's recent logs for stack traces or error
   messages from when it stopped responding.
3. Check the status of external dependencies (database, cache, queues)
   consumed by the service.
4. If the process is alive but not responding, a hang (deadlock/exhausted
   thread pool) is more likely than a crash.

## Recommended actions

- **If it is a crash**: restarting resolves the immediate symptom; analyze the
  log's stack trace to identify the root exception.
- **If an external dependency is down**: the actual fix lies in the
  dependency, not the affected service — but adding timeouts and
  circuit breakers prevents external failures from hanging the whole service in
  the future.
- **If it is resource exhaustion**: verify configured limits for memory,
  connections, and file descriptors against what is actually needed.
- Always confirm that the service is responding correctly again after any
  corrective action, rather than just checking that the container restarted.

## Severity

Critical — direct and immediate impact on the end user. Must be treated
with the highest priority.
