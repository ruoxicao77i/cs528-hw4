#!/bin/bash
# HW5 setup: provisions everything needed to run the file server.
#
#   - static IP for the VM
#   - Cloud SQL instance, database, user and tables (created once, then only started)
#   - firewall rule for port 8000
#   - the VM itself (configured by startup.sh)
#   - Cloud Function + hourly Cloud Scheduler job that stops the database
#
# The scheduler job is PAUSED here because we are about to use the database.
# cleanup.sh resumes it.

set -euo pipefail
cd "$(dirname "$0")"          # so relative paths work no matter where it's run from

# ============================== settings ==============================
PROJECT_ID="tonal-plateau-508118-g0"
REGION="us-central1"
ZONE="us-central1-a"

DB_INSTANCE="hw5-db"
DB_NAME="hw5"
DB_USER="appuser"
DB_PASS="Hw5App2026"
DB_ROOT_PASS="12345"

VM_NAME="hw5-vm"
VM_TYPE="e2-medium"
IP_NAME="hw5-ip"
NET_TAG="hw5-server"
FW_RULE="hw5-allow-8000"
PORT=8000

FORBIDDEN_TOPIC="forbidden-requests"     # used by file-server.py (from HW4)
STOP_TOPIC="stop-db-topic"
FUNCTION_NAME="stop-db"
SCHEDULER_JOB="stop-db-hourly"
# ======================================================================

# Every gcloud command in this script uses this project,
# without changing the caller's own gcloud config.
export CLOUDSDK_CORE_PROJECT="$PROJECT_ID"

log() { echo; echo "===== $* ====="; }

# Wait until no Cloud SQL operation is still running on the instance.
wait_for_sql() {
    echo "Waiting for Cloud SQL operations to finish..."
    while [ -n "$(gcloud sql operations list --instance="$DB_INSTANCE" \
                    --filter='status!=DONE' --format='value(name)' 2>/dev/null)" ]; do
        sleep 15
    done
}

# ---------------------------------------------------------------- APIs
enable_apis() {
    log "Enabling APIs"
    gcloud services enable \
        compute.googleapis.com sqladmin.googleapis.com pubsub.googleapis.com \
        logging.googleapis.com storage.googleapis.com \
        cloudfunctions.googleapis.com cloudbuild.googleapis.com run.googleapis.com \
        eventarc.googleapis.com cloudscheduler.googleapis.com artifactregistry.googleapis.com
}

# ------------------------------------------------------------ static IP
setup_static_ip() {
    log "Static IP"
    if ! gcloud compute addresses describe "$IP_NAME" --region="$REGION" >/dev/null 2>&1; then
        gcloud compute addresses create "$IP_NAME" --region="$REGION"
    fi
    VM_IP=$(gcloud compute addresses describe "$IP_NAME" --region="$REGION" --format="value(address)")
    echo "VM IP: $VM_IP"
}

# ------------------------------------------------------------ Cloud SQL
create_schema() {
    echo "Creating tables with setup_schema.py ..."
    python3 -m venv .setup-venv
    .setup-venv/bin/pip install --quiet pymysql
    .setup-venv/bin/python setup_schema.py "$DB_IP"
}

setup_database() {
    log "Cloud SQL"
    # IPs allowed to connect: the VM, and this computer (for setup_schema.py / show_tables.py)
    MY_IP=$(curl -4 -s ifconfig.me)
    NETWORKS="$VM_IP/32,$MY_IP/32"
    echo "Authorized networks: $NETWORKS"

    if gcloud sql instances describe "$DB_INSTANCE" >/dev/null 2>&1; then
        echo "Instance $DB_INSTANCE exists, starting it."
        wait_for_sql
        # Starting and changing settings must happen in the same operation
        # when the instance is stopped.
        gcloud sql instances patch "$DB_INSTANCE" --quiet --async \
            --activation-policy=ALWAYS \
            --authorized-networks="$NETWORKS"
        wait_for_sql
        NEED_SCHEMA=false
    else
        echo "Instance $DB_INSTANCE not found, creating it (this takes several minutes)."
        gcloud sql instances create "$DB_INSTANCE" --async \
            --database-version=MYSQL_8_0 \
            --edition=ENTERPRISE \
            --tier=db-f1-micro \
            --region="$REGION" \
            --storage-type=HDD \
            --storage-size=10GB \
            --root-password="$DB_ROOT_PASS" \
            --authorized-networks="$NETWORKS"
        wait_for_sql
        NEED_SCHEMA=true
    fi

    DB_IP=$(gcloud sql instances describe "$DB_INSTANCE" --format="value(ipAddresses[0].ipAddress)")
    echo "DB IP: $DB_IP"

    # Database and user
    if ! gcloud sql databases describe "$DB_NAME" --instance="$DB_INSTANCE" >/dev/null 2>&1; then
        gcloud sql databases create "$DB_NAME" --instance="$DB_INSTANCE"
        NEED_SCHEMA=true
    fi
    if ! gcloud sql users list --instance="$DB_INSTANCE" --format="value(name)" | grep -qx "$DB_USER"; then
        gcloud sql users create "$DB_USER" --instance="$DB_INSTANCE" --password="$DB_PASS"
    fi

    if [ "$NEED_SCHEMA" = true ]; then
        create_schema
    else
        echo "Database $DB_NAME already exists, skipping schema creation."
    fi
}

