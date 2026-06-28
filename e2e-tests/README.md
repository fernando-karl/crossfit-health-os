# CrossFit Health OS - Playwright E2E Test Suite

## Overview
Automated end-to-end tests for all user workflows using Playwright.

## Setup

```bash
# Install dependencies
cd e2e-tests
npm install
npx playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env with your BASE_URL
```

## Running Tests

```bash
# Run all tests
npx playwright test

# Run with UI (headed mode)
npx playwright test --headed

# Run specific test file
npx playwright test tests/auth.spec.js

# Run specific test
npx playwright test tests/auth.spec.js --grep "login success"

# Run with trace viewer (on failure)
npx playwright test --trace on
```

## Test Coverage

| Test File | Description |
|-----------|-------------|
| `public-pages.spec.js` | Landing, login, register, legal pages, auth redirect |
| `dashboard.spec.js` | Authenticated dashboard, CHOS/JS, onboarding prompt |
| `onboarding.spec.js` | Multi-step onboarding wizard |
| `navigation.spec.js` | Desktop navbar + mobile bottom tabs |
| `feature-pages.spec.js` | Training, nutrition, health, schedule, reviews, profile |
| `auth.spec.js` | Login, registration, password reset (legacy copy assertions) |
| `edge-cases.spec.js` | Error handling, input validation |

**BASE_URL:** production systemd runs on `http://127.0.0.1:8003`; use `http://localhost:8000` for local uvicorn/docker.

## Test Structure

```
e2e-tests/
├── playwright.config.js
├── .env.example
├── package.json
├── tests/
│   ├── auth.spec.js          # Login, registration, password reset
│   ├── onboarding.spec.js    # New user onboarding flow
│   ├── dashboard.spec.js     # Dashboard and navigation
│   ├── profile.spec.js       # Profile management
│   ├── training.spec.js      # Training features
│   ├── nutrition.spec.js     # Nutrition features
│   ├── health.spec.js        # Health/biometrics features
│   └── edge-cases.spec.js    # Error handling, edge cases
└── utils/
    ├── fixtures.js           # Test data fixtures
    └── helpers.js            # API helpers, utilities
```
