#!/bin/bash
# HW5 cleanup: tears down what setup.sh created, to stop billing.
#
#   - deletes the VM
#   - releases the static IP
#   - deletes the firewall rule
#   - STOPS (does not delete) the Cloud SQL instance
#   - resumes the hourly job that stops the database, as a safety net

set -uo pipefail          # no -e: keep going even if something is already gone
cd "$(dirname "$0")"

# ============================== settings ==============================
PROJECT_ID="tonal-plateau-508118-g0"
REGION="us-central1"
ZONE="us-central1-a"

DB_INSTANCE="hw5-db"
VM_NAME="hw5-vm"
IP_NAME="hw5-ip"
FW_RULE="hw5-allow-8000"
SCHEDULER_JOB="stop-db-hourly"
# ======================================================================

export CLOUDSDK_CORE_PROJECT="$PROJECT_ID"

log() { echo; echo "===== $* ====="; }

log "Deleting VM"
if gcloud compute instances describe "$VM_NAME" --zone="$ZONE" >/dev/null 2>&1; then
    gcloud compute instances delete "$VM_NAME" --zone="$ZONE" --quiet
else
    echo "$VM_NAME not found, skipping."
fi

# The VM must be gone before its IP can be released.
log "Releasing static IP"
if gcloud compute addresses describe "$IP_NAME" --region="$REGION" >/dev/null 2>&1; then
    gcloud compute addresses delete "$IP_NAME" --region="$REGION" --quiet
else
    echo "$IP_NAME not found, skipping."
fi

log "Deleting firewall rule"
if gcloud compute firewall-rules describe "$FW_RULE" >/dev/null 2>&1; then
    gcloud compute firewall-rules delete "$FW_RULE" --quiet
else
    echo "$FW_RULE not found, skipping."
fi

log "Stopping Cloud SQL (not deleting)"
if gcloud sql instances describe "$DB_INSTANCE" >/dev/null 2>&1; then
    POLICY=$(gcloud sql instances describe "$DB_INSTANCE" --format="value(settings.activationPolicy)")
    if [ "$POLICY" = "ALWAYS" ]; then
        gcloud sql instances patch "$DB_INSTANCE" --activation-policy=NEVER --quiet --async
        echo "Stop requested for $DB_INSTANCE."
    else
        echo "$DB_INSTANCE is already stopped."
    fi
else
    echo "$DB_INSTANCE not found, skipping."
fi

log "Re-enabling the hourly database auto-stop"
gcloud scheduler jobs resume "$SCHEDULER_JOB" --location="$REGION" >/dev/null 2>&1 \
    && echo "$SCHEDULER_JOB resumed." \
    || echo "$SCHEDULER_JOB not found, skipping."

log "Done"