# LegacyLink Africa

A Django REST API for connecting alumni from African schools.

## Features

- User registration and JWT authentication
- School search and onboarding
- Cohort matching (same school + graduation year)
- Connection requests (send, accept, decline)
- Django admin interface

## Setup

1. Create virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run migrations:
   ```bash
   python manage.py migrate
   python manage.py seed_schools
   ```

4. Create superuser:
   ```bash
   python manage.py createsuperuser
   ```

5. Run server:
   ```bash
   python manage.py runserver
   ```

## API Endpoints

- `POST /api/auth/register/` - Register new user
- `POST /api/auth/login/` - Login with JWT
- `GET /api/alumni/schools/?q=` - Search schools
- `PATCH /api/alumni/onboarding/` - Complete onboarding
- `GET /api/alumni/cohort/` - Get classmates
- `POST /api/connections/send/{user_id}/` - Send connection request
- `PATCH /api/connections/{id}/respond/` - Accept/decline request
- `GET /api/connections/?tab=pending` - List connections

## Admin

Visit `/admin/` to manage users, schools, and connections.