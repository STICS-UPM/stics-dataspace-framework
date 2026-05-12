#!/bin/bash
# Sets up nginx reverse proxy on the VM host to expose Minikube services
# via a caller-provided public hostname.
#
# Run as:
#   bash setup-nginx-proxy.sh [minikube_ip] [vm_ip] [public_hostname] [internal_domain]

set -e

MINIKUBE_IP="${1:-192.168.49.2}"
VM_IP="${2:-$(hostname -I | awk '{print $1}')}"
PUBLIC_HOST="${3:-}"
INTERNAL_DOMAIN="${4:-dev.ds.dataspaceunit.upm}"
KC_ADMIN_PASSWORD="${KC_ADMIN_PASSWORD:-change-me}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [ -z "$VM_IP" ] || [ -z "$PUBLIC_HOST" ]; then
    echo "Usage: bash setup-nginx-proxy.sh [minikube_ip] [vm_ip] <public_hostname> [internal_domain]" >&2
    echo "Example: bash setup-nginx-proxy.sh 192.168.49.2 203.0.113.10 public.example.org dev.ds.dataspaceunit.upm" >&2
    exit 2
fi

echo "[1/5] Installing nginx and iptables-persistent..."
sudo apt-get install -y nginx iptables-persistent

echo "[2/5] Configuring iptables DNAT (VM IP → Minikube)..."
# Remove existing rules if present
sudo iptables -t nat -D PREROUTING -d ${VM_IP} -p tcp --dport 80 -j DNAT --to-destination ${MINIKUBE_IP}:80 2>/dev/null || true
sudo iptables -t nat -D POSTROUTING -d ${MINIKUBE_IP} -j MASQUERADE 2>/dev/null || true
sudo iptables -t nat -D OUTPUT -d ${VM_IP} -p tcp --dport 80 -j DNAT --to-destination ${MINIKUBE_IP}:80 2>/dev/null || true

sudo iptables -t nat -A PREROUTING -d ${VM_IP} -p tcp --dport 80 -j DNAT --to-destination ${MINIKUBE_IP}:80
sudo iptables -t nat -A POSTROUTING -d ${MINIKUBE_IP} -j MASQUERADE
sudo iptables -t nat -A OUTPUT -d ${VM_IP} -p tcp --dport 80 -j DNAT --to-destination ${MINIKUBE_IP}:80
sudo netfilter-persistent save

echo "[3/5] Generating app.config.json for connector interfaces..."
sudo mkdir -p /var/www/connector-configs

for CONNECTOR in citycouncil company; do
    # Map connector name to full connector name
    if [ "$CONNECTOR" = "citycouncil" ]; then
        CONN_NAME="conn-citycouncil-demo"
    else
        CONN_NAME="conn-company-demo"
    fi

    # Find pod name
    POD=$(kubectl get pods -n demo -l "app.kubernetes.io/name=${CONN_NAME}-interface" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || \
          kubectl get pods -n demo | grep "${CONN_NAME}-int" | awk '{print $1}' | head -1)

    if [ -z "$POD" ]; then
        echo "  WARNING: pod for ${CONN_NAME} interface not found, skipping config patch"
        continue
    fi

    CONFIG_PATH="/usr/share/nginx/html/inesdata-connector-interface/assets/config/app.config.json"
    echo "  Patching config for ${CONNECTOR} (pod: ${POD})..."

    kubectl exec -n demo "$POD" -- cat "$CONFIG_PATH" | python3 -c "
import sys, json
c = json.load(sys.stdin)
base = 'https://${PUBLIC_HOST}'
conn = '${CONNECTOR}'
c['managementApiUrl'] = f'{base}/c/{conn}/management'
c['catalogUrl']       = f'{base}/c/{conn}/federatedcatalog'
c['sharedUrl']        = f'{base}/c/{conn}/shared'
c['oauth2']['issuer'] = f'{base}/auth/realms/demo'
c['oauth2']['allowedUrls'] = base
print(json.dumps(c, indent=2))
" | sudo tee /var/www/connector-configs/app.config.${CONNECTOR}.json > /dev/null

    # Also patch in-pod for consistency
    kubectl exec -n demo "$POD" -- cat "$CONFIG_PATH" | python3 -c "
import sys, json
c = json.load(sys.stdin)
base = 'https://${PUBLIC_HOST}'
conn = '${CONNECTOR}'
c['managementApiUrl'] = f'{base}/c/{conn}/management'
c['catalogUrl']       = f'{base}/c/{conn}/federatedcatalog'
c['sharedUrl']        = f'{base}/c/{conn}/shared'
c['oauth2']['issuer'] = f'{base}/auth/realms/demo'
c['oauth2']['allowedUrls'] = base
print(json.dumps(c, indent=2))
" | kubectl exec -n demo "$POD" -i -- tee "$CONFIG_PATH" > /dev/null

    echo "  Done: /var/www/connector-configs/app.config.${CONNECTOR}.json"
done

