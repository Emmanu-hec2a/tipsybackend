# tipsytheoryy

# Tipsy Backend API 🚀

[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=white)](https://djangoproject.com)
[![Django REST Framework](https://img.shields.io/badge/DRF-A30000?style=for-the-badge&logo=django&logoColor=white)](https://www.django-rest-framework.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Celery](https://img.shields.io/badge/Celery-37B24D?style=for-the-badge&logo=celery&logoColor=white)](https://docs.celeryq.dev)

A robust RESTful API backend powering the Tipsy e-commerce ecosystem. Built with Django REST Framework, it manages store operations, customer orders, delivery logistics, automated M-Pesa payment gateways, and asynchronous background workflows.

---

## 🛠️ Tech Stack & Key Features

* **Framework & Architecture:** Built on Django and Django REST Framework with a modular application structure (`urbanfoods`).
* **Payments Integration:** Hardened M-Pesa API integration with callback URL processing for real-time mobile payment verification.
* **Background Tasks:** Asynchronous task processing using Celery & Celery Beat (`procfile`) for scheduled jobs and queued execution.
* **Database & Static Files:** PostgreSQL schema management and static media serving configuration (`staticfiles`).
* **Deployment Ready:** Pre-configured with `nixpacks.toml` and Procfile settings for seamless deployment on platforms like Railway or Render.

---

## 📂 Project Structure

```text
tipsybackend/
├── config/             # Django root configuration & settings
├── urbanfoods/         # Core business logic, APIs, and models
├── staticfiles/        # Compiled static assets
├── templates/          # HTML templates & SEO rich content
├── manage.py           # Django management utility
├── procfile            # Process definitions for Web, Celery Worker, & Celery Beat
├── nixpacks.toml       # Environment & build setup
└── requirements.txt    # Python dependency management
```
## 🚀 Local Development Setup

### Prerequisites
* Python 3.10+
* PostgreSQL Database
* Redis (for Celery background tasks)

### Installation Guide

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/Emmanu-hec2a/tipsybackend.git](https://github.com/Emmanu-hec2a/tipsybackend.git)
   cd tipsybackend
   ```

## Create and activate a virtual environment:
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

Bash
pip install -r requirements.txt

## Environment Configuration:
Create a .env file in the project root directory:

```SECRET_KEY=your_django_secret_key
DEBUG=True
DATABASE_URL=postgres://user:password@localhost:5432/tipsy_db
MPESA_CONSUMER_KEY=your_mpesa_key
MPESA_CONSUMER_SECRET=your_mpesa_secret
```
## Run Migrations & Start Local Server:

Bash
python manage.py migrate
python manage.py runserver
The REST API endpoints will be accessible locally at http://127.0.0.1:8000/.

## ⚙️ Background Task Workers
To process asynchronous queues (such as order status updates and notifications), run the Celery worker and scheduler in separate terminal sessions:

Bash
# Start Celery Worker
celery -A config worker --loglevel=info

# Start Celery Beat Scheduler
celery -A config beat --loglevel=info
