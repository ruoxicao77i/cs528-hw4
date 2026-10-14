#!/bin/bash
# stress.sh  Usage: ./stress.sh [#clients] [duration_seconds] [client_timeout_seconds]
SERVER=35.192.34.3        # STATIC IP of the server 
N=${1:-4}
DURATION=${2:-180}
T=${3:-1}

date
for i in $(seq 1 $N); do
    timeout $DURATION ./http-client -d $SERVER -p 8000 \
        -b cs528-ruoxi-pagerank -w pages -i 12000 \
        -n 1000000 -t $T -r $i > client_$i.log 2>&1 &
done
wait
date