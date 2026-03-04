#!/bin/bash

###############################################################################
# IA EDC Connector - Application Shutdown Script
###############################################################################

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║         IA EDC CONNECTOR - SHUTDOWN SCRIPT                           ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXT_DIR="$PROJECT_ROOT/IAModelHub_Extensiones"
COMPOSE_FILE="$EXT_DIR/docker-compose.yml"

echo "[1/3] Stopping Backend (Node.js)..."
if pkill -f "node.*server-edc.js"; then
    echo "   ✓ Backend stopped"
else
    echo "   ℹ Backend was not running"
fi

echo ""
echo "[2/3] Stopping Frontend (Angular)..."
if pkill -f "ng serve"; then
    echo "   ✓ Frontend stopped"
else
    echo "   ℹ Frontend was not running"
fi

echo ""
echo "[3/3] Docker containers (optional)..."
echo "   Docker containers are still running. To stop them, run:"
echo "   docker compose -f \"$COMPOSE_FILE\" down"

echo ""
echo "✓ Application stopped successfully"
echo ""
