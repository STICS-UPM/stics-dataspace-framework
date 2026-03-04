#!/bin/bash

###############################################################################
# IA EDC Connector - Application Startup Script
###############################################################################

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXT_DIR="$PROJECT_ROOT/IAModelHub_Extensiones"
BACKEND_DIR="$EXT_DIR/backend"
COMPOSE_FILE="$EXT_DIR/docker-compose.yml"
FRONTEND_DIR="$SCRIPT_DIR"

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║         IA EDC CONNECTOR - STARTUP SCRIPT                            ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 || netstat -tuln 2>/dev/null | grep -q ":$port " || ss -tuln 2>/dev/null | grep -q ":$port "; then
        return 0
    else
        return 1
    fi
}

# Function to wait for service
wait_for_service() {
    local url=$1
    local max_attempts=30
    local attempt=1
    
    echo "   Waiting for service at $url..."
    while [ $attempt -le $max_attempts ]; do
        if curl -s -f "$url" > /dev/null 2>&1; then
            echo "   ✓ Service is ready!"
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    
    echo "   ✗ Service failed to start"
    return 1
}

# Step 1: Check and start Docker containers
echo "[1/5] Checking Docker containers..."
if ! docker compose -f "$COMPOSE_FILE" ps | grep -q "ml-assets-postgres.*running"; then
    echo "   Starting PostgreSQL and MinIO containers..."
    cd "$EXT_DIR"
    docker compose -f "$COMPOSE_FILE" up -d postgres minio minio-setup
    sleep 5
else
    echo "   ✓ Docker containers already running"
fi

# Step 2: Stop existing processes
echo ""
echo "[2/5] Stopping existing processes..."
pkill -f "node.*server-edc.js" 2>/dev/null || true
pkill -f "ng serve" 2>/dev/null || true
sleep 2
echo "   ✓ Processes stopped"

# Step 3: Start Backend
echo ""
echo "[3/5] Starting Backend (EDC Runtime)..."
cd "$BACKEND_DIR"
nohup node src/server-edc.js > server.log 2>&1 &
BACKEND_PID=$!
echo "   Backend started with PID: $BACKEND_PID"

# Wait for backend to be ready
if wait_for_service "http://localhost:3000/health"; then
    echo "   ✓ Backend is healthy"
    
    # Verify CORS configuration
    echo "   Verifying CORS configuration..."
    CORS_ORIGIN=$(curl -s -I -X OPTIONS http://localhost:3000/auth/login \
        -H "Origin: http://localhost:4200" 2>&1 | grep -i "Access-Control-Allow-Origin" | cut -d' ' -f2 | tr -d '\r')
    
    if [ -n "$CORS_ORIGIN" ]; then
        echo "   ✓ CORS configured: $CORS_ORIGIN"
    else
        echo "   ⚠ Warning: CORS headers not detected (but may still work)"
    fi
else
    echo "   ✗ Backend failed to start. Check $BACKEND_DIR/server.log"
    exit 1
fi

# Step 4: Start Frontend
echo ""
echo "[4/5] Starting Frontend (Angular)..."
cd "$FRONTEND_DIR"
nohup npm run start > frontend.log 2>&1 &
FRONTEND_PID=$!
echo "   Frontend started with PID: $FRONTEND_PID"

# Wait for frontend to compile
echo "   Waiting for Angular compilation (this may take 10-15 seconds)..."
sleep 15

if check_port 4200; then
    echo "   ✓ Frontend is running"
else
    echo "   ✗ Frontend failed to start. Check $FRONTEND_DIR/frontend.log"
    exit 1
fi

# Step 5: Display status
echo ""
echo "[5/5] Application Status:"
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                    ALL SERVICES RUNNING                              ║"
echo "╠══════════════════════════════════════════════════════════════════════╣"
echo "║  Frontend:    http://localhost:4200                                  ║"
echo "║  Backend:     http://localhost:3000                                  ║"
echo "║  Health:      http://localhost:3000/health                           ║"
echo "║  PostgreSQL:  localhost:5432                                         ║"
echo "║  MinIO:       http://localhost:9000                                  ║"
echo "╠══════════════════════════════════════════════════════════════════════╣"
echo "║  Credentials:                                                        ║"
echo "║  - user-conn-user1-demo / user1123                                   ║"
echo "║  - user-conn-user2-demo / user2123                                   ║"
echo "╠══════════════════════════════════════════════════════════════════════╣"
echo "║  Logs:                                                               ║"
echo "║  - Backend:  $BACKEND_DIR/server.log"
echo "║  - Frontend: $FRONTEND_DIR/frontend.log"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "💡 To stop all services, run:"
echo "   pkill -f 'node.*server-edc.js'; pkill -f 'ng serve'"
echo ""
echo "📊 To monitor logs in real-time:"
echo "   tail -f $BACKEND_DIR/server.log"
echo "   tail -f $FRONTEND_DIR/frontend.log"
echo ""
