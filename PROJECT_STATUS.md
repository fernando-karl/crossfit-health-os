# 🏋️ CrossFit Health OS - Project Status

**Last Updated:** 2026-02-08  
**Version:** 1.0.0-beta  
**Status:** MVP Complete, Ready for Testing

---

## 📊 Project Summary

**CrossFit Health OS** is an AI-powered elite performance ecosystem integrating biometrics, adaptive training, and nutritional intelligence for CrossFit athletes.

**Core Innovation:** Closed-loop feedback system where recovery metrics automatically adjust training volume and intensity, with weekly AI reviews for progressive optimization.

---

## ✅ Implemented Features

### 1. **AI-Powered Training Programming** 🤖

**Engine:** `backend/app/core/engine/ai_programmer.py`

- GPT-4o generates complete weekly training programs
- Methodologies: HWPO (Mat Fraser), Mayhem (Rich Froning), CompTrain (Ben Bergeron), Custom
- Periodization: Week 1-3 (accumulation) → Week 4 (deload) → Week 5-7 (intensification) → Week 8 (test)
- Session-aware: Short (≤60min) vs Long (>60min) workout structures
- Focus movement support for addressing weaknesses
- Progressive overload based on previous week data

**Endpoint:** `POST /api/v1/schedule/weekly/generate-ai`

**Cost:** ~$0.10 per program (GPT-4o)

---

### 2. **Adaptive Training Engine** 📈

**Engine:** `backend/app/core/engine/adaptive.py`

- Reads recovery metrics: HRV, sleep quality, stress, muscle soreness
- Calculates readiness score (0-100) with weighted formula:
  - HRV: 40%
  - Sleep: 30%
  - Stress (inverted): 20%
  - Soreness (inverted): 10%
- Adjusts workout volume automatically:
  - Readiness ≥80: 1.1x volume (push harder)
  - Readiness 60-79: 1.0x (maintain)
  - Readiness 40-59: 0.8x (reduce)
  - Readiness <40: 0.5x (active recovery only)
- Reasoning generated for every adjustment

**Endpoint:** `POST /api/v1/training/generate`

---

### 3. **Weekly Performance Review System** 🔄

**Engine:** `backend/app/core/engine/weekly_reviewer.py`

- Claude 3.5 Sonnet analyzes weekly performance
- Collects data: sessions, RPE, recovery metrics, feedback
- Identifies 2-3 strengths, 2-3 weaknesses
- Assesses recovery status (optimal/adequate/compromised)
- Evaluates volume appropriateness (too_low/appropriate/too_high)
- Detects progressions (e.g., "Back squat +2kg")
- Recommends specific adjustments for next week:
  - Volume change % (-50 to +50)
  - Intensity change (decrease/maintain/increase)
  - Focus movements to prioritize
  - Skill work minutes to add
  - Mobility work flag

**Endpoints:**
- `POST /api/v1/review/weekly` - Generate review
- `POST /api/v1/review/weekly/{id}/apply` - Auto-apply adjustments

**Cost:** ~$0.15 per review (Claude 3.5 Sonnet)

---

### 4. **Weekly Training Schedule** 📅

**Feature:** User defines training days, times, and session durations

- Up to 3 sessions per day
- Rest day marking
- Duration per session (30-180 minutes)
- Workout type per session (strength, metcon, skill, etc)

**Endpoints:**
- `POST /api/v1/schedule/weekly` - Create schedule
- `GET /api/v1/schedule/weekly/active` - Get active schedule
- `PATCH /api/v1/schedule/weekly/{id}` - Update
- `DELETE /api/v1/schedule/weekly/{id}` - Delete

---

### 5. **Auto Meal Planning** 🍽️

**Feature:** Meals automatically synced with training schedule

- Pre-workout meals: 60min before (configurable)
- Post-workout meals: 30min after (configurable)
- Standard meals: Breakfast (07:00), Lunch (12:00), Dinner (19:00)
- Adjusts for rest days (3 meals) vs training days (5-7 meals)

