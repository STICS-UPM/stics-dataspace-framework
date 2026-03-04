# Permanent Configuration - IA EDC Connector

## ⚠️ Critical changes - do not revert
These settings **must remain** to avoid CORS and runtime issues.

### ✅ Keep: CORS configuration with multiple origins
Location: `backend/src/server-edc.js`
```javascript
const allowedOrigins = [
  'http://localhost:4200',
  'http://127.0.0.1:4200',
  process.env.CORS_ORIGIN
].filter(Boolean);

const corsOptions = {
  origin: (origin, callback) => {
    if (!origin || allowedOrigins.includes(origin)) return callback(null, true);
    return callback(new Error(`CORS origin not allowed: ${origin}`));
  },
  credentials: true,
  methods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization', 'X-Requested-With', 'Accept'],
  exposedHeaders: ['Content-Range', 'X-Content-Range'],
  maxAge: 86400,
  optionsSuccessStatus: 204
};

app.use(cors(corsOptions));
app.options('*', cors(corsOptions));
```

### ✅ Keep: Explicit OPTIONS handler
Location: `backend/edc-extensions/management-api/extension.manifest.js`
```javascript
router.options('*', (req, res) => res.status(204).end());
```

### ❌ Do not remove
- OPTIONS handler above
- CORS headers and options
- Allowed origins list

### ✅ Post-change checks
- `curl -I -X OPTIONS http://localhost:3000/auth/login -H "Origin: http://localhost:4200"` returns `204` and CORS headers.
- Frontend login works without “Failed to fetch”.

### 🚨 Symptoms of issues
- Login returns CORS errors in browser console.
- `OPTIONS` requests respond 404/500 instead of 204.
- Missing `Access-Control-Allow-Origin` in responses.

### Notes
- `CORS_ORIGIN` env var, when set, is added to allowed origins.
- Keep these sections intact when editing backend middleware.

**Last updated:** 2025-12-12
