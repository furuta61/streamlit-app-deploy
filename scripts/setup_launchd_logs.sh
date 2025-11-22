#!/bin/bash
# Create log directory for launchd-managed monitor logs
mkdir -p "$HOME/Library/Logs/CFD3_AutoSystem"
chmod 755 "$HOME/Library/Logs/CFD3_AutoSystem"
# Ensure existing log files exist
touch "$HOME/Library/Logs/CFD3_AutoSystem/monitor.log"
touch "$HOME/Library/Logs/CFD3_AutoSystem/monitor.err"
chmod 644 "$HOME/Library/Logs/CFD3_AutoSystem/monitor.log" "$HOME/Library/Logs/CFD3_AutoSystem/monitor.err"
echo "Log directory ensured: $HOME/Library/Logs/CFD3_AutoSystem"
