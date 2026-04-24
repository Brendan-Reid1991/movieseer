#!/usr/bin/env bash
set -euo pipefail

VPN_DIR="vpn_configurations"
CONF="${1:-}"

if [ -z "$CONF" ]; then
  echo "Usage: ./scripts/set-vpn.sh <config-name>"
  echo ""
  echo "Available configs:"
  ls "$VPN_DIR"/*.conf | xargs -n1 basename | sed 's/\.conf$//'
  exit 1
fi

CONF_FILE="$VPN_DIR/${CONF}.conf"
if [ ! -f "$CONF_FILE" ]; then
  echo "Error: $CONF_FILE not found"
  exit 1
fi

PRIVATE_KEY=$(awk -F' = ' '/^PrivateKey/{print $2}' "$CONF_FILE")
ADDRESSES=$(awk -F' = ' '/^Address/{print $2}' "$CONF_FILE" | tr ',' '\n' | grep -v ':' | tr '\n' ',' | sed 's/,$//')
PUBLIC_KEY=$(awk -F' = ' '/^PublicKey/{print $2}' "$CONF_FILE")
ENDPOINT=$(awk -F' = ' '/^Endpoint/{print $2}' "$CONF_FILE")
ENDPOINT_IP="${ENDPOINT%:*}"
ENDPOINT_PORT="${ENDPOINT#*:}"

cat > "$VPN_DIR/active.env" <<EOF
# Generated from ${CONF}.conf - do not edit manually
WIREGUARD_PRIVATE_KEY=${PRIVATE_KEY}
WIREGUARD_ADDRESSES=${ADDRESSES}
WIREGUARD_PUBLIC_KEY=${PUBLIC_KEY}
VPN_ENDPOINT_IP=${ENDPOINT_IP}
VPN_ENDPOINT_PORT=${ENDPOINT_PORT}
EOF

echo "VPN config set to: $CONF"
echo "Written to: $VPN_DIR/active.env"
