# Session Scheduler API

Constraint-based session scheduling API powered by Google OR-Tools. Automatically assigns participants to recurring sessions while respecting availability, pairing, exclusion, and capacity constraints — then optimizes for fairness.

## Overview

Scheduling people into recurring sessions (weekly shifts, community events, volunteer slots) is a hard combinatorial problem. This API solves it using **constraint programming** (CP-SAT solver from Google OR-Tools). Users define sessions, participants, and constraints through a REST API; the solver produces an optimized monthly schedule that satisfies all requirements.

Each user owns isolated data through JWT-authenticated multi-tenancy, and can configure solver behavior (constraint toggles, objective weights, group sizes) per session group.

## Tech Stack

- **Backend:** Django, Django REST Framework
- **Auth:** SimpleJWT (Bearer tokens, 7-day access / 30-day refresh)
- **Scheduling Engine:** Google OR-Tools CP-SAT solver
- **Database:** PostgreSQL (SQLite for local dev)
- **Static Files:** WhiteNoise with Brotli compression
- **Deployment:** VPS (Gunicorn + Uvicorn ASGI worker)

## Features

### Scheduling Engine

The core solver supports 12 constraints and 4 optimization objectives, all configurable per session group:

**Constraints** (toggle on/off):

| Constraint | Description |
|---|---|
| `availability` | Only schedule participants for sessions they're available for |
| `max_weekly` | Cap sessions per participant per ISO week |
| `max_monthly` | Cap sessions per participant per month |
| `minimum_monthly` | Floor on sessions per participant per month |
| `group_size` | Fixed group size (configurable separately for weekdays/weekends) |
| `partner` | Paired participants always attend together |
| `exclusion` | Listed participants are never co-scheduled |
| `only_session_occurrences` | Restrict participant to specific (session, date) pairs |
| `exclude_session_occurrences` | Block participant from specific (session, date) pairs |
| `min_sessions_together` | Two participants must share at least N sessions of a type |
| `enforced_sessions` | Force participant onto specific sessions |
| `one_session_per_day` | Max one session per participant per day |

**Optimization objectives** (weighted):

| Objective | Description |
|---|---|
| `diversity` | Minimize the maximum times any pair is co-scheduled |
| `session_separation` | Maximize the gap between a participant's sessions |
| `consecutive_days_penalty` | Penalize back-to-back day assignments |
| `anchor` | Ensure at least one anchor participant per session |

### API

- User-scoped data isolation — users only see their own session groups, sessions, and participants
- Bidirectional camelCase/snake_case conversion for JavaScript-friendly payloads
- Signal-based cascade cleanup — deleting a session automatically removes references from all participant records
- Demo data management command for quick setup (`python manage.py load_demo_data`)

## API Endpoints

All endpoints (except auth) require `Authorization: Bearer <token>`.

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/token/` | Obtain JWT token pair |
| POST | `/api/token/refresh/` | Refresh access token |
| GET | `/api/me/` | Get current user info |

### Schedule

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/expositors/` | List all generated schedules |
| GET/PUT | `/api/expositors/<year>/<month>/<group_id>/` | Get or update a schedule |
| POST | `/api/expositors/generate` | Run the solver to generate a schedule |

### Session Groups & Sessions

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/api/expositors/sessions/groups/` | List or create session groups |
| GET/PUT/DELETE | `/api/expositors/sessions/groups/<id>/` | Retrieve, update, or delete a group |
| POST | `/api/expositors/sessions/groups/<id>/sessions/` | Create a session in a group |
| PUT/DELETE | `/api/expositors/sessions/groups/<id>/sessions/<sid>/` | Update or delete a session |

### Participants & Traits

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/api/expositors/participants/` | List or create participants (`?sessionGroupId=`) |
| GET/PUT/DELETE | `/api/expositors/participants/<id>/` | Retrieve, update, or delete a participant |
| GET/POST | `/api/expositors/traits/` | List or create participant traits (`?sessionGroupId=`) |
| GET/PUT/DELETE | `/api/expositors/traits/<id>/` | Retrieve, update, or delete a trait |

## Getting Started

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
git clone https://github.com/your-username/session-scheduler-api.git
cd session-scheduler-api
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Database Setup

```bash
python manage.py migrate
python manage.py load_demo_data   # creates a "demo" user with sample data
```

### Run

```bash
python manage.py runserver
```

The API is available at `http://localhost:8000/api/`. Obtain a token via `/api/token/` with the demo credentials or create a superuser with `python manage.py createsuperuser`.

## Project Structure

```
├── tasks_backend/          # Django project config (settings, root URLs, ASGI entry)
│   ├── settings.py         # DRF/JWT/CORS/WhiteNoise config
│   ├── urls.py             # Root URL routing
│   └── views.py            # /api/me/ endpoint
├── exhibitors/             # Core app
│   ├── models.py           # SessionGroup, Session, Participant, ParticipantTrait, Exhibitor
│   ├── serializers.py      # DRF serializers with camelCase conversion
│   ├── views.py            # API views and viewsets
│   ├── urls.py             # App URL routing
│   ├── admin.py            # Admin registration
│   ├── services/
│   │   └── SessionScheduler.py   # OR-Tools constraint solver (1200+ lines)
│   ├── management/commands/
│   │   └── load_demo_data.py     # Demo data seeder
│   │   (signals in models.py — pre-delete cascade cleanup)
└── requirements.txt
```
