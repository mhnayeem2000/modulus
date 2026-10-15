from django.conf import settings
from django.http import FileResponse
from django.views.decorators.http import require_GET


@require_GET
def service_worker(request):
    service_worker_path = settings.BASE_DIR / 'static' / 'service-worker.js'
    response = FileResponse(service_worker_path.open('rb'), content_type='application/javascript')
    response['Cache-Control'] = 'no-cache'
    response['Service-Worker-Allowed'] = '/'
    return response
