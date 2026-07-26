# Runbook: Sustained high CPU usage in containerized service

## Symptoms

- `cpu_usage_percent` metric above 80% of the CPU allocated to the container
  for more than 15 seconds.
- Request response time gradually increases.
- In severe cases, the service stops responding to health checks.

## Likely causes

1. **Process with loop or inefficient calculation**: an internal service
   routine started consuming disproportionate CPU, usually following a
   recent deployment or configuration change.
2. **Legitimate traffic spike**: request volume grew beyond the capacity
   allocated to the container.
3. **Noisy neighbor**: another process or container on the same physical
   host is competing for the same CPU cores.
4. **Under-provisioned resource limit**: the container was configured
   with a CPU limit (`cpus` in Docker Compose, or `resources.limits`
   in Kubernetes) lower than necessary for its normal workload.

## Diagnosis

1. Confirm whether the CPU increase coincides with a request increase
   (`http_requests_total`) or if it is disproportionate to it.
2. Check if there was a recent deployment or configuration change in the
   affected service.
3. Compare the container's CPU usage with the overall machine/node usage —
   if only the container is high while the host is idle, it is a service bug/config
   issue; if the entire machine is under pressure, it is a capacity or
   noisy neighbor problem.

## Recommended actions

- **If it is a legitimate traffic spike**: scale horizontally (spin up
  more service replicas) or increase the container's CPU limit.
- **If it is a stuck process/loop**: restarting the container usually
  resolves the symptom immediately, but the root cause must be investigated
  afterward (do not treat the restart as a permanent fix).
- **If it is a noisy neighbor**: move the service to another host or
  isolate it via `cpuset` (pin to dedicated cores).
- Never increase the CPU limit without understanding the root cause — doing
  so only postpones the problem and may mask a real bug.

## Severity

High if it persists for more than a few minutes or affects the response time for
end users. Medium if it is transient and resolved automatically by auto-scaling.
