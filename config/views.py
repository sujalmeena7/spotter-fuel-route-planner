from django.http import JsonResponse

from apps.stations.apps import wait_for_warmup


def healthz(request):
    """Health check endpoint returning 200 OK after waiting for background warmup."""
    wait_for_warmup(timeout=15.0)
    return JsonResponse({"status": "ok"})