# ------------------------------------------------------------- Pub/Sub
setup_topics() {
    log "Pub/Sub topics"
    for t in "$FORBIDDEN_TOPIC" "$STOP_TOPIC"; do
        if ! gcloud pubsub topics describe "$t" >/dev/null 2>&1; then
            gcloud pubsub topics create "$t"
        fi
    done
}

# ------------------------------------------------------------ firewall
setup_firewall() {
    log "Firewall"
    if ! gcloud compute firewall-rules describe "$FW_RULE" >/dev/null 2>&1; then
        gcloud compute firewall-rules create "$FW_RULE" \
            --allow="tcp:$PORT" --target-tags="$NET_TAG"
    fi
}

# ------------------------------------------------------------------ VM
setup_vm() {
    log "VM"
    # Always start from a fresh VM, so it runs the current file-server.py
    if gcloud compute instances describe "$VM_NAME" --zone="$ZONE" >/dev/null 2>&1; then
        echo "Deleting old $VM_NAME ..."
        gcloud compute instances delete "$VM_NAME" --zone="$ZONE" --quiet
    fi

    gcloud compute instances create "$VM_NAME" \
        --zone="$ZONE" \
        --machine-type="$VM_TYPE" \
        --image-family=debian-12 \
        --image-project=debian-cloud \
        --address="$VM_IP" \
        --scopes=cloud-platform \
        --tags="$NET_TAG" \
        --metadata-from-file=startup-script=startup.sh,file-server=file-server.py \
        --metadata=db-host="$DB_IP",db-pass="$DB_PASS"
}

wait_for_server() {
    echo "Waiting for the server on $VM_IP:$PORT (up to 10 minutes)..."
    for _ in $(seq 1 60); do
        if curl -s -o /dev/null --max-time 5 "http://$VM_IP:$PORT/"; then
            echo "Server is up."
            return
        fi
        sleep 10
    done
    echo "Server did not answer yet. Check: gcloud compute instances get-serial-port-output $VM_NAME --zone=$ZONE"
}

# ---------------------------------------- Cloud Function + Scheduler
setup_db_monitor() {
    log "Cloud Function and Scheduler"
    if ! gcloud functions describe "$FUNCTION_NAME" --region="$REGION" >/dev/null 2>&1; then
        gcloud functions deploy "$FUNCTION_NAME" \
            --gen2 \
            --runtime=python312 \
            --region="$REGION" \
            --source=cloud_function \
            --entry-point=stop_db \
            --trigger-topic="$STOP_TOPIC"
    else
        echo "Function $FUNCTION_NAME already deployed."
    fi

    if ! gcloud scheduler jobs describe "$SCHEDULER_JOB" --location="$REGION" >/dev/null 2>&1; then
        gcloud scheduler jobs create pubsub "$SCHEDULER_JOB" \
            --location="$REGION" \
            --schedule="0 * * * *" \
            --topic="$STOP_TOPIC" \
            --message-body="check"
    fi

    # We are about to use the database, so pause the auto-stop.
    # cleanup.sh resumes it.
    gcloud scheduler jobs pause "$SCHEDULER_JOB" --location="$REGION" >/dev/null 2>&1 || true
    echo "Scheduler job $SCHEDULER_JOB is paused while you work."
}

# ================================ main ================================
enable_apis
setup_static_ip
setup_database
setup_topics
setup_firewall
setup_db_monitor
setup_vm
wait_for_server

log "Done"
echo "Server: http://$VM_IP:$PORT/"
echo "DB IP:  $DB_IP"
echo "Run ./cleanup.sh when you are finished."