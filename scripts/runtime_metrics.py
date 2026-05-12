#!/usr/bin/env python3
"""
Runtime metrics collection and HTTP server for scraping by otel-collector.
This exposes process, PID, and system metrics that can be scraped rather than pushed.
"""

import os
import time
import threading
import psutil
import subprocess
import logging
from prometheus_client import CollectorRegistry, Gauge, Counter, Histogram, Info, start_http_server
from prometheus_client.core import REGISTRY
import http.server
import socketserver

logger = logging.getLogger(__name__)

class RuntimeMetricsCollector:
    """Collects runtime metrics for the robot runtime platform"""
    
    def __init__(self, registry=None):
        self.registry = registry or REGISTRY
        self.setup_metrics()
        
    def setup_metrics(self):
        """Set up all the metrics we want to collect"""
        
        # Process count metrics
        self.process_count_current = Gauge(
            'runwhen_process_count_current',
            'Current number of processes in cgroup',
            registry=self.registry
        )
        
        self.process_count_max = Gauge(
            'runwhen_process_count_max', 
            'Maximum allowed processes in cgroup',
            registry=self.registry
        )
        
        self.process_utilization_percent = Gauge(
            'runwhen_process_utilization_percent',
            'PID utilization percentage',
            registry=self.registry
        )
        
        # Process lifecycle metrics
        self.process_memory_rss_bytes = Gauge(
            'runwhen_process_memory_rss_bytes',
            'Process resident memory size in bytes',
            registry=self.registry
        )
        
        self.process_memory_vms_bytes = Gauge(
            'runwhen_process_memory_vms_bytes', 
            'Process virtual memory size in bytes',
            registry=self.registry
        )
        
        self.process_open_fds = Gauge(
            'runwhen_process_open_fds',
            'Number of open file descriptors',
            registry=self.registry
        )
        
        # Child process metrics
        self.child_process_count = Gauge(
            'runwhen_child_process_count',
            'Number of child processes',
            registry=self.registry
        )
        
        self.python_process_count = Gauge(
            'runwhen_python_process_count',
            'Number of Python processes',
            registry=self.registry
        )
        
        self.shell_process_count = Gauge(
            'runwhen_shell_process_count',
            'Number of shell processes',
            registry=self.registry
        )
        
        # Process cleanup metrics (counters)
        self.process_cleanup_success_total = Counter(
            'runwhen_process_cleanup_success_total',
            'Total processes successfully terminated',
            registry=self.registry
        )
        
        self.process_cleanup_failed_total = Counter(
            'runwhen_process_cleanup_failed_total',
            'Total processes that required SIGKILL',
            registry=self.registry
        )
        
        # Process cleanup timing
        self.process_cleanup_duration_seconds = Histogram(
            'runwhen_process_cleanup_duration_seconds',
            'Time taken for process cleanup',
            registry=self.registry
        )
        
        # Runtime info
        self.runtime_info = Info(
            'runwhen_runtime_info',
            'Runtime information',
            registry=self.registry
        )
        
        # Set static info
        self.runtime_info.info({
            'pid': str(os.getpid()),
            'pgid': str(os.getpgid(0)),
            'session_id': os.environ.get('RW_SESSION_ID', 'unknown'),
            'runrequest_id': os.environ.get('RW_RUNREQUEST_ID', 'unknown'),
        })
        
    def collect_cgroup_metrics(self):
        """Collect cgroup-related PID metrics"""
        try:
            current_pids, max_pids = self.get_cgroup_pids_info()
            
            self.process_count_current.set(current_pids)
            self.process_count_max.set(max_pids if max_pids != float('inf') else 0)
            
            # Calculate utilization percentage
            if max_pids > 0 and max_pids != float('inf'):
                utilization = (current_pids / max_pids) * 100
                self.process_utilization_percent.set(utilization)
            else:
                # If no limit, show percentage based on reasonable baseline
                baseline = 1000  # Assume 1000 as a reasonable baseline
                utilization = (current_pids / baseline) * 100
                self.process_utilization_percent.set(min(utilization, 100))
                
        except Exception as e:
            logger.warning(f"Error collecting cgroup metrics: {e}")
    
    def collect_process_metrics(self):
        """Collect process-related metrics"""
        try:
            current_process = psutil.Process()
            
            # Memory metrics
            memory_info = current_process.memory_info()
            self.process_memory_rss_bytes.set(memory_info.rss)
            self.process_memory_vms_bytes.set(memory_info.vms)
            
            # File descriptor count
            try:
                fd_count = current_process.num_fds()
                self.process_open_fds.set(fd_count)
            except (AttributeError, psutil.AccessDenied):
                pass  # Not available on all platforms
            
            # Child process analysis
            children = current_process.children(recursive=True)
            self.child_process_count.set(len(children))
            
            # Categorize child processes
            python_count = 0
            shell_count = 0
            
            for child in children:
                try:
                    name = child.name().lower()
                    if 'python' in name:
                        python_count += 1
                    elif name in ['bash', 'sh', 'zsh']:
                        shell_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            self.python_process_count.set(python_count)
            self.shell_process_count.set(shell_count)
            
        except Exception as e:
            logger.warning(f"Error collecting process metrics: {e}")
    
    def collect_all_metrics(self):
        """Collect all runtime metrics"""
        self.collect_cgroup_metrics()
        self.collect_process_metrics()
    
    def record_cleanup_metrics(self, success_count, failed_count, duration_seconds):
        """Record process cleanup metrics"""
        self.process_cleanup_success_total.inc(success_count)
        self.process_cleanup_failed_total.inc(failed_count)
        self.process_cleanup_duration_seconds.observe(duration_seconds)

    def get_cgroup_pids_info(self):
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
                        
                        # pids.max might not exist in v2, default to system limit
                        if os.path.exists(max_path):
                            with open(max_path) as f:
                                max_content = f.read().strip()
                                max_pids = float('inf') if max_content == 'max' else int(max_content)
                        else:
                            # Fallback to system limit
                            max_pids = 32768  # Common default
                        
                        return current, max_pids
            
            return 0, 0
        except Exception as e:
            logger.warning(f"Error reading cgroup pids info: {e}")
            return 0, 0


