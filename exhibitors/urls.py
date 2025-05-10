from django.urls import path
from . import views

urlpatterns = [
    # Example:
    path("", views.index, name="index"),
]
