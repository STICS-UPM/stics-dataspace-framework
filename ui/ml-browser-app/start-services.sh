#!/bin/bash

# IA Assets Browser - Quick Start Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXT_DIR="$PROJECT_ROOT/IAModelHub_Extensiones"
COMPOSE_FILE="$EXT_DIR/docker-compose.yml"

echo "========================================="
echo "  IA Assets Browser - Full Stack Setup  "
echo "========================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    echo "Please start Docker and try again"
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Start infrastructure services
echo "📦 Starting services (PostgreSQL + MinIO + Backend)..."
docker compose -f "$COMPOSE_FILE" up -d

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 10

# Check service status
echo ""
echo "🔍 Checking service status..."
docker compose -f "$COMPOSE_FILE" ps

echo ""
echo "🏥 Health checks..."

# Check backend
if curl -f http://localhost:3000/health > /dev/null 2>&1; then
    echo "✅ Backend is healthy (http://localhost:3000)"
else
    echo "⚠️  Backend is starting... (http://localhost:3000)"
fi

# Check MinIO
if curl -f http://localhost:9000/minio/health/live > /dev/null 2>&1; then
    echo "✅ MinIO is healthy (http://localhost:9000)"
else
    echo "⚠️  MinIO is starting... (http://localhost:9000)"
fi

# Check PostgreSQL
if docker exec ml-assets-postgres pg_isready -U ml_assets_user > /dev/null 2>&1; then
    echo "✅ PostgreSQL is healthy (localhost:5432)"
else
    echo "⚠️  PostgreSQL is starting... (localhost:5432)"
fi

echo ""
echo "========================================="
echo "  Services are ready! 🎉"
echo "========================================="
echo ""
echo "📍 Access points:"
echo "   • Backend API:     http://localhost:3000"
echo "   • MinIO Console:   http://localhost:9001 (minioadmin / minioadmin123)"
echo "   • PostgreSQL:      localhost:5432"
echo "   • pgAdmin:         http://localhost:5050 (admin@ml-assets.local / admin123)"
echo ""
echo "📝 Next steps:"
echo "   1. Start the frontend:"
echo "      npm start"
echo ""
echo "   2. Open browser:"
echo "      http://localhost:4200"
echo ""
echo "   3. Create an ML Asset with file upload!"
echo ""
echo "📚 Documentation: SETUP_GUIDE.md"
echo ""
echo "🛑 To stop services:"
echo "   docker compose -f \"$COMPOSE_FILE\" down"
echo ""
