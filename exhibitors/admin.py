from django.contrib import admin

# Register your models here.
from .models import Exhibitor, Participant

admin.register(Exhibitor)
admin.register(Participant)
