#!/bin/bash
# stress.sh Usage: ./stress.sh [#clients] [duration]
SERVER=35.192.34.3        # STATIC IP of the server 
N=${1:-4}
DURATION=${2:-180}

date
for i in $(seq 1 $N); do
    timeout $DURATION ./http-client -d $SERVER -p 8000 \
        -b cs528-ruoxi-pagerank -w pages -i 12000 \
        -n 1000000 -t 10 -r $i > client_$i.log 2>&1 &
done
wait
date