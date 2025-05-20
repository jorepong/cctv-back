
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings')
django.setup()

from SmartCCTV.settings import start_ssh_tunnel
start_ssh_tunnel()

from analytics.models import Cameras

cams = Cameras.objects.all()
print(cams.count())