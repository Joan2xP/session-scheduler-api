from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Exhibitor
from .serializers import ExhibitorSerializer


class ExhibitorList(APIView):
    def get(self, request):
        exhibitors = Exhibitor.objects.all()
        serializer = ExhibitorSerializer(exhibitors, many=True)
        return Response(serializer.data)

    def post(self, request):

        return Response({"message": "POST request received"})
