# ML Models Browser

Standalone Angular 17 component to explore, manage, and create Machine Learning assets in a data space based on Eclipse Dataspace Connector (EDC).

## 📋 Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Development](#development)
- [Testing](#testing)
- [Architecture](#architecture)
- [EDC Integration](#edc-integration)

## ✨ Features

### ML Asset Management
- **IA Assets Browser**: Grid/list view of Machine Learning models
- **Asset Creation**: Full form with validation to create new IA assets
- **Asset Details**: Detailed view of each asset with all metadata
- **Advanced Filters**: By storage type, format, ML task, etc.

### ML Metadata (JS_Pionera_Ontology)
- **Dynamic Vocabulary**: Loads options from JSON-LD
- **7 ML Fields**:
  - Task (10 options)
  - Subtask (25 options)
  - Algorithm (27 options)
  - Library (19 options)
  - Framework (12 options)
  - Software (21 options)
  - Format (15 options)

### Navigation and UI
- **Responsive Layout**: Sidebar menu, top toolbar
- **4 Sections**: IA Assets Browser, Create ML Asset, Catalog, Contracts
- **Material Design**: Angular Material 17 with custom theme

## 📦 Prerequisites

- Node.js >= 18.x
- npm >= 9.x
- Angular CLI 17.x
- Running EDC Connector

## 🚀 Installation

```bash
cd IAModelHub/IAModelHub_EDCUI/ml-browser-app
npm install
```

## ⚙️ Configuration

Edit `src/environments/environment.ts`:

```typescript
export const environment = {
  runtime: {
    managementApiUrl: 'http://localhost:19193/management',
    catalogUrl: 'http://localhost:19193/management/federatedcatalog',
    participantId: 'connector-demo'
  }
};
```

## 🎯 Usage

### Development

```bash
npm start
# Open http://localhost:4200
```

### Production

```bash
npm run build
# Files in dist/ml-browser-app/
```

## 🧪 Testing

```bash
npm test                 # Unit tests
npm run test:coverage    # With coverage
```

## 📝 Full Documentation

See the original `README.md` for extended documentation.
