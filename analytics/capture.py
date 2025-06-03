import os
import sys

import django
import json
import subprocess
import time
from pathlib import Path
from django.utils import timezone
from django.conf import settings
from django.utils.timezone import localtime, now as dj_now

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Django 설정 및 초기화
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings.local')
django.setup()

from SmartCCTV.settings.local import start_ssh_tunnel
start_ssh_tunnel()

from analytics.models import Cameras, Snapshots

def get_video_resolution(rtsp_url: str) -> str:
    """RTSP 영상에서 해상도(width x height)를 추출하고 실패 시 기본값 반환"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json",
                rtsp_url
            ],
            capture_output=True, text=True,timeout=10
        )

        # ffprobe 결과 파싱
        info = json.loads(result.stdout)

        if "streams" in info and info["streams"]:
            width = info["streams"][0].get("width")
            height = info["streams"][0].get("height")
            if width and height:
                return f"{width}x{height}"

        print("[⚠️] 해상도 정보가 없거나 불완전합니다.")
    except subprocess.TimeoutExpired:
        print("[⏱️] ffprobe 시간이 초과되었습니다.")
    except json.JSONDecodeError:
        print("[❌] ffprobe JSON 파싱 실패.")
    except Exception as e:
        print(f"[❌] ffprobe 실행 중 알 수 없는 오류: {e}")

    # 실패 시 fallback 해상도
    return "1920x1080"

def capture_snapshot_with_ffmpeg_rtsp(camera_id: int):
    try:
        camera = Cameras.objects.get(pk=camera_id)
    except Cameras.DoesNotExist:
        print(f"[❌] 존재하지 않는 카메라 ID: {camera_id}")
        return

    timestamp = localtime(dj_now())
    timestamp_str = "snap_" + timestamp.strftime('%y%m%d%H%M%S')

    cam_dir = Path(settings.CAPTURE_ROOT) / str(camera.camera_id)
    cam_dir.mkdir(parents=True, exist_ok=True)

    video_path = cam_dir / f"{timestamp_str}.mp4"
    image_path = cam_dir / f"{timestamp_str}.jpg"

    rtsp_url = camera.rtsp_url
    resolution = get_video_resolution(rtsp_url)

    print(f"\n[🎥] RTSP mp4 저장 시작\n→ URL: {rtsp_url}\n→ 저장: {video_path}\n→ 해상도: {resolution}")

    result_video = subprocess.run([
        "ffmpeg", "-rtsp_transport", "tcp",
        "-analyzeduration", "10000000", "-probesize", "5000000",
        "-i", rtsp_url, "-t", "2",  # ✅ 2초로 변경
        "-s", resolution, "-c:v", "libx264",
        "-preset", "ultrafast", str(video_path)
    ], capture_output=True, text=True, timeout=30)

    print("=== [ffmpeg stdout - mp4 저장] ===")
    print(result_video.stdout)

    if not video_path.exists():
        print(f"[❌] mp4 저장 실패: {video_path}")
        return

    result_jpg = subprocess.run([
        "ffmpeg", "-i", str(video_path),
        "-frames:v", "1", str(image_path)
    ], capture_output=True, text=True)

    print("┌─[🔧 ffmpeg stderr - 이미지 추출]")
    print(result_jpg.stderr)
    print("└─[🔧 ffmpeg stdout - 이미지 추출]")

    if result_jpg.returncode != 0 or not image_path.exists():
        print(f"[❌] 이미지 생성 실패: {image_path}")
        return

    # ✅ mp4 파일 삭제
    try:
        video_path.unlink()
        print(f"[🗑️] mp4 삭제 완료: {video_path}")
    except Exception as e:
        print(f"[⚠️] mp4 삭제 실패: {e}")

    try:
        relative_path = image_path.relative_to(settings.CAPTURE_ROOT)
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

def capture_snapshot_with_ffmpeg_hls(camera_id: int):
    try:
        camera = Cameras.objects.get(pk=camera_id)
    except Cameras.DoesNotExist:
        print(f"[❌] 존재하지 않는 카메라 ID: {camera_id}")
        return

    timestamp = localtime(dj_now())
    timestamp_str = "snap_" + timestamp.strftime('%y%m%d%H%M%S')

    cam_dir = Path(settings.CAPTURE_ROOT) / str(camera.camera_id)
    cam_dir.mkdir(parents=True, exist_ok=True)

    image_path = cam_dir / f"{timestamp_str}.jpg"
    hls_url = camera.rtsp_url

    print(f"\n[🌐] HLS 이미지 캡처 시작\n→ URL: {hls_url}\n→ 저장: {image_path}")

    result_jpg = subprocess.run([
        "ffmpeg", "-i", hls_url,
        "-frames:v", "1", "-q:v", "2", str(image_path)
    ], capture_output=True, text=True, timeout=30)

    if result_jpg.returncode != 0 or not image_path.exists():
        print(f"[❌] 이미지 생성 실패: {image_path}")
        return

    relative_path = image_path.relative_to(settings.CAPTURE_ROOT)
    Snapshots.objects.create(
        camera=camera,
        captured_at=timestamp,
        image_path=str(relative_path),
        processing_status_ai='PENDING',
        processing_status_congestion='PENDING'
    )
    print(f"[✅] HLS 스냅샷 저장 완료: {image_path}")


# ✅ 무한 반복: 30초마다 1번씩 실행
if __name__ == "__main__":
    try:
        camera_id = int(input("🎥 캡처할 카메라 ID를 입력하세요: "))
    except ValueError:
        print("[❌] 잘못된 입력입니다. 정수를 입력해주세요.")
        exit(1)

    try:
        camera = Cameras.objects.get(pk=camera_id)
    except Cameras.DoesNotExist:
        print(f"[❌] 존재하지 않는 카메라 ID: {camera_id}")
        exit(1)

    if camera.source_type == "HLS":
        print(f"🌐 [ID {camera_id}] HLS 스트림에서 30초 간격 캡처 시작")
        capture_func = capture_snapshot_with_ffmpeg_hls
    else:
        print(f"🎥 [ID {camera_id}] RTSP 스트림에서 30초 간격 캡처 시작")
        capture_func = capture_snapshot_with_ffmpeg_rtsp

    print("📸 30초 간격으로 스냅샷 캡처 시작합니다. 중지하려면 Ctrl+C를 누르세요.")
    while True:
        try:
            capture_func(camera_id)
        except Exception as e:
            print(f"[❌] 반복 중 오류 발생: {e}")
        time.sleep(30)



