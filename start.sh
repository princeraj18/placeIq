#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  PlaceIQ — startup script
#  Usage:  bash start.sh
#          GEMINI_API_KEY=your_key bash start.sh
#          PORT=9000 bash start.sh
# ─────────────────────────────────────────────────────────────
set -e

PORT=${PORT:-8000}
WORKERS=${WORKERS:-2}

echo ""
echo "  ██████╗ ██╗      █████╗  ██████╗███████╗██╗ ██████╗ "
echo "  ██╔══██╗██║     ██╔══██╗██╔════╝██╔════╝██║██╔═══██╗"
echo "  ██████╔╝██║     ███████║██║     █████╗  ██║██║   ██║"
echo "  ██╔═══╝ ██║     ██╔══██║██║     ██╔══╝  ██║██║▄▄ ██║"
echo "  ██║     ███████╗██║  ██║╚██████╗███████╗██║╚██████╔╝"
echo "  ╚═╝     ╚══════╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝ ╚══▀▀═╝ "
echo ""
echo "  AI Placement Intelligence Platform"
echo "─────────────────────────────────────────────────────────"
echo ""

# ── Load .env if present ──────────────────────────────────────
if [ -f ".env" ]; then
  echo "📄  Loading .env..."
  export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

# ── Check API key ─────────────────────────────────────────────
if [ -z "$GEMINI_API_KEY" ] || [ "$GEMINI_API_KEY" = "your_gemini_api_key_here" ]; then
  echo "⚠️   GEMINI_API_KEY not set — AI features will use smart local fallbacks."
  echo "    To enable full AI: set GEMINI_API_KEY=... in .env"
  echo ""
else
  echo "✅  GEMINI_API_KEY detected — full AI features enabled."
  echo ""
fi

# ── Install dependencies ──────────────────────────────────────
echo "📦  Checking dependencies..."
pip install -q django djangorestframework django-cors-headers gunicorn python-dotenv --break-system-packages 2>/dev/null || true

# ── Run migrations ────────────────────────────────────────────
echo "🗄️   Running database migrations..."
DJANGO_SETTINGS_MODULE=backend.settings python3 manage.py migrate --run-syncdb -v 0 2>/dev/null || \
  python3 manage.py migrate --run-syncdb -v 0

# ── Seed data if needed ───────────────────────────────────────
python3 -c "
import os, sys
os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
sys.path.insert(0, '.')
import django; django.setup()
from api.models import User, Job
from api.auth import create_user
if User.objects.count() == 0:
    create_user('admin', 'admin@placeiq.com', 'admin1234', 'Admin', 'User', 'admin')
    create_user('student', 'student@placeiq.com', 'student123', 'Jane', 'Doe', 'student')
    print('✅  Demo users created (admin@placeiq.com / admin1234, student@placeiq.com / student123)')
if Job.objects.count() == 0:
    admin = User.objects.get(username='admin')
    jobs = [
        ('Software Engineer Intern', 'Google', 'Bangalore, IN', 'Internship', ['Python','Java','DSA','System Design']),
        ('Frontend Developer', 'Flipkart', 'Bengaluru, IN', 'Full-time', ['React','TypeScript','CSS','REST APIs']),
        ('ML Engineer', 'Microsoft', 'Hyderabad, IN', 'Full-time', ['Python','PyTorch','TensorFlow','Statistics']),
        ('Backend Engineer', 'Amazon', 'Remote', 'Full-time', ['Java','Spring Boot','AWS','Databases']),
        ('Data Analyst Intern', 'Zomato', 'Delhi, IN', 'Internship', ['SQL','Python','Excel','Tableau']),
        ('DevOps Engineer', 'Infosys', 'Pune, IN', 'Full-time', ['Docker','Kubernetes','AWS','CI/CD','Linux']),
        ('Product Manager', 'Swiggy', 'Bengaluru, IN', 'Full-time', ['Product Strategy','SQL','Agile','Communication']),
        ('Android Developer', 'Paytm', 'Noida, IN', 'Full-time', ['Kotlin','Android SDK','REST APIs','Git']),
    ]
    for title,co,loc,emp,reqs in jobs:
        Job.objects.create(title=title,company=co,location=loc,employment_type=emp,requirements=reqs,posted_by=admin)
    print(f'✅  {len(jobs)} demo jobs created')
" 2>/dev/null || true

# ── Start server ──────────────────────────────────────────────
echo ""
echo "🚀  Starting PlaceIQ on port $PORT..."
echo ""
echo "  🌐  Open in browser:  http://localhost:$PORT"
echo "  📡  API base:         http://localhost:$PORT/api/"
echo "  👤  Admin login:      admin@placeiq.com   / admin1234"
echo "  🎓  Student login:    student@placeiq.com / student123"
echo ""
echo "─────────────────────────────────────────────────────────"
echo "  Press Ctrl+C to stop"
echo "─────────────────────────────────────────────────────────"
echo ""

exec gunicorn backend.wsgi:application \
  --bind 0.0.0.0:$PORT \
  --workers $WORKERS \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
