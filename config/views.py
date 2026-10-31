from django.http import JsonResponse


def healthz(request):
    """Health check endpoint returning 200 OK."""
    return JsonResponse({"status": "ok"})
