
import os
import django

from SmartCCTV.settings import start_ssh_tunnel

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings')
django.setup()

start_ssh_tunnel()

from analytics.models import Cameras

# print(Cameras.objects.first())

cams = Cameras.objects.all()
print(cams.count())
# print(cams.first().camera_id)