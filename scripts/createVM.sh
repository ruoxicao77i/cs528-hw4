gcloud compute instances create hw4-VM \
    --image-project=debian-cloud \
    --image-family=debian-10 \
    --metadata-from-file=startup-script=startup.sh