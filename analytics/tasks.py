import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings')
django.setup()

from SmartCCTV.settings import start_ssh_tunnel
start_ssh_tunnel()

import subprocess
from pathlib import Path
from django.utils import timezone
from django.conf import settings
from analytics.models import Cameras, Snapshots

def capture_snapshot_with_ffmpeg(camera_id: int):
    try:
        camera = Cameras.objects.get(pk=camera_id)
    except Cameras.DoesNotExist:
        print(f"[❌] 존재하지 않는 카메라 ID: {camera_id}")
        return

    timestamp = timezone.now()
    timestamp_str = timestamp.strftime('%Y%m%d_%H%M%S')

    cam_dir = Path(settings.MEDIA_ROOT) / str(camera.camera_id)
    cam_dir.mkdir(parents=True, exist_ok=True)

    video_path = cam_dir / f"{timestamp_str}.mp4"
    image_path = cam_dir / f"{timestamp_str}.jpg"

    rtsp_url = camera.rtsp_url
    print(f"\n[🎥] RTSP mp4 저장 시작\n→ URL: {rtsp_url}\n→ 저장: {video_path}")

    result_video = subprocess.run([
        "ffmpeg", "-rtsp_transport", "tcp",
        "-analyzeduration", "10000000",
        "-probesize", "5000000",
        "-i", rtsp_url,
        "-t", "3",
        "-s", "1920x1080",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        str(video_path)
    ], capture_output=True, text=True, timeout=30)

    print("=== [ffmpeg stderr - mp4 저장] ===")
    print(result_video.stderr)
    print("=== [ffmpeg stdout - mp4 저장] ===")
    print(result_video.stdout)

    if not video_path.exists():
        print(f"[❌] mp4 저장 실패: {video_path}")
        return

    result_jpg = subprocess.run([
        "ffmpeg", "-i", str(video_path),
        "-frames:v", "1",
        str(image_path)
    ], capture_output=True, text=True)

    print("┌─[🔧 ffmpeg stderr - 이미지 추출]")
    print(result_jpg.stderr)
    print("└─[🔧 ffmpeg stdout - 이미지 추출]")

    if result_jpg.returncode != 0 or not image_path.exists():
        print(f"[❌] 이미지 생성 실패: {image_path}")
        return

    try:
        relative_path = image_path.relative_to(settings.MEDIA_ROOT)
    except ValueError:
        relative_path = image_path.name

    Snapshots.objects.create(
        camera=camera,
        captured_at=timestamp,
        image_path=str(relative_path),
        processing_status_ai='PENDING',
        processing_status_congestion='PENDING'
    )
    print(f"[✅] 스냅샷 저장 완료: {image_path}")
