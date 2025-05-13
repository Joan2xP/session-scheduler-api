from django.urls import path
from .views import ExhibitorList

urlpatterns = [
    # Example:
    path("", ExhibitorList.as_view(), name="exhibitor-list"),
]