**Endpoint:** `POST /api/v1/schedule/weekly/{id}/meal-plan`

---

### 6. **Session Feedback Tracking** 📝

**Feature:** Post-workout subjective + objective data

**Tracked:**
- RPE (Rate of Perceived Exertion) 1-10
- Difficulty assessment (too_easy/appropriate/hard_but_manageable/too_hard)
- Technique quality 1-10
- Pacing (too_fast/good/too_slow)
- Energy levels pre/post
- Would repeat boolean
- Movement-specific feedback:
  - Prescribed vs actual sets/reps/weight
  - Breaks taken
  - Technique notes

**Endpoint:** `POST /api/v1/review/feedback`

---

### 7. **Authentication System** 🔐

**Backend Endpoints:**
- `POST /api/v1/auth/register` - User registration with profile
- `POST /api/v1/auth/login` - JWT token authentication
- `POST /api/v1/auth/logout` - Session cleanup
- `POST /api/v1/auth/forgot-password` - Request reset email
- `POST /api/v1/auth/reset-password` - Reset with token
- `POST /api/v1/auth/refresh` - Token refresh

**Features:**
- Password validation (8+ chars, uppercase, lowercase, number)
- Supabase Auth integration
- Email verification ready
- JWT tokens (1 hour expiry)
- Automatic profile creation on signup

---

### 8. **Complete Frontend** 💻

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS

**Pages:**
1. **Landing Page (/)** - Hero, features, pricing, CTA
2. **Register (/register)** - Signup with profile setup
3. **Login (/login)** - Authentication
4. **Forgot Password (/forgot-password)** - Reset request
5. **Dashboard (/dashboard)** - Main app interface

**API Client:** `frontend/lib/api.ts`
- Axios-based HTTP client
- Automatic token injection
- Token expiration handling (401 → login redirect)
- All major endpoints wrapped

**Styling:**
- Custom Tailwind theme (primary blue palette)
- Responsive design (mobile-first)
- Custom utility classes (btn-primary, input-field, card)

---

## 📁 Project Structure

```
crossfit-health-os/
├── backend/                        # FastAPI Python Backend
│   ├── app/
│   │   ├── api/v1/                # API Endpoints
│   │   │   ├── auth.py            # Authentication
│   │   │   ├── training.py        # Training sessions
│   │   │   ├── health.py          # Recovery & biomarkers
│   │   │   ├── nutrition.py       # Meal logging
│   │   │   ├── schedule.py        # Weekly schedules + AI gen
│   │   │   ├── review.py          # Feedback & reviews
│   │   │   ├── users.py           # User management
│   │   │   └── integrations.py   # HealthKit, Calendar
│   │   ├── core/                  # Core Business Logic
│   │   │   ├── engine/
│   │   │   │   ├── adaptive.py    # Adaptive training
│   │   │   │   ├── ai_programmer.py  # AI program generation
│   │   │   │   └── weekly_reviewer.py  # AI reviews
│   │   │   ├── auth.py            # JWT validation
│   │   │   └── config.py          # Settings
│   │   ├── models/                # Pydantic Models
│   │   │   ├── training.py
│   │   │   ├── health.py
│   │   │   └── review.py
│   │   ├── db/                    # Database
│   │   │   ├── supabase.py        # Client
│   │   │   └── helpers.py         # Error handling
│   │   └── main.py                # FastAPI app
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/                       # Next.js 14 Frontend
│   ├── app/                       # Pages (App Router)
│   │   ├── page.tsx               # Landing
│   │   ├── login/
│   │   ├── register/
│   │   ├── forgot-password/
│   │   ├── dashboard/
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── lib/
│   │   └── api.ts                 # API client
│   ├── Dockerfile
│   ├── package.json
│   └── next.config.js
│
├── infra/                          # Infrastructure
│   └── supabase/
│       └── migrations/            # SQL migrations
│           ├── 001_initial_schema.sql
│           ├── 002_weekly_schedule.sql
│           └── 003_feedback_and_reviews.sql
│
├── docker-compose.yml              # Full stack
├── README.md                       # Project overview
├── AI_MODEL_ANALYSIS.md            # Model comparison & costs
├── AI_PROGRAMMING_GUIDE.md         # AI programming docs
├── WEEKLY_SCHEDULE_GUIDE.md        # Schedule system docs
├── CODE_REVIEW.md                  # Static analysis
└── PROJECT_STATUS.md               # This file
```

