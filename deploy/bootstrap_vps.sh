#!/usr/bin/env bash
# TradeAI VPS bootstrap — run this ONCE on a fresh Ubuntu 24.04 VPS as root.
# Usage:  sudo bash bootstrap_vps.sh
set -e

echo "═══════════════════════════════════════════════════════════════"
echo "  TradeAI VPS Bootstrap — Ubuntu 24.04"
echo "═══════════════════════════════════════════════════════════════"

# ─── 1. System update ──────────────────────────────────────────
echo "[1/7] System update..."
apt update && apt upgrade -y

# ─── 2. Required packages ──────────────────────────────────────
echo "[2/7] Installing packages..."
apt install -y python3 python3-pip python3-venv git curl ufw fail2ban \
                build-essential libssl-dev libffi-dev sqlite3 htop nano

# ─── 3. Create non-root tradeai user ───────────────────────────
echo "[3/7] Creating tradeai user..."
if ! id tradeai &>/dev/null; then
    useradd -m -s /bin/bash tradeai
    usermod -aG sudo tradeai
    echo "tradeai ALL=(ALL) NOPASSWD: /bin/systemctl restart tradeai, /bin/systemctl restart tradeai-tracker, /bin/systemctl status tradeai, /bin/systemctl status tradeai-tracker, /bin/journalctl" > /etc/sudoers.d/tradeai
    chmod 440 /etc/sudoers.d/tradeai
    echo "  → user 'tradeai' created. Set password next:"
    passwd tradeai
fi

# ─── 4. Firewall ──────────────────────────────────────────────
echo "[4/7] Configuring firewall..."
ufw allow OpenSSH
ufw --force enable

# ─── 5. Fail2ban (brute-force SSH protection) ──────────────────
echo "[5/7] Enabling fail2ban..."
systemctl enable --now fail2ban

# ─── 6. SSH hardening ─────────────────────────────────────────
echo "[6/7] Hardening SSH (disabling root password login)..."
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl restart ssh

# ─── 7. Create TradeAI dirs ────────────────────────────────────
echo "[7/7] Preparing TradeAI directories..."
sudo -u tradeai mkdir -p /home/tradeai/TradeAI/logs
sudo -u tradeai mkdir -p /home/tradeai/TradeAI/data/snapshots
sudo -u tradeai mkdir -p /home/tradeai/TradeAI/data/ohlcv_cache

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Bootstrap complete!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Log out of root, log in as 'tradeai' user:"
echo "       ssh tradeai@<your-vps-ip>"
echo "  2. Clone the TradeAI repo:"
echo "       cd ~ && git clone <your-github-repo-url> TradeAI"
echo "  3. Install Python deps:"
echo "       cd ~/TradeAI && pip install -r requirements.txt --break-system-packages"
echo "  4. Create .env file (see deploy/env.example)"
echo "  5. Install systemd services:"
echo "       sudo cp deploy/tradeai.service /etc/systemd/system/"
echo "       sudo cp deploy/tradeai-tracker.service /etc/systemd/system/"
echo "       sudo systemctl daemon-reload"
echo "       sudo systemctl enable --now tradeai tradeai-tracker"
