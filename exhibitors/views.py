from django.http import JsonResponse

# Create your views here.


def index(request):
    mock_data = [
        {"id": 1, "month": 1, "year": 2023},
        {"id": 2, "month": 2, "year": 2023},
        {"id": 3, "month": 3, "year": 2023},
    ]
    return JsonResponse(mock_data, safe=False)