---

## 🗄️ Database Schema

**Tables (Supabase PostgreSQL):**

1. `users` - User profiles
2. `workout_templates` - Workout definitions
3. `workout_sessions` - Actual workouts performed
4. `exercise_sets` - Individual sets
5. `recovery_metrics` - Daily HRV, sleep, readiness
6. `biomarker_types` - Reference (16 types)
7. `biomarker_readings` - Lab results
8. `meal_plans` - Nutrition plans
9. `meal_logs` - Food tracking
10. `weekly_schedules` - Training schedules
11. `weekly_meal_plans` - Auto-generated meal plans
12. `session_feedback` - Post-workout feedback
13. `weekly_reviews` - AI-generated reviews
14. `personal_records` - PRs

**Security:** Row-level security (RLS) enabled on all tables

---

## 💰 Cost Analysis

### Per Athlete/Month

| Service | Usage | Cost |
|---------|-------|------|
| **GPT-4o** | 4 weekly programs | $0.40 |
| **GPT-4o mini** | 20 daily adjustments | $0.40 |
| **Claude 3.5 Sonnet** | 4 weekly reviews | $0.60 |
| **Gemini 1.5 Pro** | 1 monthly analysis | $0.05 |
| **TOTAL AI** | | **$1.45** |
| **Supabase** | Database + Auth | Free (up to 500MB) |
| **Hosting** | Coolify self-hosted | $0 |

**Subscription Price:** $29-49/month  
**AI Cost:** $1.45/month  
**Gross Margin:** 97%+ 💰

---

## 🚀 Deployment

### Development

**Backend:**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Access:**
- Backend: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Frontend: http://localhost:3000

### Docker (Full Stack)

```bash
# Create .env (see .env.example)
cp .env.example .env

# Start all services
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Coolify (Production)

1. Create new resource → Docker Compose
2. Connect GitHub repo
3. Set environment variables (from .env.example)
4. Deploy

---

## 🔑 Environment Variables

**Backend (.env):**
```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-key

# AI APIs
OPENAI_API_KEY=sk-your-key
ANTHROPIC_API_KEY=sk-ant-your-key

