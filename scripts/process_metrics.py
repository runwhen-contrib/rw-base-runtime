#!/usr/bin/env python3
"""
Process-specific metrics that can be written to files for collection.
This allows runrobot.py instances to contribute metrics without port conflicts.
"""

import os
import json
import time
import psutil
import logging
import gc
import threading
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

class ProcessMetricsRecorder:
    """Records process metrics to files for collection by metrics daemon"""
    
    def __init__(self, metrics_dir="/tmp/runwhen_metrics"):
        self.metrics_dir = Path(metrics_dir)
        self.metrics_dir.mkdir(exist_ok=True)
        self.pid = os.getpid()
        self.metrics_file = self.metrics_dir / f"process_{self.pid}.json"
        self.start_time = time.time()
        
    def record_process_start(self, session_id=None, runrequest_id=None):
        """Record when a process starts"""
        try:
            process = psutil.Process(self.pid)
            metrics = {
                "pid": self.pid,
                "pgid": os.getpgid(0),
                "session_id": session_id or "unknown",
                "runrequest_id": runrequest_id or "unknown",
                "start_time": self.start_time,
                "process_name": process.name(),
                "cmdline": " ".join(process.cmdline()),
                "status": "running",
                "last_update": time.time()
            }
            
            with open(self.metrics_file, 'w') as f:
                json.dump(metrics, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Error recording process start: {e}")
    
    def record_process_metrics(self):
        """Record current process metrics"""
        try:
            if not self.metrics_file.exists():
                return
                
            process = psutil.Process(self.pid)
            memory_info = process.memory_info()
            
            # Read existing metrics
            with open(self.metrics_file, 'r') as f:
                metrics = json.load(f)
            
            # Basic process metrics
            basic_metrics = {
                "memory_rss_bytes": memory_info.rss,
                "memory_vms_bytes": memory_info.vms,
                "cpu_percent": process.cpu_percent(),
                "num_threads": process.num_threads(),
                "open_fds": process.num_fds() if hasattr(process, 'num_fds') else 0,
                "children_count": len(process.children()),
                "last_update": time.time()
            }
            
            # Python-specific metrics
            python_metrics = self._collect_python_metrics()
            
            # Update with current metrics
            metrics.update(basic_metrics)
            metrics.update(python_metrics)
            
            with open(self.metrics_file, 'w') as f:
                json.dump(metrics, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Error recording process metrics: {e}")
    
    def _collect_python_metrics(self):
        """Collect Python-specific runtime metrics"""
        try:
            # Garbage collection stats
            gc_stats = gc.get_stats()
            gc_counts = gc.get_count()
            
            # Thread information
            active_threads = threading.active_count()
            main_thread = threading.main_thread()
            
            # Memory information
            import tracemalloc
            memory_traced = tracemalloc.is_tracing()
            
            python_metrics = {
                "python_info": {
                    "version": sys.version,
                    "version_info": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                    "implementation": sys.implementation.name,
                    "executable": sys.executable,
                    "platform": sys.platform,
                },
                "python_gc": {
                    "collections_gen0": gc_counts[0] if len(gc_counts) > 0 else 0,
                    "collections_gen1": gc_counts[1] if len(gc_counts) > 1 else 0,
                    "collections_gen2": gc_counts[2] if len(gc_counts) > 2 else 0,
                    "total_collections": sum(stat.get('collections', 0) for stat in gc_stats),
                    "total_collected": sum(stat.get('collected', 0) for stat in gc_stats),
                    "total_uncollectable": sum(stat.get('uncollectable', 0) for stat in gc_stats),
                    "gc_enabled": gc.isenabled(),
                    "gc_thresholds": gc.get_threshold(),
                },
                "python_threads": {
                    "active_count": active_threads,
                    "main_thread_alive": main_thread.is_alive() if main_thread else False,
                    "main_thread_name": main_thread.name if main_thread else "unknown",
                    "daemon_thread_count": sum(1 for t in threading.enumerate() if t.daemon),
                },
                "python_memory": {
                    "tracemalloc_enabled": memory_traced,
                    "refcount_total": len(gc.get_objects()) if hasattr(gc, 'get_objects') else 0,
                }
            }
            
            # Add tracemalloc info if enabled
            if memory_traced:
                try:
                    current, peak = tracemalloc.get_traced_memory()
                    python_metrics["python_memory"].update({
                        "traced_current_bytes": current,
                        "traced_peak_bytes": peak,
                    })
                except Exception:
                    pass
            
            return python_metrics
            
        except Exception as e:
            logger.warning(f"Error collecting Python metrics: {e}")
            return {
                "python_info": {
                    "version": sys.version,
                    "error": str(e)
                }
            }
    
    def record_cleanup_event(self, success_count, failed_count, duration_seconds):
        """Record process cleanup event"""
        try:
            if not self.metrics_file.exists():
                return
                
            # Read existing metrics
            with open(self.metrics_file, 'r') as f:
                metrics = json.load(f)
            
            # Add cleanup event
            if 'cleanup_events' not in metrics:
                metrics['cleanup_events'] = []
            
            cleanup_event = {
                "timestamp": time.time(),
                "success_count": success_count,
                "failed_count": failed_count,
                "duration_seconds": duration_seconds
            }
            
            metrics['cleanup_events'].append(cleanup_event)
            metrics['last_update'] = time.time()
            
            with open(self.metrics_file, 'w') as f:
                json.dump(metrics, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Error recording cleanup event: {e}")
    
    def record_process_end(self, exit_code=0):
        """Record when a process ends"""
        try:
            if not self.metrics_file.exists():
                return
                
            # Read existing metrics
            with open(self.metrics_file, 'r') as f:
                metrics = json.load(f)
            
            # Mark as completed
            metrics.update({
                "status": "completed",
                "exit_code": exit_code,
                "end_time": time.time(),
                "duration_seconds": time.time() - self.start_time,
                "last_update": time.time()
            })
            
            with open(self.metrics_file, 'w') as f:
                json.dump(metrics, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Error recording process end: {e}")
    
    def cleanup(self):
        """Clean up metrics file when process exits"""
        try:
            if self.metrics_file.exists():
                # Move to completed directory instead of deleting
                completed_dir = self.metrics_dir / "completed"
                completed_dir.mkdir(exist_ok=True)
                
                completed_file = completed_dir / f"process_{self.pid}_{int(time.time())}.json"
                self.metrics_file.rename(completed_file)
                
                # Keep only last 100 completed files
                completed_files = sorted(completed_dir.glob("*.json"))
                if len(completed_files) > 100:
                    for old_file in completed_files[:-100]:
                        old_file.unlink()
                        
        except Exception as e:
            logger.warning(f"Error cleaning up metrics: {e}")

def get_process_metrics_recorder():
    """Get a process metrics recorder instance"""
    return ProcessMetricsRecorder()

# Global instance
_recorder = None

def init_process_metrics(session_id=None, runrequest_id=None):
    """Initialize process metrics recording"""
    global _recorder
    if _recorder is None:
        _recorder = ProcessMetricsRecorder()
        _recorder.record_process_start(session_id, runrequest_id)
    return _recorder

def record_cleanup_metrics(success_count, failed_count, duration_seconds):
    """Record cleanup metrics"""
    if _recorder:
        _recorder.record_cleanup_event(success_count, failed_count, duration_seconds)

def finalize_process_metrics(exit_code=0):
    """Finalize process metrics recording"""
    if _recorder:
        _recorder.record_process_end(exit_code)
        _recorder.cleanup() 