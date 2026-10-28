#!/bin/bash
# Runs as root on every boot. Only does the real setup the first time.

if [ -f /var/log/startup_already_done ]; then
    echo "Startup script already ran once. Skipping."
    exit 0
fi

APP_DIR=/opt/hw5
MD_URL=http://metadata.google.internal/computeMetadata/v1/instance/attributes

# 1. Install system packages
apt-get update
apt-get install -y python3-pip python3-venv

# 2. Get the server code and DB settings from the VM metadata
#    (setup.sh passes them in when it creates the VM)
mkdir -p $APP_DIR
curl -s -H "Metadata-Flavor: Google" $MD_URL/file-server > $APP_DIR/file-server.py
DB_HOST=$(curl -s -H "Metadata-Flavor: Google" $MD_URL/db-host)
DB_PASS=$(curl -s -H "Metadata-Flavor: Google" $MD_URL/db-pass)

# 3. Install Python libraries in a virtual environment
python3 -m venv $APP_DIR/venv
$APP_DIR/venv/bin/pip install pymysql google-cloud-storage google-cloud-logging google-cloud-pubsub

# 4. Run the server as a systemd service, so it also starts again after a reboot
cat > /etc/systemd/system/file-server.service <<EOF
[Unit]
Description=HW5 file server
After=network-online.target
Wants=network-online.target

[Service]
Environment=DB_HOST=$DB_HOST
Environment=DB_PASS=$DB_PASS
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python3 $APP_DIR/file-server.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now file-server

# 5. Mark setup as done
touch /var/log/startup_already_done