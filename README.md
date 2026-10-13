# CS528 Homework 4

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

## Test

There are basically two tools we use to Demonstrate the functionality of the app.

1. The provided client program(`client/http-client`) by the TA.
2. The `curl` command for Linux.

All the tests run in another VM different from that runs the server.

### 1. Create the VM

```bash
gcloud compute instances create hw4-client-vm \
    --zone=us-central1-a \
    --machine-type=e2-micro \
    --image-project=ubuntu-os-cloud \
    --image-family=ubuntu-2404-lts-amd64 \
    --no-service-account \
    --no-scopes
```

Then copy the client into the VM(Attention: The http-client should correspond to the kernel of the VM):
```bash
gcloud compute scp http-client hw4-client-vm:~ --zone=us-central1-a

gcloud compute ssh hw4-client-vm --zone=us-central1-a

# get the static ip
gcloud compute addresses list
```

Inside the VM, use the provided http client to request 100  of the cloud storage files:
```bash
./http-client -d $IP -p 8000 -b $BUCKET -w $WEBDIR -n 100 -i $INDEX -t 10 -v > results.txt 2>&1

./http-client -d 35.192.34.3 -b cs528-ruoxi-pagerank -w pages -n 100 -i 12000 -p 8000 -t 10 -v > results.txt 2>&1

grep -c "200 OK" results.txt # the output should be #requests
```


Here are the detailed parameters for the provided http client.

| Short | Long | Argument | Description |
|---|---|---|---|
| `-h` | `--help` | | Show the help message and exit |
| `-d` | `--domain` | `DOMAIN` | Domain to make requests to |
| `-b` | `--bucket` | `BUCKET` | Cloud bucket containing your files. Use `none` if running locally |
| `-w` | `--webdir` | `WEBDIR` | Directory containing your files. Use `none` if you did not make one |
| `-n` | `--num_requests` | `NUM_REQUESTS` | Number of requests to make |
| `-i` | `--index` | `INDEX` | Maximum existing file index |
| `-p` | `--port` | `PORT` | Server port |
| `-f` | `--follow` | | Follow redirects |
| `-s` | `--ssl` | | Use HTTPS |
| `-v` | `--verbose` | | Print the responses from the server on stdout |
| `-r` | `--random` | `RANDOM` | Initial random seed |
| `-t` | `--timeout` | `TIMEOUT` | Timeout in seconds for requests |

