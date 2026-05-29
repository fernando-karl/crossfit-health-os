# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CrossFit Health OS** is an elite performance optimization platform that integrates biometric data, adaptive training algorithms, and nutritional intelligence. The system uses AI-powered programming (GPT-4, Claude 3.5) to create personalized training plans and weekly performance reviews based on recovery metrics.

**Core Value Proposition:** Closed-loop feedback system where biometric data (HRV, sleep) → Adaptive training volume → Recovery tracking → AI-powered weekly reviews → Next cycle adjustments.

## Architecture

### Technology Stack

**Backend:**
- FastAPI (Python 3.11) - async API framework
- Supabase (PostgreSQL) - database with Row-Level Security
- Redis - caching and Celery task queue
- Celery - async job processing (OCR, AI generation)

**Frontend:**
- Next.js 14+ (App Router) - React framework with client components
- TypeScript - type-safe components
- Tailwind CSS - utility-first styling

**AI/ML:**
- OpenAI GPT-4 Turbo - workout programming generation
- Claude 3.5 Sonnet - weekly performance reviews (preferred)
- GPT-4o Vision - lab report OCR extraction

**Integrations:**
- Apple HealthKit - HRV, sleep, heart rate
- Google Calendar OAuth2 - workout scheduling
- Supabase Auth - JWT-based authentication

### System Architecture

```
User Device (iOS/Web)
    ↓
Next.js Frontend (port 3000)
    ↓ JWT Auth
FastAPI Backend (port 8000)
    ↓
Supabase PostgreSQL (port 5432)
    ↓
Redis (port 6379) ← Celery Workers
```

## Development Commands

### Backend

