from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse, HttpResponseNotFound
import os

def serve_spa(request, path=''):
    """Serve the SPA index.html as a raw file (bypasses Django template engine)."""
    index_path = os.path.join(settings.BASE_DIR, 'frontend', 'index.html')
    if os.path.exists(index_path):
        return FileResponse(open(index_path, 'rb'), content_type='text/html; charset=utf-8')
    return HttpResponseNotFound('Frontend not built.')

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('api/', include('api.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Serve static frontend assets
urlpatterns += static('/static/frontend/', document_root=os.path.join(settings.BASE_DIR, 'frontend'))

# Serve frontend SPA for all other routes (raw file, not Django template)
urlpatterns += [
    re_path(r'^(?!api/)(?!django-admin/)(?!media/)(?!static/).*$', serve_spa),
]
