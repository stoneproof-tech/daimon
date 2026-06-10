#!/usr/bin/env bash
#
# setup_vps.sh — porta online un nodo seed di DAIMON su Ubuntu 24.04 (idempotente).
#
# Installa dipendenze, clona/aggiorna il repo, crea un venv e installa il package,
# genera UN NUOVO wallet che nasce e resta sul server (mai trasmesso), configura il
# firewall (solo SSH + porta nodo) e installa+avvia il servizio systemd.
#
# Uso (sul VPS, come utente con sudo):
#     curl -fsSL https://raw.githubusercontent.com/stoneproof-tech/daimon/main/deploy/setup_vps.sh | sudo bash
#   oppure dopo il clone:
#     sudo bash deploy/setup_vps.sh
#
# Rieseguibile in sicurezza: aggiorna il codice e riavvia il servizio, senza mai
# sovrascrivere un wallet già esistente.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/stoneproof-tech/daimon}"
APP_DIR="${APP_DIR:-/opt/daimon}"
DATA_DIR="${DATA_DIR:-/var/lib/daimon}"
RUN_USER="${RUN_USER:-daimon}"
NODE_PORT="${NODE_PORT:-9101}"
WALLET="${DATA_DIR}/node.wallet"
UNIT="/etc/systemd/system/daimon-node.service"

log() { echo -e "\n\033[1;36m›› $*\033[0m"; }

if [[ $EUID -ne 0 ]]; then
  echo "Esegui con sudo/root." >&2
  exit 1
fi

# ── 1. Utente di servizio non-root ───────────────────────────────────────────
log "Utente di servizio '${RUN_USER}'"
if ! id -u "${RUN_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/${RUN_USER}" \
          --shell /usr/sbin/nologin "${RUN_USER}"
  echo "creato."
else
  echo "già presente."
fi

# ── 2. Dipendenze di sistema ─────────────────────────────────────────────────
log "Installazione pacchetti (python3, venv, pip, git)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git

# ── 3. Codice: clone o aggiornamento ─────────────────────────────────────────
log "Repository in ${APP_DIR}"
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" fetch --depth 1 origin main
  git -C "${APP_DIR}" reset --hard origin/main
  echo "aggiornato."
else
  git clone --depth 1 "${REPO_URL}" "${APP_DIR}"
  echo "clonato."
fi
chown -R "${RUN_USER}:${RUN_USER}" "${APP_DIR}"

# ── 4. Virtualenv + install del package ──────────────────────────────────────
log "Virtualenv e installazione (pip install -e .)"
if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install --upgrade pip >/dev/null
"${APP_DIR}/.venv/bin/pip" install -e "${APP_DIR}"
chown -R "${RUN_USER}:${RUN_USER}" "${APP_DIR}/.venv"

# ── 5. Wallet del nodo: NUOVO, generato e custodito sul server ────────────────
log "Wallet del nodo in ${WALLET}"
install -d -o "${RUN_USER}" -g "${RUN_USER}" -m 700 "${DATA_DIR}"
if [[ ! -f "${WALLET}" ]]; then
  sudo -u "${RUN_USER}" "${APP_DIR}/.venv/bin/daimon" wallet new --out "${WALLET}"
  echo "wallet creato (la chiave privata resta solo qui)."
else
  echo "wallet già presente: non lo tocco."
fi
chown "${RUN_USER}:${RUN_USER}" "${WALLET}"
chmod 600 "${WALLET}"
NODE_ADDR="$(sudo -u "${RUN_USER}" "${APP_DIR}/.venv/bin/daimon" wallet show --wallet "${WALLET}" | awk '{print $2}')"

# ── 6. Firewall: SICURO sui server condivisi/di produzione ───────────────────
# NON attiviamo MAI ufw e NON tocchiamo le regole esistenti: su una macchina con
# altri servizi (es. Traefik su 80/443) attivarlo con default-deny, o riscriverne
# le regole, taglierebbe quei servizi. Se ufw è già ATTIVO ci limitiamo ad
# AGGIUNGERE la porta del nodo; se è inattivo o assente, non lo tocchiamo.
log "Firewall (modalità sicura per server condivisi)"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  echo "    ufw ATTIVO: aggiungo solo 'allow ${NODE_PORT}/tcp' (regole esistenti intatte)."
  ufw allow "${NODE_PORT}/tcp" >/dev/null
  ufw status | grep -Ei "status|${NODE_PORT}" | sed 's/^/    /'
else
  echo "    ufw INATTIVO o assente: NON lo attivo (eviterei di tagliare altri servizi)."
  echo "    Se è presente un firewall del provider (cloud firewall), apri ${NODE_PORT}/tcp lì."
fi

# ── 7. Servizio systemd ──────────────────────────────────────────────────────
log "Servizio systemd daimon-node"
cp "${APP_DIR}/deploy/daimon-node.service" "${UNIT}"
systemctl daemon-reload
systemctl enable daimon-node >/dev/null 2>&1 || true
systemctl restart daimon-node
sleep 2
systemctl --no-pager --full status daimon-node | sed 's/^/    /' || true

# ── 8. Riepilogo ─────────────────────────────────────────────────────────────
IP="$(curl -fsSL https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
log "FATTO — nodo seed online"
echo "    indirizzo miner del nodo : ${NODE_ADDR}"
echo "    seed node (per unirsi)   : ${IP}:${NODE_PORT}"
echo "    log in tempo reale       : journalctl -u daimon-node -f"
echo "    stato                    : systemctl status daimon-node"