**Start backend server:**
```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Run tests:**
```bash
cd backend
pytest tests/ -v --cov=app --cov-report=term-missing
```

**Run specific test file:**
```bash
cd backend
pytest tests/test_training.py -v
```

**Run tests with coverage threshold:**
```bash
cd backend
pytest tests/ -v --cov=app --cov-fail-under=60
```

**Lint code:**
```bash
cd backend
ruff check app/ --select E,F,W --ignore E501
```

**Format code:**
```bash
cd backend
black app/
```

### Docker

**Start all services (local development):**
```bash
docker-compose up -d
```

**Backend available at:** http://localhost:8000
**API docs (Swagger):** http://localhost:8000/docs
**ReDoc:** http://localhost:8000/redoc

**View logs:**
```bash
docker-compose logs -f backend
docker-compose logs -f celery-worker
```

**Stop services:**
```bash
docker-compose down
```

**Reset database (local):**
```bash
docker-compose down -v  # Removes volumes
docker-compose up -d
```

### Database Migrations

**Note:** Currently using Supabase migrations (not Alembic).

**Create migration:**
```bash
supabase migration new <migration_name>
```

**Apply migrations:**
```bash
supabase db push
```

**Reset local database:**
```bash
supabase db reset
```

### Frontend

**Note:** Frontend commands not yet in repository. Typical Next.js setup would be:

```bash
cd frontend
npm install
npm run dev  # Start dev server on port 3000
npm run build
npm test
```

## Core System Components

### 1. Adaptive Training Engine

**Location:** `backend/app/core/engine/adaptive.py`

**Purpose:** Generates workouts dynamically based on recovery state.

**Key Function:** `AdaptiveTrainingEngine.generate_workout(user_id, date)`

**Algorithm:**
1. Fetch recovery metrics (HRV, sleep, stress, soreness) from `recovery_metrics` table
2. Calculate HRV baseline (30-day rolling average) and HRV ratio
   - `hrv_ratio = current_hrv_ms / baseline_hrv_ms`
   - New users (<5 days data) default to 50ms baseline
3. Calculate readiness score (0-100):
   - All metrics normalized to 0-1 scale first
   - HRV ratio vs baseline: 40% (normalized 0.5-1.5 → 0-1)
   - Sleep quality (1-10 scale): 30%
   - Stress (1-10 scale, inverted): 20%
   - Soreness (1-10 scale, inverted): 10%
   - Formula: `(hrv_norm * 0.4 + sleep_norm * 0.3 + stress_norm * 0.2 + soreness_norm * 0.1) * 100`
4. Determine volume multiplier:
   - `>= 80`: 1.1x (push for PRs)
   - `60-79`: 1.0x (maintain)
   - `40-59`: 0.8x (reduce volume)
   - `< 40`: 0.5x (active recovery only)
5. Select base workout template from methodology (HWPO/Mayhem/CompTrain)
6. Adjust movement volume/intensity (uses round() for fair rounding)
7. Return adaptive workout with reasoning

**Database Tables:**
- `recovery_metrics` - daily HRV, sleep, stress, readiness
- `users` - profile and preferences
- `workout_templates` - base workout library

### 2. AI Programming Engine

**Location:** `backend/app/core/engine/ai_programmer.py`

**Purpose:** Generates 8-week progressive training programs using GPT-4 Turbo.

**Key Function:** `AITrainingProgrammer.generate_weekly_program()`

**Features:**
- Respects periodization (Volume → Deload → Intensity → Test Week)
- Progressive overload based on previous week data
- Weakness-focused programming
- Multiple scaling options (RX, Scaled, Beginner)
- JSON structured output with fallback to rule-based templates

**API Model:** OpenAI GPT-4 Turbo with JSON mode

### 3. Weekly Review Engine

**Location:** `backend/app/core/engine/weekly_reviewer.py`

**Purpose:** AI-powered performance analysis with actionable recommendations.

**Key Function:** `WeeklyReviewEngine.generate_weekly_review(user_id, week_start, week_end)`

**AI Model Priority:**
1. Claude 3.5 Sonnet (primary) - best for nuanced analysis
2. GPT-4 (fallback)
3. Rule-based logic (if no API keys)

**Analysis Components:**
- Session completion & adherence rates
- RPE (Rate of Perceived Exertion) trends
- Recovery status assessment
- Volume/intensity appropriateness
- Movement-specific progression detection
- Next week adjustments (volume %, intensity change, focus movements)

**Database Tables:**
- `workout_sessions` - planned vs completed
- `recovery_metrics` - HRV, sleep trends
- `session_feedback` - RPE, difficulty, technique quality
- `weekly_reviews` - stored reviews with AI model used

### 4. Integration Layer

#### Google Calendar Sync
**Location:** `backend/app/core/integrations/calendar.py`

**OAuth Flow:**
1. Frontend requests authorization URL
2. User authorizes on Google
3. Backend exchanges code for refresh token
4. Token stored in `users.google_calendar_refresh_token`
5. Create events with refresh token

**Functions:**
- `get_oauth_url()` - generate auth URL
- `exchange_code()` - get refresh token
- `refresh_access_token()` - renew access
- `create_calendar_event()` - insert workout/meal
- `sync_calendar_events()` - batch create week's events

**Timezone Note:** Hardcoded to "America/Sao_Paulo" - should be user-configurable.

#### Lab Report OCR
**Location:** `backend/app/core/integrations/ocr.py`

**Pipeline:**
```
PDF/Image → PDF to images → Base64 encode → GPT-4o Vision → JSON biomarkers
```

**Extracted Data:**
- Biomarker name, value, unit
- Reference range (min/max)
- Status (normal/low/high)
- Category (hematology, metabolic, lipid, thyroid, etc.)

**Supported Languages:** English, Portuguese

**Cost:** ~$0.05-0.15 per report

#### Apple HealthKit
**Location:** `backend/app/core/integrations/healthkit.py`

**Data Types:**
- HRV (ms), Resting HR (bpm)
- Sleep duration and quality
- Workout completion data

**Status:** Data collection active, but metric processing not yet implemented.

## API Endpoints

### Training
```
GET    /api/v1/training/workouts/today      # Today's adaptive workout
POST   /api/v1/training/generate            # Generate adaptive workout
POST   /api/v1/training/sessions            # Start session
PATCH  /api/v1/training/sessions/{id}       # Complete session
GET    /api/v1/training/sessions            # List sessions (date range)
POST   /api/v1/training/prs                 # Record personal record
GET    /api/v1/training/prs                 # List PRs
GET    /api/v1/training/templates           # List public templates
```

### Schedule
```
POST   /api/v1/schedule/weekly              # Create weekly schedule
GET    /api/v1/schedule/weekly/active       # Get active schedule
POST   /api/v1/schedule/weekly/generate-ai  # Generate AI program
POST   /api/v1/schedule/meals               # Create meal plan
GET    /api/v1/schedule/meals/active        # Get active meal plan
```

### Health
```
POST   /api/v1/health/recovery              # Log recovery metrics
GET    /api/v1/health/recovery/latest       # Get today's recovery
GET    /api/v1/health/recovery              # Get recovery (date range)
POST   /api/v1/health/biomarkers/upload     # Upload lab report (OCR)
GET    /api/v1/health/biomarkers            # List biomarker readings
```

### Review
```
POST   /api/v1/review/feedback              # Submit session feedback
POST   /api/v1/review/generate              # Generate weekly review
GET    /api/v1/review/                      # List reviews
```

### Integrations
```
POST   /api/v1/integrations/healthkit/sync           # Sync HealthKit data
GET    /api/v1/integrations/calendar/oauth/url       # Get Google OAuth URL
GET    /api/v1/integrations/calendar/oauth/callback  # OAuth callback
POST   /api/v1/integrations/calendar/sync            # Sync to calendar
```

### Users & Auth
```
GET    /api/v1/users/me                     # Current user profile
PATCH  /api/v1/users/me                     # Update profile
GET    /api/v1/users/stats                  # User statistics
POST   /api/v1/auth/login                   # Login (Supabase Auth)
POST   /api/v1/auth/register                # Register
```

## Data Models

### Key Enums

**WorkoutType:** `strength`, `metcon`, `skill`, `conditioning`, `mixed`

**Methodology:** `hwpo`, `mayhem`, `comptrain`, `custom`

**RecoveryStatus:** `optimal`, `adequate`, `compromised`

**VolumeAssessment:** `too_low`, `appropriate`, `too_high`

**IntensityChange:** `decrease`, `maintain`, `increase`

### Training Domain

**Movement:**
```python
movement: str           # "back squat", "pull-up"
sets: int
reps: str               # "5" or "8-10" or "AMRAP"
weight_kg: Optional[float]
intensity: str          # "heavy", "moderate", "light"
rest: str               # "2:00", "as needed"
notes: Optional[str]
```

**WorkoutTemplate:**
```python
id: UUID
name: str               # "Heavy Back Squat + Annie"
methodology: Methodology
workout_type: WorkoutType
difficulty_level: int   # 1-5
movements: List[Movement]
target_stimulus: str    # "Heavy strength + short metcon"
tags: List[str]         # ["strength", "gymnastics"]
```

**WorkoutSession:**
```python
id: UUID
user_id: UUID
template_id: UUID
started_at: datetime
completed_at: Optional[datetime]
score: Optional[str]    # "185kg" or "7:23"
rpe_score: int          # 1-10 Rate of Perceived Exertion
heart_rate_avg: Optional[int]
```

### Health Domain

**RecoveryMetric:**
```python
date: date
sleep_duration_hours: float
sleep_quality_score: int        # 1-100
hrv_rmssd_ms: int               # Heart Rate Variability
resting_heart_rate_bpm: int
stress_level: int               # 1-10
muscle_soreness: int            # 1-10
energy_level: int               # 1-10
readiness_score: float          # Calculated 0-100
```

**BiomarkerReading:**
```python
biomarker_type_id: UUID
test_date: date
value: float
unit: str               # "g/dL", "mg/dL", "ng/mL"
lab_name: str
status: str             # "normal", "low", "high"
pdf_url: Optional[str]
```

### Review Domain

**WeeklyReview:**
```python
user_id: UUID
week_number: int
week_start_date: date
summary: str
strengths: List[PerformanceHighlight]
weaknesses: List[PerformanceChallenge]
recovery_status: RecoveryStatus
volume_assessment: VolumeAssessment
next_week_adjustments: NextWeekAdjustments
coach_message: str
ai_model_used: str      # "claude-3-5-sonnet" or "gpt-4"
```

**NextWeekAdjustments:**
```python
volume_change_pct: int          # -20 to +20
intensity_change: IntensityChange
focus_movements: List[str]      # ["snatch", "handstand_walk"]
add_skill_work_minutes: int
add_mobility_work: bool
```

## Database Architecture

**Supabase Client:** `backend/app/db/supabase.py`

```python
from supabase import create_client
supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
```

**Query Pattern:**
```python
response = supabase_client.table("table_name").select("*").eq("id", id).execute()
data = handle_supabase_response(response, "Error message")
```

**Error Handling:** Use `handle_supabase_response()` and `handle_supabase_single()` from `db/helpers.py`

### Key Tables

- `users` - profiles, preferences, integration tokens
- `workout_templates` - base workout library
- `workout_sessions` - completed/scheduled workouts
- `recovery_metrics` - daily HRV, sleep, stress, readiness
- `personal_records` - movement PRs with dates
- `weekly_schedules` - training schedules
- `weekly_reviews` - AI-generated reviews
- `session_feedback` - post-workout ratings (RPE, difficulty)
- `healthkit_data` - raw Apple HealthKit dumps
- `biomarker_readings` - lab test results
- `meal_plans` - nutrition schedules

## Authentication

**Method:** JWT + Supabase Auth

**Protected Endpoint Pattern:**
```python
from fastapi import Depends
from app.core.auth import get_current_user