# App
SECRET_KEY=your-secret-key-change-in-production
FRONTEND_URL=http://localhost:3000
```

**Frontend (.env.local):**
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

---

## 📚 Documentation

| File | Description |
|------|-------------|
| `README.md` | Project overview, setup, features |
| `AI_MODEL_ANALYSIS.md` | Model comparison (GPT-4o, Claude, Gemini) |
| `AI_PROGRAMMING_GUIDE.md` | AI program generation guide |
| `WEEKLY_SCHEDULE_GUIDE.md` | Schedule & meal planning docs |
| `CODE_REVIEW.md` | Static analysis & recommendations |
| `frontend/README.md` | Frontend-specific documentation |
| `IMPLEMENTATION_GUIDE.md` | Implementation details |
| `FRONTEND_GUIDE.md` | Frontend architecture |

**Total Documentation:** ~90KB

---

## ✅ Testing Status

### Backend
- ✅ Unit tests: ~580 tests, ~78% coverage (CI threshold 60%)
- ✅ Integration tests: API endpoints via pytest + httpx
- ⚠️ E2E: Playwright specs exist; authenticated flows partially skipped

### Frontend
- ✅ SSR pages: dashboard, training, schedule, health, nutrition, reviews, profile
- ⚠️ E2E autenticado: expandir cobertura Playwright

**Priority:** Add tests before production (target 60%+ coverage)

---

## 🐛 Known Issues

1. **Backend:**
   - Tests missing (critical)
   - Celery workers not implemented (async tasks)
   - HealthKit/Calendar integrations are stubs
   - OCR for lab reports not implemented

2. **Frontend:**
   - No protected route middleware (manual check in each page)
   - Dashboard subpages not built (workouts, schedule, reviews, profile)
   - No reusable components (code duplication)
   - No loading states between routes
   - localStorage used directly (should be abstracted to hook)
   - No error boundary for runtime errors

3. **General:**
   - Email verification not fully implemented
   - Password reset page not created (token from email)
   - No mobile app (PWA only)

---

## 📈 Roadmap

### Phase 1: MVP Completion (2 weeks)
- [x] AI program generation
- [x] Adaptive training engine
- [x] Weekly review system
- [x] Frontend authentication
- [x] Dashboard UI
- [ ] Unit tests (backend 60%+ coverage)
- [ ] Protected routes middleware
- [ ] Dashboard subpages (workouts, schedule, reviews)

### Phase 2: Integration (1 month)
- [ ] HealthKit integration (iOS)
- [ ] Google Calendar sync
- [ ] OCR for lab reports (GPT-4 Vision)
- [ ] Email verification flow
- [ ] Password reset page
- [ ] Real-time workout tracking

### Phase 3: Enhancement (2 months)
- [ ] Progress charts (Chart.js)
- [ ] Community leaderboards
- [ ] Mobile PWA (manifest + service worker)
- [ ] Dark mode
- [ ] Multi-coach platform
- [ ] Wearable integrations (Whoop, Oura, Garmin)

### Phase 4: Scale (3+ months)
- [ ] Mobile native apps (Swift, Kotlin)
- [ ] Marketplace for custom programs
- [ ] Social features
- [ ] Advanced analytics dashboard
- [ ] Multi-language support

---

## 🎯 Success Metrics

**Target KPIs (3 months):**
- Aderência: >85% (sessions completed vs planned)
- Satisfação: >8/10 (athlete rating)
- Progressão: >3%/month strength (beginners), >1%/month (advanced)
- Injury rate: <5%
- Retenção: >80% (after 12 weeks)

---

## 🏆 Competitive Advantages

1. **AI-Powered Adaptation:** Only system with real-time volume adjustment based on recovery
2. **Closed-Loop Feedback:** Weekly AI reviews create true progressive overload
3. **Methodology Agnostic:** Supports HWPO, Mayhem, CompTrain, Custom
4. **Cost Effective:** $29-49/month vs $100-200 for human coaching
5. **Self-Hosted:** Coolify deployment for complete data control

---

## 👥 Team & Credits

**Built by:** Fernando Karl (Innovation Director, Service IT Security)  
**AI Models:**
- GPT-4o (OpenAI) - Program generation
- Claude 3.5 Sonnet (Anthropic) - Weekly reviews
- Gemini 1.5 Pro (Google) - Monthly analysis

**Inspiration:**
- Mat Fraser (HWPO methodology)
- Rich Froning (Mayhem methodology)
- Ben Bergeron (CompTrain methodology)

---

## 📞 Support

- **GitHub:** https://github.com/yourusername/crossfit-health-os
- **Docs:** http://localhost:8000/docs (local) or https://api.crossfithealthos.com/docs
- **Email:** support@crossfithealthos.com (TODO)
- **Discord:** https://discord.gg/crossfithealthos (TODO)

---

## 📝 License

MIT License - See LICENSE file

---

**Status:** 🚧 MVP Complete - Ready for Alpha Testing  
**Next Steps:** Add tests, deploy to Coolify, onboard first 10 users

**Built with 💪 by athletes, for athletes.**

---

*Last commit: `126e099` - feat: Add complete frontend with authentication and backend auth endpoints*  
*Total commits: 4*  
*Lines of code: ~8,000 (backend) + ~3,000 (frontend) = 11,000+ LOC*  
*Documentation: ~90KB across 9 files*
