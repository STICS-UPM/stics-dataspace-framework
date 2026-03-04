# IA EDC Connector - Quick Start Guide

## 🚀 Start the application

### Option 1: Automatic script (recommended)
```bash
cd /home/edmundo/IAModelHub/IAModelHub_EDCUI/ml-browser-app
./start-application.sh
```
The script:
- Starts PostgreSQL and MinIO (Docker)
- Stops previous processes
- Starts the EDC backend (port 3000)
- Starts the Angular frontend (port 4200)
- Verifies the stack is healthy

### Option 2: Manual start
```bash
# 1. Start Docker containers
cd /home/edmundo/IAModelHub/IAModelHub_Extensiones
docker compose up -d postgres minio minio-setup

# 2. Start backend
cd /home/edmundo/IAModelHub/IAModelHub_Extensiones/backend
node src/server-edc.js

# 3. Start frontend (separate terminal)
cd /home/edmundo/IAModelHub/IAModelHub_EDCUI/ml-browser-app
npm run start
```

## 🛑 Stop the application
```bash
cd /home/edmundo/IAModelHub/IAModelHub_EDCUI/ml-browser-app
./stop-application.sh
```

## 🌐 Access URLs
- Frontend: http://localhost:4200
- Backend API: http://localhost:3000
- Health Check: http://localhost:3000/health
- MinIO Console: http://localhost:9001

## 🔐 Credentials
- User 1: `user-conn-user1-demo / user1123`
- User 2: `user-conn-user2-demo / user2123`

## 🐛 Troubleshooting
### "Failed to fetch" on login
1) Backend not running
```bash
curl http://localhost:3000/health
cd /home/edmundo/IAModelHub/IAModelHub_Extensiones/backend && node src/server-edc.js
```
2) CORS misconfigured (already fixed: full CORS + OPTIONS handling).
3) Browser cache: hard reload (Ctrl+Shift+R) or DevTools → Network → Disable cache.
4) Frontend build errors
```bash
tail -50 /home/edmundo/IAModelHub/IAModelHub_EDCUI/ml-browser-app/frontend.log
```

### Check service status
```bash
ss -tlnp | grep -E "3000|4200|5432|9000"
ps aux | grep node
cd /home/edmundo/IAModelHub/IAModelHub_Extensiones && docker compose ps
```

### Live logs
```bash
tail -f /home/edmundo/IAModelHub/IAModelHub_Extensiones/backend/server.log
tail -f /home/edmundo/IAModelHub/IAModelHub_EDCUI/ml-browser-app/frontend.log
```

## 📝 Key endpoints
### Authentication
```bash
curl -X POST http://localhost:3000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"user-conn-user1-demo","password":"user1123"}'
```

### Assets
```bash
curl -X POST http://localhost:3000/v3/assets/request \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Contract Definitions
```bash
curl -X POST http://localhost:3000/v3/contractdefinitions/request \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Catalog
```bash
curl -X POST http://localhost:3000/v3/catalog/request \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 🔧 Configuration
### Backend environment variables
```bash
PORT=3000
NODE_ENV=development
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ml_assets_db
DB_USER=ml_assets_user
DB_PASSWORD=ml_assets_password
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin123
S3_BUCKET=ml-assets
S3_REGION=us-east-1
CORS_ORIGIN=http://localhost:4200
```

### Frontend environment
Set in `src/environments/environment.ts`:
- `managementApiUrl`: `http://localhost:3000`
- `catalogUrl`: `http://localhost:3000`

## 📚 More information
- See project root `README.md` and `DEPLOYMENT.md` for full details.
- Start/stop scripts: `start-application.sh`, `start-services.sh`, `stop-application.sh`.
- Last updated: 2025-12-11