@router.get("/protected")
async def protected_route(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    # ... route logic
```

**JWT Flow:**
1. User logs in via `/api/v1/auth/login`
2. Supabase returns JWT access token
3. Frontend stores token in localStorage
4. All requests include `Authorization: Bearer <token>` header
5. Backend validates with `auth.get_user(token)`
6. User profile fetched from `users` table by `auth_user_id`

**Error Cases:**
- Invalid/expired token → 401 Unauthorized
- User profile not found → 404 Not Found

## Frontend Architecture

**Location:** `frontend/app/dashboard/`

**Pages:**
- `page.tsx` - Main dashboard (stats + navigation hub)
- `workouts/page.tsx` - View and track sessions
- `schedule/page.tsx` - Create/edit weekly schedule
- `recovery/page.tsx` - Log HRV, sleep, stress metrics
- `reviews/page.tsx` - View AI-generated weekly reviews

**State Management:** React hooks (useState, useEffect) - no global state library

**API Client Pattern:**
```typescript
import api from '@/lib/api';  // Axios instance with auth interceptor

const response = await api.get('/api/v1/training/sessions', {
  params: { start_date, end_date }
});
```

**Authentication:**
- JWT token stored in localStorage
- Token expiration checked via JWT payload parsing
- 401 responses trigger redirect to `/login`

**Styling:** Tailwind CSS utility classes

## Training Methodologies

### HWPO (Hard Work Pays Off - Mat Fraser)

**Weekly Structure:**
- Monday: Heavy strength + short intense metcon
- Tuesday: Gymnastics skill development
- Wednesday: Active recovery or moderate volume
- Thursday: Threshold training + accessory work
- Friday: Competition simulation WOD
- Saturday: Long chipper or partner WOD
- Sunday: Rest or Zone 2 cardio

**Philosophy:** High intensity, competition-focused, CNS management

### Mayhem (Rich Froning)

**Focus:** High volume, competition prep, work capacity

### CompTrain (Ben Bergeron)

**Focus:** Balanced, sustainable, long-term development

### Custom

User-defined programming with AI assistance.

## Environment Variables

**Required:**
```env
# Application
SECRET_KEY=your-secret-key
ENVIRONMENT=development|production

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-key

# Redis
REDIS_URL=redis://redis:6379/0

# AI (at least one required for full functionality)
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key

# Google Calendar (optional)
GOOGLE_CALENDAR_CLIENT_ID=your-client-id
GOOGLE_CALENDAR_CLIENT_SECRET=your-client-secret

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:8000
```

**Optional:**
```env
DATABASE_URL=postgresql://...  # Fallback for local dev
APPLE_TEAM_ID=your-team-id
TODOIST_API_TOKEN=your-token
```

## CI/CD Pipeline

**GitHub Actions:** `.github/workflows/ci.yml`

**On PR/Push to main:**
1. **Test Job:**
   - Install Python 3.11 dependencies
   - Run pytest with coverage
   - Require 60% coverage minimum

2. **Lint Job:**
   - Run ruff linter
   - Check code style (E, F, W errors, ignore E501 line length)

**Test Environment Variables:** Mock keys provided in CI workflow.

## Known Implementation Gaps

1. **Celery Task Queue** - Configured but no Celery tasks implemented. Weekly review cron runs via `POST /api/v1/internal/cron/weekly-reviews` (shared-secret auth) — wire from Coolify cron / external scheduler.
2. **Google Calendar Timezone** - Hardcoded to "America/Sao_Paulo" (should be user setting)
3. **Redis Caching** - Configured but not utilized
4. **Frontend Package Management** - No package.json in repository root
5. **Supabase Real-time** - WebSocket subscriptions not used

## Development Patterns

### Adding a New API Endpoint

1. Add endpoint to router in `backend/app/api/v1/<domain>.py`
2. Add Pydantic models in `backend/app/models/<domain>.py` if needed
3. Add database queries using Supabase client
4. Add tests in `backend/tests/test_<domain>.py`
5. Update `main.py` to include router (if new domain)

### Modifying Readiness Calculation

1. Edit `AdaptiveTrainingEngine._calculate_readiness_score()` in `backend/app/core/engine/adaptive.py`
2. Update weight percentages in formula
3. Test with sample recovery_metrics data
4. Update documentation in this file

### Adding AI Model Options

1. Update `__init__()` in `AITrainingProgrammer` or `WeeklyReviewEngine`
2. Add API client initialization with fallback chain
3. Add generation method (e.g., `_generate_review_anthropic()`)
4. Update system prompts as needed

### Adding a New Integration

1. Create module in `backend/app/core/integrations/<integration>.py`
2. Implement OAuth flow if needed
3. Add API endpoints in `backend/app/api/v1/integrations.py`
4. Add models if needed
5. Store tokens/credentials in `users` table or new table
6. Update environment variables in `.env.example`

## Performance Considerations

**Typical Response Times:**
- Adaptive workout generation: ~500ms (2 DB queries + calculation)
- AI program generation: 15-45s (GPT-4 Turbo API call)
- Weekly review generation: 10-30s (Claude/GPT-4 API call)
- Lab report OCR: 3-8s per page (GPT-4o Vision API)
- Google Calendar sync: ~1s per event

**Optimization Opportunities:**
- Implement Redis caching for workout templates
- Background jobs (Celery) for long-running AI operations
- Response streaming for large datasets
- Database query optimization with indexes

## Testing

**Backend Test Structure:**
- `tests/conftest.py` - fixtures and test setup
- `tests/test_training.py` - training endpoints
- `tests/test_health.py` - health endpoints
- `tests/test_schedule.py` - schedule endpoints
- `tests/test_review.py` - review endpoints
- `tests/test_auth.py` - authentication
- `tests/test_models.py` - Pydantic model validation

**Run Tests:**
```bash
cd backend
pytest tests/ -v --cov=app
```

**Frontend Tests:** Not yet implemented.

## Deployment

**Platform:** Coolify (Docker orchestration)

**Services:**
- `backend` - FastAPI app (port 8000)
- `redis` - Cache and Celery broker (port 6379)
- `celery-worker` - Background task processor
- `celery-beat` - Scheduled tasks
- `supabase-db` - PostgreSQL (local dev only, port 5432)
- `pgadmin` - Database management (optional, port 5050)

**Docker Compose:**
```bash
docker-compose up -d  # Start all services
docker-compose logs -f backend  # View logs
docker-compose down  # Stop services
```

**Health Check:**
```bash
curl http://localhost:8000/health
```

**API Documentation:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
