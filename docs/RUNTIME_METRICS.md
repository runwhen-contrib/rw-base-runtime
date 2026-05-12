# RunWhen Runtime Metrics

This document describes the runtime metrics that are exposed by the RunWhen platform for monitoring process and PID management.

## Overview

The runtime metrics server exposes Prometheus-compatible metrics on port 8000 (configurable via `RW_METRICS_PORT` environment variable). These metrics can be scraped by your OpenTelemetry collector or any Prometheus-compatible scraper.

## Available Metrics

### Process Count Metrics

- **`runwhen_process_count_current`** (Gauge)
  - Description: Current number of processes in the cgroup
  - Use: Monitor process count growth over time
  - Alert on: Unexpected spikes or sustained high values

- **`runwhen_process_count_max`** (Gauge)
  - Description: Maximum allowed processes in the cgroup
  - Use: Understand the process limit constraints
  - Alert on: When this limit is reached

- **`runwhen_process_utilization_percent`** (Gauge)
  - Description: PID utilization percentage (current/max * 100)
  - Use: Monitor how close you are to hitting PID limits
  - Alert on: >80% utilization

### Memory Metrics

- **`runwhen_process_memory_rss_bytes`** (Gauge)
  - Description: Process resident memory size in bytes
  - Use: Monitor memory usage of the main process
  - Alert on: Memory growth trends or high usage

- **`runwhen_process_memory_vms_bytes`** (Gauge)
  - Description: Process virtual memory size in bytes
  - Use: Monitor virtual memory allocation
  - Alert on: Excessive virtual memory usage

### File Descriptor Metrics

- **`runwhen_process_open_fds`** (Gauge)
  - Description: Number of open file descriptors
  - Use: Monitor file descriptor leaks
  - Alert on: Continuously growing FD count

### Child Process Metrics

- **`runwhen_child_process_count`** (Gauge)
  - Description: Total number of child processes
  - Use: Monitor subprocess spawning
  - Alert on: Unexpected child process counts

- **`runwhen_python_process_count`** (Gauge)
  - Description: Number of Python child processes
  - Use: Monitor Python subprocess creation
  - Alert on: Excessive Python process spawning

- **`runwhen_shell_process_count`** (Gauge)
  - Description: Number of shell child processes (bash, sh, zsh)
  - Use: Monitor shell command execution
  - Alert on: Many concurrent shell processes

### Process Cleanup Metrics

- **`runwhen_process_cleanup_success_total`** (Counter)
  - Description: Total processes successfully terminated during cleanup
  - Use: Monitor cleanup effectiveness
  - Alert on: Declining success rate

- **`runwhen_process_cleanup_failed_total`** (Counter)
  - Description: Total processes that required SIGKILL during cleanup
  - Use: Monitor stubborn processes
  - Alert on: Increasing failure rate

- **`runwhen_process_cleanup_duration_seconds`** (Histogram)
  - Description: Time taken for process cleanup operations
  - Use: Monitor cleanup performance
  - Alert on: Slow cleanup operations

### Runtime Information

- **`runwhen_runtime_info`** (Info)
  - Description: Static runtime information
  - Labels: `pid`, `pgid`, `session_id`, `runrequest_id`
  - Use: Debugging and correlation

## Configuration

### Environment Variables

- **`RW_METRICS_PORT`**: Port for metrics server (default: 8000)
- **`RW_SESSION_ID`**: Session ID for labeling
- **`RW_RUNREQUEST_ID`**: Run request ID for labeling

### Enabling Metrics

Metrics are automatically enabled when the `runtime_metrics.py` module is available. No additional configuration is required.

## Integration with OpenTelemetry Collector

See `otel-collector-config-example.yaml` for a sample configuration that scrapes these metrics.

### Key Configuration Points

1. **Scrape Endpoint**: `http://localhost:8000/metrics`
2. **Scrape Interval**: 15 seconds (recommended)
3. **Job Name**: `runwhen-runtime`

## Monitoring and Alerting Recommendations

### Critical Alerts

1. **PID Exhaustion**: `runwhen_process_utilization_percent > 90`
2. **Process Cleanup Failures**: `rate(runwhen_process_cleanup_failed_total[5m]) > 0.1`
3. **Memory Leaks**: `increase(runwhen_process_memory_rss_bytes[10m]) > 100MB`

### Warning Alerts

1. **High PID Usage**: `runwhen_process_utilization_percent > 80`
2. **Slow Cleanup**: `histogram_quantile(0.95, runwhen_process_cleanup_duration_seconds) > 30`
3. **FD Leaks**: `increase(runwhen_process_open_fds[5m]) > 50`

### Operational Dashboards

Create dashboards showing:
- Process count trends over time
- Memory usage patterns
- Cleanup success rates
- FD usage patterns
- Child process spawning patterns

## Troubleshooting

### Metrics Not Available

If you see "Runtime metrics not available" in logs:
1. Check that `runtime_metrics.py` is in the correct location
2. Verify Python dependencies are installed
3. Check for import errors in logs

### Metrics Server Not Starting

If the metrics server fails to start:
1. Check port availability (default 8000)
2. Verify permissions for binding to the port
3. Check for network configuration issues

### Missing Metrics

If some metrics are missing:
1. Cgroup metrics require `/sys/fs/cgroup` access
2. File descriptor metrics may not be available on all platforms
3. Check logs for collection errors

## Example Queries

### Prometheus/PromQL

```promql
# Current PID utilization
runwhen_process_utilization_percent

# Memory usage trend
increase(runwhen_process_memory_rss_bytes[5m])

# Process cleanup success rate
rate(runwhen_process_cleanup_success_total[5m]) / 
(rate(runwhen_process_cleanup_success_total[5m]) + rate(runwhen_process_cleanup_failed_total[5m]))

# Average cleanup time
histogram_quantile(0.5, runwhen_process_cleanup_duration_seconds)
```

### Grafana Dashboard

Import the metrics and create panels for:
- Process count timeline
- Memory usage graph
- PID utilization gauge
- Cleanup success rate
- Active child processes by type 