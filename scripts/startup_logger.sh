#! /bin/bash
apt update
apt-get install -y git python3-venv

APP_DIR=/opt/cs528-hw4

# if the repo exists, then pull; otherwise git clone
if [ -d "$APP_DIR" ]; then
    git -C "$APP_DIR" pull
else
    git clone https://github.com/ruoxicao77i/cs528-hw4.git "$APP_DIR"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

nohup "$APP_DIR/.venv/bin/python" "$APP_DIR/forbidden-logger/main.py" > /var/log/forbidden_requests.log 2>&1 &