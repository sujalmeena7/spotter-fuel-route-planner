from django.shortcuts import render


def map_view(request):
    """Serve the interactive MapLibre GL JS fuel-optimized route planner UI."""
    return render(request, "web/map.html")
