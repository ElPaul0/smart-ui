#!/usr/bin/env bash
# Install smart-ui on a Linux host with MegaRAID storcli available.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/smart-ui}"
ENV_FILE="${ENV_FILE:-/etc/smart-ui/smart-ui.env}"
DATA_DIR="${DATA_DIR:-/var/lib/smart-ui}"
REPO_URL="${REPO_URL:-https://github.com/ElPaul0/smart-ui.git}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

STORCLI_BIN="${STORCLI_PATH:-/opt/MegaRAID/storcli/storcli64}"
echo "==> Checking storcli (${STORCLI_BIN})"
if [[ ! -x "${STORCLI_BIN}" ]]; then
  echo "storcli not found at ${STORCLI_BIN}."
  echo "Install Broadcom/LSI storcli and set STORCLI_PATH in ${ENV_FILE}."
  exit 1
fi

echo "==> Installing app into ${APP_DIR}"
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" pull --ff-only
else
  # Preserve local storcli logs if migrating from a bare copy
  if [[ -d "${APP_DIR}" && ! -d "${APP_DIR}/.git" ]]; then
    BACKUP="${APP_DIR}.bak.$(date +%Y%m%d%H%M%S)"
    echo "Backing up existing ${APP_DIR} → ${BACKUP}"
    mv "${APP_DIR}" "${BACKUP}"
  fi
  mkdir -p "$(dirname "${APP_DIR}")"
  git clone "${REPO_URL}" "${APP_DIR}"
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

mkdir -p "$(dirname "${ENV_FILE}")" "${DATA_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${APP_DIR}/.env.example" "${ENV_FILE}"
  if grep -q '^SMART_UI_DB=' "${ENV_FILE}"; then
    sed -i "s|^SMART_UI_DB=.*|SMART_UI_DB=${DATA_DIR}/events.db|" "${ENV_FILE}"
  else
    echo "SMART_UI_DB=${DATA_DIR}/events.db" >> "${ENV_FILE}"
  fi
  echo "Created ${ENV_FILE} — edit ntfy / language before starting."
else
  echo "Keeping existing ${ENV_FILE} (survives updates)."
fi

install -m 644 "${APP_DIR}/deploy/smart-ui.service" /etc/systemd/system/smart-ui.service
sed -i "s|^EnvironmentFile=.*|EnvironmentFile=-${ENV_FILE}|" /etc/systemd/system/smart-ui.service

systemctl daemon-reload
systemctl enable --now smart-ui.service
systemctl --no-pager --full status smart-ui.service || true

echo
echo "Done."
echo "  Config : ${ENV_FILE}"
echo "  Data   : ${DATA_DIR}"
echo "  App    : ${APP_DIR}"
echo "  Health : curl -s http://127.0.0.1:7001/api/health"
echo
echo "Update later with:  sudo APP_DIR=${APP_DIR} $0"
echo "(git pull + pip install; ${ENV_FILE} is left untouched)"
