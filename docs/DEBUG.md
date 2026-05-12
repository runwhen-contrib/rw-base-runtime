# Debug Mode for Robot Runtime

## Artifact Preservation

By default, the robot runtime cleans up all temporary directories and artifacts after execution to prevent disk space issues. However, for debugging purposes, you can preserve these artifacts.

## Usage

### Enable Debug Mode (Preserve Artifacts)
```bash
export RW_DEBUG_KEEP_ARTIFACTS=true
# Run your robot execution
```

### Disable Debug Mode (Default - Cleanup)
```bash
export RW_DEBUG_KEEP_ARTIFACTS=false
# OR
unset RW_DEBUG_KEEP_ARTIFACTS
# Run your robot execution
```

## What Gets Preserved

When debug mode is enabled, the following directory structure is preserved:

```
/tmp/runwhen/executions/{SESSION_ID}/{RUNREQUEST_ID}/
├── codebundle/          # Robot working directory and copied files
│   ├── runbook.robot    # Your robot file(s)
│   └── [other files]    # Any supporting files
├── robot_logs/          # All robot outputs
│   ├── log.html         # Robot Framework log
│   ├── report.jsonl     # Platform reports
│   ├── issues.jsonl     # Platform issues
│   └── stdout.txt       # Console output
└── workdir/             # Configuration directories
    ├── .azure/          # Azure CLI config
    ├── .gcloud/         # Google Cloud config
    ├── cb-temp/         # CODEBUNDLE_TEMP_DIR
    └── .kube/           # Kubernetes config
```

## Manual Cleanup

When debug mode is enabled, you'll need to manually clean up artifacts:

```bash
# Remove specific execution
rm -rf /tmp/runwhen/executions/{SESSION_ID}/{RUNREQUEST_ID}

# Remove all debug artifacts
rm -rf /tmp/runwhen/executions/

# Clean up gradually (remove old sessions)
find /tmp/runwhen/executions/ -type d -mtime +1 -exec rm -rf {} \;
```

## Logging

The runtime will clearly indicate when debug mode is active:

```
🐛 DEBUG MODE ENABLED: Artifacts will be preserved after execution
🐛 DEBUG MODE: Set RW_DEBUG_KEEP_ARTIFACTS=false or unset to enable cleanup
```

Or when cleanup is enabled (default):

```
🧹 CLEANUP MODE: Artifacts will be cleaned up after execution
🧹 CLEANUP MODE: Set RW_DEBUG_KEEP_ARTIFACTS=true to preserve for debugging
```

## Use Cases

- **Debugging robot failures**: Inspect logs, outputs, and working directory
- **Development testing**: Check generated files and directory structure
- **Troubleshooting platform issues**: Examine configuration directories
- **Validating isolation**: Verify each execution gets its own directories

## Important Notes

⚠️ **Warning**: Debug mode can consume significant disk space if enabled in production environments with many executions.

✅ **Recommendation**: Only enable debug mode for specific troubleshooting sessions, not as a default setting.

🔧 **Best Practice**: Use debug mode in development/testing environments where disk space is less critical. 