class MetricsServer:
    """HTTP server for serving Prometheus metrics"""
    
    def __init__(self, port=8000, registry=None):
        self.port = port
        self.registry = registry or REGISTRY
        self.collector = RuntimeMetricsCollector(registry=self.registry)
        self.server_thread = None
        self.running = False
        
    def start(self):
        """Start the metrics server in a background thread"""
        if self.running:
            return
        
        try:
            # Start periodic collection
            self.running = True
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            
            # Start metrics collection loop
            self.metrics_thread = threading.Thread(target=self._collect_metrics_loop, daemon=True)
            self.metrics_thread.start()
            
            logger.info(f"Runtime metrics server started on port {self.port}")
            
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
            self.running = False
            
    def _run_server(self):
        """Run the HTTP server"""
        try:
            start_http_server(self.port, registry=self.registry)
        except Exception as e:
            logger.error(f"Metrics server error: {e}")
            
    def _collect_metrics_loop(self):
        """Periodically collect metrics"""
        while self.running:
            try:
                self.collector.collect_all_metrics()
                time.sleep(15)  # Collect every 15 seconds
            except Exception as e:
                logger.warning(f"Error in metrics collection loop: {e}")
                time.sleep(15)
                
    def stop(self):
        """Stop the metrics server"""
        self.running = False
        if self.server_thread:
            self.server_thread.join(timeout=5)
        logger.info("Runtime metrics server stopped")
        
    def get_collector(self):
        """Get the metrics collector for recording cleanup events"""
        return self.collector


# Global metrics server instance
_metrics_server = None

def start_metrics_server(port=None):
    """Start the global metrics server"""
    global _metrics_server
    
    if _metrics_server is not None:
        return _metrics_server
    
    # Default port, but allow override via environment
    if port is None:
        port = int(os.environ.get('RW_METRICS_PORT', 8000))
    
    _metrics_server = MetricsServer(port=port)
    _metrics_server.start()
    return _metrics_server

def stop_metrics_server():
    """Stop the global metrics server"""
    global _metrics_server
    if _metrics_server:
        _metrics_server.stop()
        _metrics_server = None

def get_metrics_server():
    """Get the global metrics server instance"""
    return _metrics_server

def record_cleanup_metrics(success_count, failed_count, duration_seconds):
    """Record cleanup metrics if server is running"""
    if _metrics_server:
        _metrics_server.get_collector().record_cleanup_metrics(
            success_count, failed_count, duration_seconds
        ) 