#!/bin/bash
# create_client_vm.sh  Usage: ./scripts/create_client_vm.sh [vm_name] [zone]
# Creates a client VM and copies stress.sh and the Linux http-client into its home directory.
# Run from the repo root.
set -euo pipefail

VM_NAME=${1:-hw4-client-vm}
ZONE=${2:-us-central1-a}          # same zone as hw4-vm
MACHINE_TYPE=e2-small

gcloud compute instances create "$VM_NAME" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --image-project=debian-cloud \
    --image-family=debian-12

# sshd needs a moment after the instance is created, so retry the copy
for attempt in $(seq 1 10); do
    if gcloud compute scp scripts/stress.sh client/http-client-linux "$VM_NAME":~ --zone="$ZONE"; then
        break
    fi
    if [ "$attempt" -eq 10 ]; then
        echo "Could not copy files to $VM_NAME" >&2
        exit 1
    fi
    echo "SSH not ready yet, retrying in 10s ($attempt/10)..."
    sleep 10
done

# stress.sh runs ./http-client
gcloud compute ssh "$VM_NAME" --zone="$ZONE" \
    --command="mv http-client-linux http-client && chmod +x http-client stress.sh"

echo "Done. Log in with: gcloud compute ssh $VM_NAME --zone=$ZONE"
