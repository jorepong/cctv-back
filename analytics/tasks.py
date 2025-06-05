# import os
# import django
#
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings')
# django.setup()
#
# from SmartCCTV.settings import start_ssh_tunnel
# start_ssh_tunnel()
#
# import subprocess
# from pathlib import Path
# from django.utils import timezone
# from django.conf import settings
# from analytics.models import Cameras, Snapshots
#
# def capture_snapshot_with_ffmpeg(camera_id: int):
#     try:
#         camera = Cameras.objects.get(pk=camera_id)
#     except Cameras.DoesNotExist:
#         print(f"[❌] 존재하지 않는 카메라 ID: {camera_id}")
#         return
#
#     timestamp = timezone.now()
#     timestamp_str = timestamp.strftime('%Y%m%d_%H%M%S')
#
#     cam_dir = Path(settings.MEDIA_ROOT) / str(camera.camera_id)
#     cam_dir.mkdir(parents=True, exist_ok=True)
#
#     video_path = cam_dir / f"{timestamp_str}.mp4"
#     image_path = cam_dir / f"{timestamp_str}.jpg"
#
#     rtsp_url = camera.rtsp_url
#     print(f"\n[🎥] RTSP mp4 저장 시작\n→ URL: {rtsp_url}\n→ 저장: {video_path}")
#
#     result_video = subprocess.run([
#         "ffmpeg", "-rtsp_transport", "tcp",
#         "-analyzeduration", "10000000",
#         "-probesize", "5000000",
#         "-i", rtsp_url,
#         "-t", "3",
#         "-s", "1920x1080",
#         "-c:v", "libx264",
#         "-preset", "ultrafast",
#         str(video_path)
#     ], capture_output=True, text=True, timeout=30)
#
#     print("=== [ffmpeg stderr - mp4 저장] ===")
#     print(result_video.stderr)
#
#     if not video_path.exists():
#         print(f"[❌] mp4 저장 실패: {video_path}")
#         return
#
#     result_jpg = subprocess.run([
#         "ffmpeg", "-i", str(video_path),
#         "-frames:v", "1",
#         str(image_path)
#     ], capture_output=True, text=True)
#
#     print("┌─[🔧 ffmpeg stderr - 이미지 추출]")
#     print(result_jpg.stderr)
#     print("└─[🔧 ffmpeg stdout - 이미지 추출]")
#
#     if result_jpg.returncode != 0 or not image_path.exists():
#         print(f"[❌] 이미지 생성 실패: {image_path}")
#         return
#
#     try:
#         relative_path = image_path.relative_to(settings.MEDIA_ROOT)
#     except ValueError:
#         relative_path = image_path.name
#
#     Snapshots.objects.create(
#         camera=camera,
#         captured_at=timestamp,
#         image_path=str(relative_path),
#         processing_status_ai='PENDING',
#         processing_status_congestion='PENDING'
#     )
#     print(f"[✅] 스냅샷 저장 완료: {image_path}")

from analytics.services import calculate_and_save_congestion_event


@shared_task(name="calculate_congestion_for_snapshot")
def calculate_congestion_for_snapshot_task(snapshot_id: int):
    """
    주어진 스냅샷에 대한 혼잡도를 계산하고 결과를 저장하는 Celery 작업입니다.
    실제 계산 로직은 analytics.services.calculate_and_save_congestion_event 함수를 호출합니다.
    """
    try:
        # snapshot_id 유효성 검사 등 추가 가능
        if not isinstance(snapshot_id, int):
            print(f"[Congestion Task] 유효하지 않은 snapshot_id 타입: {snapshot_id}")
            return

        print(f"[Congestion Task] Snapshot ID {snapshot_id}에 대한 혼잡도 분석 시작...")
        result_event = calculate_and_save_congestion_event(snapshot_id)

        if result_event:
            print(f"[Congestion Task] Snapshot ID {snapshot_id}의 혼잡도 분석 성공. Event ID: {result_event.event_id}, Level: {result_event.congestion_level}")
        # else:
            # calculate_and_save_congestion_event 내부에서 이미 로그를 남기므로 여기서는 추가 로그 불필요할 수 있음
            # print(f"[Congestion Task] Snapshot ID {snapshot_id}의 혼잡도 분석 중 문제 발생 또는 저장 조건 미충족.")

    except Exception as e:
        # 예상치 못한 오류 발생 시 로깅 및 처리
        print(f"[Congestion Task] Snapshot ID {snapshot_id} 처리 중 심각한 오류 발생: {e}")
        # 여기에 에러 리포팅 시스템 연동 또는 실패 상태 업데이트 등의 로직 추가 가능
        # 예: Snapshots.objects.filter(snapshot_id=snapshot_id).update(processing_status_congestion=ProcessingStatus.FAILED)
        # self.retry(exc=e, countdown=60) # 특정 예외에 대해 재시도 로직 (필요시)
        raise # 오류를 다시 발생시켜 Celery가 실패로 인지하도록 함 (또는 특정 방식으로 처리)