echo "[4/5] Writing nginx config..."
sudo tee /etc/nginx/sites-enabled/pionera-dataspace.conf > /dev/null << NGINXEOF
server {
    listen ${VM_IP}:80;
    server_name ${PUBLIC_HOST};

    location = /inesdata-connector-interface/assets/config/app.config.json {
        alias /var/www/connector-configs/app.config.citycouncil.json;
        default_type application/json;
        add_header Cache-Control "no-store, no-cache, must-revalidate";
    }
    location = /c/citycouncil/inesdata-connector-interface/assets/config/app.config.json {
        alias /var/www/connector-configs/app.config.citycouncil.json;
        default_type application/json;
        add_header Cache-Control "no-store, no-cache, must-revalidate";
    }
    location = /c/company/inesdata-connector-interface/assets/config/app.config.json {
        alias /var/www/connector-configs/app.config.company.json;
        default_type application/json;
        add_header Cache-Control "no-store, no-cache, must-revalidate";
    }

    location = / {
        default_type text/html;
        return 200 "<html><body><h1>INESData Environment</h1><ul><li><a href=\"/c/citycouncil/inesdata-connector-interface/\">Citycouncil Connector</a></li><li><a href=\"/c/company/inesdata-connector-interface/\">Company Connector</a></li><li><a href=\"/auth/\">Keycloak</a></li><li><a href=\"/s3-console/\">MinIO Console</a></li></ul></body></html>";
    }

    location /auth/ {
        rewrite ^/auth/(.*) /\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host auth.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Accept-Encoding "";
        sub_filter_types application/json text/html;
        sub_filter_once off;
        sub_filter "http://auth.${INTERNAL_DOMAIN}/realms/"    "https://${PUBLIC_HOST}/auth/realms/";
        sub_filter "http://auth.${INTERNAL_DOMAIN}/resources/" "https://${PUBLIC_HOST}/auth/resources/";
        sub_filter "http://auth.${INTERNAL_DOMAIN}/js/"        "https://${PUBLIC_HOST}/auth/js/";
    }

    location /s3/ {
        rewrite ^/s3/(.*) /\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host minio.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /s3-console/ {
        rewrite ^/s3-console/(.*) /\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host console.minio-s3.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /rs-demo/ {
        rewrite ^/rs-demo/(.*) /\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host registration-service-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /c/citycouncil/management/ {
        rewrite ^/c/citycouncil/management/(.*) /management/\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host conn-citycouncil-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        client_max_body_size 0;
    }

    location /c/citycouncil/shared/ {
        rewrite ^/c/citycouncil/shared/(.*) /shared/\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host conn-citycouncil-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /c/citycouncil/federatedcatalog/ {
        rewrite ^/c/citycouncil/federatedcatalog/(.*) /management/federatedcatalog/\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host conn-citycouncil-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /c/citycouncil/ {
        rewrite ^/c/citycouncil/(.*) /\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host conn-citycouncil-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /c/company/management/ {
        rewrite ^/c/company/management/(.*) /management/\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host conn-company-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        client_max_body_size 0;
    }

    location /c/company/shared/ {
        rewrite ^/c/company/shared/(.*) /shared/\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host conn-company-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /c/company/federatedcatalog/ {
        rewrite ^/c/company/federatedcatalog/(.*) /management/federatedcatalog/\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host conn-company-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /c/company/ {
        rewrite ^/c/company/(.*) /\$1 break;
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host conn-company-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /inesdata-connector-interface/ {
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host conn-citycouncil-demo.${INTERNAL_DOMAIN};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}

server {
    listen ${VM_IP}:80;
    server_name *.${PUBLIC_HOST};

    location / {
        proxy_pass http://${MINIKUBE_IP};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        client_max_body_size 0;
    }
}
NGINXEOF

sudo nginx -t && sudo systemctl enable nginx && sudo systemctl restart nginx
echo "  nginx configured and started"

echo "[5/5] Setting Keycloak realm frontendUrl..."
KC_URL="http://auth.${INTERNAL_DOMAIN}"
KC_TOKEN=$(curl -s -X POST "${KC_URL}/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=admin-cli&username=admin&password=${KC_ADMIN_PASSWORD}&grant_type=password" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

REALM=$(curl -s "${KC_URL}/admin/realms/demo" -H "Authorization: Bearer $KC_TOKEN")
UPDATED=$(echo "$REALM" | python3 -c "
import sys,json
r = json.load(sys.stdin)
r.setdefault('attributes', {})['frontendUrl'] = 'https://${PUBLIC_HOST}/auth'
print(json.dumps(r))
")
curl -s -o /dev/null -w "%{http_code}" -X PUT \
    "${KC_URL}/admin/realms/demo" \
    -H "Authorization: Bearer $KC_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$UPDATED"
echo ""
echo "  Keycloak frontendUrl set to https://${PUBLIC_HOST}/auth"

echo ""
echo "=========================================="
echo "Setup complete. URLs:"
echo "  https://${PUBLIC_HOST}/c/citycouncil/inesdata-connector-interface/"
echo "  https://${PUBLIC_HOST}/c/company/inesdata-connector-interface/"
echo "  https://${PUBLIC_HOST}/auth/"
echo "  https://${PUBLIC_HOST}/s3-console/"
echo "=========================================="
