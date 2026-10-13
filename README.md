## Deployment

The web server runs on a Compute Engine VM with a static IP. A startup script installs the dependencies, pulls this repo, and starts the server every time the VM boots, so no manual SSH step is needed.

The VM runs as a dedicated service account. No key file is used on the VM: the client libraries get credentials from the VM's attached service account automatically.

### 0. Set variables

Run all commands below from the repo root on your local machine. Change these values first.

```bash
PROJECT_ID=your-project-id
REGION=us-central1               # same region as the homework 2 bucket
ZONE=us-central1-a
BUCKET=your-hw2-bucket            # bucket from homework 2
SA_NAME=file-server-sa
SA_EMAIL=$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com
VM_NAME=hw4-vm
IP_NAME=hw4-ip
TOPIC=forbidden-requests

gcloud config set project $PROJECT_ID
```

### 1. Enable the APIs

```bash
gcloud services enable compute.googleapis.com storage.googleapis.com \
    logging.googleapis.com pubsub.googleapis.com
```

### 2. Create the service account

```bash
gcloud iam service-accounts create $SA_NAME \
    --display-name="HW4 file server"
```

### 3. Grant only the roles the server needs

Each role is granted on the narrowest resource possible.

```bash
# Read files from the homework 2 bucket (read only, on this bucket only)
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
    --member=serviceAccount:$SA_EMAIL --role=roles/storage.objectViewer

# Write logs to Cloud Logging
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member=serviceAccount:$SA_EMAIL --role=roles/logging.logWriter

# Publish to the forbidden-requests topic only
gcloud pubsub topics create $TOPIC    # skip if it already exists
gcloud pubsub topics add-iam-policy-binding $TOPIC \
    --member=serviceAccount:$SA_EMAIL --role=roles/pubsub.publisher
```

| Role | Resource | Why |
|---|---|---|
| Storage Object Viewer | homework 2 bucket | Read the requested files |
| Logs Writer | project | Log erroneous requests |
| Pub/Sub Publisher | `forbidden-requests` topic | Report requests from forbidden countries |

### 4. Reserve a static IP

The region must match the VM's zone.

```bash
gcloud compute addresses create $IP_NAME --region=$REGION

# Show the address
gcloud compute addresses describe $IP_NAME --region=$REGION --format="get(address)"
```

### 5. Open port 8000

```bash
gcloud compute firewall-rules create allow-file-server-8000 \
    --allow=tcp:8000 --target-tags=file-server --source-ranges=0.0.0.0/0
```

The rule only applies to VMs with the `file-server` network tag.

### 6. Create the VM

```bash
gcloud compute instances create $VM_NAME \
    --zone=$ZONE \
    --machine-type=e2-micro \
    --image-project=debian-cloud \
    --image-family=debian-12 \
    --address=$IP_NAME \
    --service-account=$SA_EMAIL \
    --scopes=cloud-platform \
    --tags=file-server \
    --metadata-from-file=startup-script=startup.sh
```

`--scopes=cloud-platform` does not give extra permissions by itself. Access is limited by the IAM roles in step 3.

The startup script takes a minute or two to install packages before the server is up.

### 7. Test

```bash
IP=$(gcloud compute addresses describe $IP_NAME --region=$REGION --format="get(address)")

# GET: file path in the URL, expect 200
curl -i http://$IP:8000/$BUCKET/some-file.html

# POST: file path in the body, expect 200
curl -i -d "$BUCKET/some-file.html" http://$IP:8000/

# Missing file, expect 404
curl -i http://$IP:8000/$BUCKET/no-such-file

# Other methods, expect 501
curl -i -X PUT http://$IP:8000/$BUCKET/some-file.html
curl -I http://$IP:8000/$BUCKET/some-file.html
```

Errors show up in Logs Explorer with this query:

```
logName="projects/PROJECT_ID/logs/file-server"
```

### Troubleshooting

SSH into the VM, then:

```bash
# Did the startup script run without errors?
sudo journalctl -u google-startup-scripts.service

# Server output
cat /var/log/file-server.log

# Does the server answer locally? If yes but not from outside, check the firewall rule.
curl -i http://localhost:8000/$BUCKET/some-file.html

# Run the startup script again without recreating the VM
sudo google_metadata_script_runner startup
```

### Clean up

Delete the VM **and** release the IP. A reserved IP that is not attached to a VM is billed at a higher rate.

```bash
gcloud compute instances delete $VM_NAME --zone=$ZONE
gcloud compute addresses delete $IP_NAME --region=$REGION
gcloud compute firewall-rules delete allow-file-server-8000
```

## Local development

Locally there is no attached service account, so use one of these:

```bash
# Option A: log in with your own Google account (no key file needed)
gcloud auth application-default login

# Option B: use a service account key (never commit it)
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

Then:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python file-server/main.py
```