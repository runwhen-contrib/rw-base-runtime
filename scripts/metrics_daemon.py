#!/usr/bin/env python3
"""
Standalone metrics daemon that runs independently of runrobot.py instances.
This provides a single metrics server that aggregates metrics from runrobot processes.
"""

import os
import time
import signal
import sys
import logging
import json
import psutil
from pathlib import Path
from prometheus_client import CollectorRegistry, Gauge, Counter, Histogram, Info, start_http_server
from prometheus_client.core import REGISTRY
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import threading
import socket

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProcessMetricsCollector:
    """Collects metrics from process metric files"""
    
    def __init__(self, metrics_dir="/tmp/runwhen_metrics", registry=None):
        self.metrics_dir = Path(metrics_dir)
        self.metrics_dir.mkdir(exist_ok=True)
        self.registry = registry or REGISTRY
        self.setup_metrics()
        
    def setup_metrics(self):
        """Set up Prometheus metrics"""
        # Current process metrics
        self.active_processes = Gauge(
            'runwhen_active_processes',
            'Number of currently active runrobot processes',
            registry=self.registry
        )
        
        self.process_memory_total = Gauge(
            'runwhen_process_memory_total_bytes',
            'Total memory usage across all processes',
            registry=self.registry
        )
        
        self.process_count_by_status = Gauge(
            'runwhen_process_count_by_status',
            'Number of processes by status',
            ['status'],
            registry=self.registry
        )
        
        # Process lifecycle metrics
        self.process_starts_total = Counter(
            'runwhen_process_starts_total',
            'Total number of processes started',
            registry=self.registry
        )
        
        self.process_completions_total = Counter(
            'runwhen_process_completions_total',
            'Total number of processes completed',
            ['exit_code'],
            registry=self.registry
        )
        
        self.process_duration_seconds = Histogram(
            'runwhen_process_duration_seconds',
            'Process execution duration',
            registry=self.registry
        )
        
        # Cleanup metrics
        self.cleanup_events_total = Counter(
            'runwhen_cleanup_events_total',
            'Total cleanup events',
            registry=self.registry
        )
        
        self.cleanup_processes_total = Counter(
            'runwhen_cleanup_processes_total',
            'Total processes cleaned up',
            ['result'],
            registry=self.registry
        )
        
        # Runtime info
        self.runtime_info = Info(
            'runwhen_daemon_info',
            'Daemon runtime information',
            registry=self.registry
        )
        
        # Python runtime metrics from processes
        self.python_gc_collections = Gauge(
            'runwhen_python_gc_collections_total',
            'Total garbage collections by generation',
            ['generation'],
            registry=self.registry
        )
        
        self.python_gc_collected = Gauge(
            'runwhen_python_gc_collected_total',
            'Total objects collected by GC',
            registry=self.registry
        )
        
        self.python_threads_active = Gauge(
            'runwhen_python_threads_active',
            'Active Python threads',
            registry=self.registry
        )
        
        self.python_threads_daemon = Gauge(
            'runwhen_python_threads_daemon',
            'Daemon Python threads',
            registry=self.registry
        )
        
        self.python_memory_objects = Gauge(
            'runwhen_python_memory_objects_total',
            'Total Python objects in memory',
            registry=self.registry
        )
        
        self.python_memory_traced = Gauge(
            'runwhen_python_memory_traced_bytes',
            'Python traced memory usage',
            ['type'],
            registry=self.registry
        )
        
        self.python_info = Info(
            'runwhen_python_process_info',
            'Python runtime information from processes',
            registry=self.registry
        )
        
        self.runtime_info.info({
            'daemon_pid': str(os.getpid()),
            'metrics_dir': str(self.metrics_dir),
            'start_time': str(time.time())
        })
    
    def collect_metrics(self):
        """Collect metrics from all process files"""
        try:
            # Get all active process files
            active_files = list(self.metrics_dir.glob("process_*.json"))
            completed_files = list((self.metrics_dir / "completed").glob("*.json")) if (self.metrics_dir / "completed").exists() else []
            
            # Count active processes
            self.active_processes.set(len(active_files))
            
            # Collect metrics from active processes
            total_memory = 0
            status_counts = {}
            
            # Python metrics aggregates
            total_gc_collections = {'gen0': 0, 'gen1': 0, 'gen2': 0}
            total_gc_collected = 0
            total_threads_active = 0
            total_threads_daemon = 0
            total_memory_objects = 0
            python_version_info = None
            
            for process_file in active_files:
                try:
                    with open(process_file, 'r') as f:
                        data = json.load(f)
                    
                    # Check if process is still running
                    if self._is_process_running(data.get('pid')):
                        status = data.get('status', 'unknown')
                        status_counts[status] = status_counts.get(status, 0) + 1
                        
                        # Memory usage - read from the data file
                        memory_rss = data.get('memory_rss_bytes', 0)
                        if memory_rss > 0:
                            total_memory += memory_rss
                        
                        # Collect Python metrics
                        python_gc = data.get('python_gc', {})
                        python_threads = data.get('python_threads', {})
                        python_memory = data.get('python_memory', {})
                        python_info = data.get('python_info', {})
                        
                        # Aggregate Python metrics
                        total_gc_collections['gen0'] += python_gc.get('collections_gen0', 0)
                        total_gc_collections['gen1'] += python_gc.get('collections_gen1', 0)
                        total_gc_collections['gen2'] += python_gc.get('collections_gen2', 0)
                        total_gc_collected += python_gc.get('total_collected', 0)
                        total_threads_active += python_threads.get('active_count', 0)
                        total_threads_daemon += python_threads.get('daemon_thread_count', 0)
                        total_memory_objects += python_memory.get('refcount_total', 0)
                        
                        # Store Python version info (use first valid one found)
                        if python_info and not python_version_info:
                            python_version_info = python_info
                        
                        # Handle traced memory
                        if python_memory.get('tracemalloc_enabled'):
                            current_traced = python_memory.get('traced_current_bytes', 0)
                            peak_traced = python_memory.get('traced_peak_bytes', 0)
                            if current_traced > 0:
                                self.python_memory_traced.labels(type='current').set(current_traced)
                            if peak_traced > 0:
                                self.python_memory_traced.labels(type='peak').set(peak_traced)
                            
                        # Count as process start if we haven't seen it before
                        # This is a simple approach - in production you'd want more sophisticated tracking
                        if data.get('status') == 'running' and not data.get('_counted_start'):
                            self.process_starts_total.inc()
                            # Mark as counted (this updates the file but it's okay for our use case)
                            data['_counted_start'] = True
                            with open(process_file, 'w') as f:
                                json.dump(data, f, indent=2)
                        
                    else:
                        # Process is dead, move to completed
                        self._move_to_completed(process_file, data)
                        
                except Exception as e:
                    logger.warning(f"Error reading process file {process_file}: {e}")
            
            # Update aggregated Python metrics
            self.python_gc_collections.labels(generation='gen0').set(total_gc_collections['gen0'])
            self.python_gc_collections.labels(generation='gen1').set(total_gc_collections['gen1'])
            self.python_gc_collections.labels(generation='gen2').set(total_gc_collections['gen2'])
            self.python_gc_collected.set(total_gc_collected)
            self.python_threads_active.set(total_threads_active)
            self.python_threads_daemon.set(total_threads_daemon)
            self.python_memory_objects.set(total_memory_objects)
            
            # Update Python version info
            if python_version_info:
                self.python_info.info({
                    'version': python_version_info.get('version', 'unknown'),
                    'version_info': python_version_info.get('version_info', 'unknown'),
                    'implementation': python_version_info.get('implementation', 'unknown'),
                    'platform': python_version_info.get('platform', 'unknown'),
                })
            
            # Update status counts
            for status, count in status_counts.items():
                self.process_count_by_status.labels(status=status).set(count)
            
            # Reset counts for statuses not seen
            for status in ['running', 'completed', 'unknown']:
                if status not in status_counts:
                    self.process_count_by_status.labels(status=status).set(0)
            
            self.process_memory_total.set(total_memory)
            
            # Process completed files for historical metrics
            self._process_completed_files(completed_files)
            
        except Exception as e:
            logger.warning(f"Error collecting metrics: {e}")
    
    def _is_process_running(self, pid):
        """Check if a process is still running"""
        if not pid:
            return False
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError):
            return False
    
    def _move_to_completed(self, process_file, data):
        """Move a dead process file to completed directory"""
        try:
            completed_dir = self.metrics_dir / "completed"
            completed_dir.mkdir(exist_ok=True)
            
            pid = data.get('pid', 'unknown')
            timestamp = int(time.time())
            completed_file = completed_dir / f"process_{pid}_{timestamp}.json"
            
            # Update data with completion info
            data['status'] = 'completed'
            data['end_time'] = time.time()
            data['exit_code'] = -1  # Unknown exit code
            
            with open(completed_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            process_file.unlink()
            
        except Exception as e:
            logger.warning(f"Error moving process file to completed: {e}")
    
    def _process_completed_files(self, completed_files):
        """Process completed files for historical metrics"""
        # Track which files we've already processed to avoid double-counting
        processed_file = self.metrics_dir / ".processed_completed"
        
        try:
            # Read list of already processed files
            processed_files = set()
            if processed_file.exists():
                with open(processed_file, 'r') as f:
                    processed_files = set(f.read().splitlines())
            
            newly_processed = []
            
            for completed_file in completed_files:
                file_id = completed_file.name
                if file_id in processed_files:
                    continue
                    
                try:
                    with open(completed_file, 'r') as f:
                        data = json.load(f)
                    
                    # Update completion counter
                    exit_code = data.get('exit_code', 0)
                    self.process_completions_total.labels(exit_code=str(exit_code)).inc()
                    
                    # Update duration histogram
                    duration = data.get('duration_seconds', 0)
                    if duration > 0:
                        self.process_duration_seconds.observe(duration)
                    
                    # Count cleanup events
                    cleanup_events = data.get('cleanup_events', [])
                    for event in cleanup_events:
                        self.cleanup_events_total.inc()
                        success_count = event.get('success_count', 0)
                        failed_count = event.get('failed_count', 0)
                        if success_count > 0:
                            self.cleanup_processes_total.labels(result='success').inc(success_count)
                        if failed_count > 0:
                            self.cleanup_processes_total.labels(result='failed').inc(failed_count)
                    
                    # Mark as processed
                    newly_processed.append(file_id)
                    
                except Exception as e:
                    logger.warning(f"Error processing completed file {completed_file}: {e}")
            
            # Update processed files list
            if newly_processed:
                with open(processed_file, 'a') as f:
                    for file_id in newly_processed:
                        f.write(f"{file_id}\n")
                        
        except Exception as e:
            logger.warning(f"Error processing completed files: {e}")

class SystemMetricsCollector:
    """Collects system and daemon process metrics (similar to the original runtime_metrics)"""
    
    def __init__(self, registry=None):
        self.registry = registry or REGISTRY
        self.setup_metrics()
        
    def setup_metrics(self):
        """Set up system metrics that were previously available"""
        # Daemon process metrics
        self.daemon_memory_rss_bytes = Gauge(
            'runwhen_daemon_memory_rss_bytes',
            'Daemon process resident memory size in bytes',
            registry=self.registry
        )
        
        self.daemon_memory_vms_bytes = Gauge(
            'runwhen_daemon_memory_vms_bytes',
            'Daemon process virtual memory size in bytes',
            registry=self.registry
        )
        
        self.daemon_open_fds = Gauge(
            'runwhen_daemon_open_fds',
            'Number of open file descriptors in daemon',
            registry=self.registry
        )
        
        self.daemon_cpu_percent = Gauge(
            'runwhen_daemon_cpu_percent',
            'Daemon CPU usage percentage',
            registry=self.registry
        )
        
        self.daemon_num_threads = Gauge(
            'runwhen_daemon_num_threads',
            'Number of threads in daemon process',
            registry=self.registry
        )
        
        # System-level metrics
        self.system_cpu_percent = Gauge(
            'runwhen_system_cpu_percent',
            'System CPU usage percentage',
            registry=self.registry
        )
        
        self.system_memory_percent = Gauge(
            'runwhen_system_memory_percent',
            'System memory usage percentage',
            registry=self.registry
        )
        
        self.system_disk_usage_percent = Gauge(
            'runwhen_system_disk_usage_percent',
            'System disk usage percentage',
            ['path'],
            registry=self.registry
        )
        
        # Cgroup metrics (if available)
        self.cgroup_pids_current = Gauge(
            'runwhen_cgroup_pids_current',
            'Current number of processes in cgroup',
            registry=self.registry
        )
        
        self.cgroup_pids_max = Gauge(
            'runwhen_cgroup_pids_max',
            'Maximum allowed processes in cgroup',
            registry=self.registry
        )
        
        self.cgroup_memory_usage_bytes = Gauge(
            'runwhen_cgroup_memory_usage_bytes',
            'Current memory usage in cgroup',
            registry=self.registry
        )
        
        self.cgroup_pids_usage_percent = Gauge(
            'runwhen_cgroup_pids_usage_percent',
            'Percentage of PID limit currently used',
            registry=self.registry
        )
        
        # Python runtime info
        self.python_info = Info(
            'runwhen_python_info',
            'Python runtime information',
            registry=self.registry
        )
        
        # Set Python info
        import sys
        self.python_info.info({
            'version': sys.version,
            'implementation': sys.implementation.name,
            'version_info': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        })
    
    def collect_metrics(self):
        """Collect system and daemon metrics"""
        try:
            # Get current process (daemon)
            daemon_process = psutil.Process()
            
            # Daemon process metrics
            memory_info = daemon_process.memory_info()
            self.daemon_memory_rss_bytes.set(memory_info.rss)
            self.daemon_memory_vms_bytes.set(memory_info.vms)
            
            try:
                self.daemon_open_fds.set(daemon_process.num_fds())
            except (AttributeError, psutil.AccessDenied):
                pass
            
            try:
                self.daemon_cpu_percent.set(daemon_process.cpu_percent())
            except psutil.AccessDenied:
                pass
            
            try:
                self.daemon_num_threads.set(daemon_process.num_threads())
            except psutil.AccessDenied:
                pass
            
            # System metrics
            self.system_cpu_percent.set(psutil.cpu_percent())
            self.system_memory_percent.set(psutil.virtual_memory().percent)
            
            # Disk usage for common paths
            for path in ['/', '/tmp']:
                try:
                    disk_usage = psutil.disk_usage(path)
                    usage_percent = (disk_usage.used / disk_usage.total) * 100
                    self.system_disk_usage_percent.labels(path=path).set(usage_percent)
                except (OSError, psutil.AccessDenied):
                    pass
            
            # Cgroup metrics
            self._collect_cgroup_metrics()
            
        except Exception as e:
            logger.warning(f"Error collecting system metrics: {e}")
    
    def _collect_cgroup_metrics(self):
        """Collect cgroup metrics (reusing logic from runtime_metrics)"""
        try:
            current_pids, max_pids = self._get_cgroup_pids_info()
            
            if current_pids > 0:
                self.cgroup_pids_current.set(current_pids)
                
            if max_pids > 0 and max_pids != float('inf'):
                self.cgroup_pids_max.set(max_pids)
            
            # Memory usage from cgroup
            memory_usage = self._get_cgroup_memory_usage()
            if memory_usage > 0:
                self.cgroup_memory_usage_bytes.set(memory_usage)
                
            # PID usage percentage
            if max_pids > 0:
                usage_percent = (current_pids / max_pids) * 100
                self.cgroup_pids_usage_percent.set(usage_percent)
                
        except Exception as e:
            logger.warning(f"Error collecting cgroup metrics: {e}")
    
    def _get_cgroup_pids_info(self):
        """Get current PID count from cgroup (supports both v1 and v2)"""
        try:
            with open('/proc/self/cgroup', 'r') as f:
                cgroup_content = f.read()
            
            # Try cgroup v1 first
            for line in cgroup_content.split('\n'):
                if 'pids' in line:
                    pids_cgroup = line.split(':')[-1]
                    current_path = f"/sys/fs/cgroup{pids_cgroup}/pids.current"
                    max_path = f"/sys/fs/cgroup{pids_cgroup}/pids.max"
                    
                    if os.path.exists(current_path) and os.path.exists(max_path):
                        with open(current_path) as f:
                            current = int(f.read().strip())
                        with open(max_path) as f:
                            max_content = f.read().strip()
                            max_pids = float('inf') if max_content == 'max' else int(max_content)
                        return current, max_pids
            
            # Try cgroup v2
            for line in cgroup_content.split('\n'):
                if line.startswith('0::'):
                    cgroup_v2_path = line.split('::')[-1].strip()
                    current_path = f"/sys/fs/cgroup{cgroup_v2_path}/pids.current"
                    max_path = f"/sys/fs/cgroup{cgroup_v2_path}/pids.max"
                    
                    if os.path.exists(current_path):
                        with open(current_path) as f:
                            current = int(f.read().strip())
                        
                        if os.path.exists(max_path):
                            with open(max_path) as f:
                                max_content = f.read().strip()
                                max_pids = float('inf') if max_content == 'max' else int(max_content)
                        else:
                            max_pids = 32768  # Common default
                        
                        return current, max_pids
            
            return 0, 0
        except Exception as e:
            logger.warning(f"Error reading cgroup pids info: {e}")
            return 0, 0
    
    def _get_cgroup_memory_usage(self):
        """Get current memory usage from cgroup"""
        try:
            with open('/proc/self/cgroup', 'r') as f:
                cgroup_content = f.read()
            
            # Try cgroup v1 first
            for line in cgroup_content.split('\n'):
                if 'memory' in line:
                    memory_cgroup = line.split(':')[-1]
                    usage_path = f"/sys/fs/cgroup{memory_cgroup}/memory.usage_in_bytes"
                    
                    if os.path.exists(usage_path):
                        with open(usage_path) as f:
                            return int(f.read().strip())
            
            # Try cgroup v2
            for line in cgroup_content.split('\n'):
                if line.startswith('0::'):
                    cgroup_v2_path = line.split('::')[-1].strip()
                    usage_path = f"/sys/fs/cgroup{cgroup_v2_path}/memory.current"
                    
                    if os.path.exists(usage_path):
                        with open(usage_path) as f:
                            return int(f.read().strip())
            
            return 0
        except Exception as e:
            logger.warning(f"Error reading cgroup memory usage: {e}")
            return 0

class MetricsDaemon:
    """Standalone metrics daemon for the platform"""
    
    def __init__(self, port=9090, metrics_dir="/tmp/runwhen_metrics"):
        self.port = port
        self.metrics_dir = metrics_dir
        self.running = False
        self.process_collector = None
        self.system_collector = None
        
    def start(self):
        """Start the metrics daemon"""
        logger.info(f"Starting metrics daemon on port {self.port}")
        
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        try:
            # Create registry and collectors
            registry = CollectorRegistry()
            
            # Create our custom collectors (skip standard Python collectors for now to avoid import issues)
            self.process_collector = ProcessMetricsCollector(
                metrics_dir=self.metrics_dir,
                registry=registry
            )
            
            self.system_collector = SystemMetricsCollector(registry=registry)
            
            # Start the HTTP server
            start_http_server(self.port, registry=registry)
            
            self.running = True
            logger.info(f"Metrics daemon started successfully on port {self.port}")
            
            # Main loop
            while self.running:
                try:
                    self.process_collector.collect_metrics()
                    self.system_collector.collect_metrics()
                    time.sleep(15)  # Collect every 15 seconds
                except Exception as e:
                    logger.warning(f"Error in collection loop: {e}")
                    time.sleep(15)
                    
        except OSError as e:
            if e.errno == 98:  # Address already in use
                logger.error(f"Port {self.port} already in use. Is another metrics daemon running?")
                sys.exit(1)
            else:
                raise
        except Exception as e:
            logger.error(f"Failed to start metrics daemon: {e}")
            sys.exit(1)
            
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
        sys.exit(0)

def main():
    """Main entry point"""
    port = int(os.environ.get('RW_METRICS_PORT', 9090))
    metrics_dir = os.environ.get('RW_METRICS_DIR', '/tmp/runwhen_metrics')
    
    # Check if port is already in use
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('localhost', port))
        sock.close()
    except OSError:
        logger.error(f"Port {port} is already in use. Exiting.")
        sys.exit(1)
    
    daemon = MetricsDaemon(port=port, metrics_dir=metrics_dir)
    daemon.start()

if __name__ == "__main__":
    main() 