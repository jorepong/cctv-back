import os
import django
from django_q.tasks import async_task

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings.local')
django.setup()

import subprocess
import time
from pathlib import Path
from django.utils.timezone import localtime, now as dj_now
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from analytics.models import Cameras, CameraStatus, Snapshots


def log_with_time(message: str):
    """시간과 함께 로그 메시지 출력"""
    current_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{current_time}] {message}")


def capture_snapshot_direct_ffmpeg(camera_id: int) -> bool:
    """ffmpeg으로 RTSP에서 직접 JPG 캡처"""
    log_prefix = f"[CAM-{camera_id}]"
    try:
        camera = Cameras.objects.get(pk=camera_id)
    except Cameras.DoesNotExist:
        log_with_time(f"[ERROR] {log_prefix} 존재하지 않는 카메라 ID입니다.")
        return False

    timestamp = localtime(dj_now())
    timestamp_str = "snap_" + timestamp.strftime('%y%m%d%H%M%S')

    script_dir = Path(__file__).resolve().parent
    cam_dir = script_dir / "captured" / str(camera.camera_id)
    cam_dir.mkdir(parents=True, exist_ok=True)

    image_path = cam_dir / f"{timestamp_str}.jpg"
    rtsp_url = camera.rtsp_url

    log_with_time(f"[RTSP] {log_prefix} 직접 캡처를 시작합니다...")

    try:
        result = subprocess.run([
            "ffmpeg",
            "-rtsp_transport", "tcp",
            "-analyzeduration", "5000000",
            "-probesize", "5000000",
            "-i", rtsp_url,
            "-frames:v", "1",
            "-q:v", "2",
            "-y",
            str(image_path)
        ],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            log_with_time(f"[ERROR] {log_prefix} ffmpeg 실행 실패: {result.stderr.strip()}")
            return False

        if not image_path.exists():
            log_with_time(f"[ERROR] {log_prefix} 이미지 파일이 생성되지 않았습니다.")
            return False

        file_size = image_path.stat().st_size
        if file_size < 1000:
            log_with_time(f"[ERROR] {log_prefix} 이미지 파일 크기가 너무 작습니다 ({file_size} bytes).")
            image_path.unlink()
            return False

        snapshot = Snapshots.objects.create(
            camera=camera,
            captured_at=timestamp,
            image_path=str(image_path),
            processing_status_ai='PENDING',
            processing_status_congestion='PENDING'
        )

        log_with_time(f"[SUCCESS] {log_prefix} 스냅샷 저장 완료: {image_path.name} ({file_size:,} bytes)")

        async_task(
            'analytics.services.analyze_snapshot_task',
            snapshot.snapshot_id,
            q_options={'group': f'snapshot-analysis-{camera_id}'}
        )

        return True

    except subprocess.TimeoutExpired:
        log_with_time(f"[WARN] {log_prefix} ffmpeg 명령 시간 초과 (15초).")
        return False
    except Exception as e:
        log_with_time(f"[ERROR] {log_prefix} 캡처 실패: {e}")
        if image_path.exists():
            try:
                image_path.unlink()
            except:
                pass
        return False


def capture_snapshot_hls_direct(camera_id: int) -> bool:
    """HLS에서 직접 JPG 캡처"""
    log_prefix = f"[CAM-{camera_id}]"
    try:
        camera = Cameras.objects.get(pk=camera_id)
    except Cameras.DoesNotExist:
        log_with_time(f"[ERROR] {log_prefix} 존재하지 않는 카메라 ID입니다.")
        return False

    timestamp = localtime(dj_now())
    timestamp_str = "snap_" + timestamp.strftime('%y%m%d%H%M%S')

    script_dir = Path(__file__).resolve().parent
    cam_dir = script_dir / "captured" / str(camera.camera_id)
    cam_dir.mkdir(parents=True, exist_ok=True)

    image_path = cam_dir / f"{timestamp_str}.jpg"
    hls_url = camera.rtsp_url

    log_with_time(f"[HLS] {log_prefix} 직접 캡처를 시작합니다...")

    try:
        result = subprocess.run([
            "ffmpeg",
            "-i", hls_url,
            "-frames:v", "1",
            "-q:v", "2",
            "-y",
            str(image_path)
        ],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            log_with_time(f"[ERROR] {log_prefix} ffmpeg 실행 실패: {result.stderr.strip()}")
            return False

        if not image_path.exists():
            log_with_time(f"[ERROR] {log_prefix} 이미지 파일이 생성되지 않았습니다.")
            return False

        file_size = image_path.stat().st_size
        if file_size < 1000:
            log_with_time(f"[ERROR] {log_prefix} 이미지 파일 크기가 너무 작습니다 ({file_size} bytes).")
            image_path.unlink()
            return False

        snapshot = Snapshots.objects.create(
            camera=camera,
            captured_at=timestamp,
            image_path=str(image_path),
            processing_status_ai='PENDING',
            processing_status_congestion='PENDING'
        )

        log_with_time(f"[SUCCESS] {log_prefix} HLS 스냅샷 저장 완료: {image_path.name} ({file_size:,} bytes)")

        async_task(
            'analytics.services.analyze_snapshot_task',
            snapshot.snapshot_id,
            q_options={'group': f'snapshot-analysis-{camera_id}'}
        )

        return True

    except subprocess.TimeoutExpired:
        log_with_time(f"[WARN] {log_prefix} ffmpeg 명령 시간 초과 (15초).")
        return False
    except Exception as e:
        log_with_time(f"[ERROR] {log_prefix} 캡처 실패: {e}")
        if image_path.exists():
            try:
                image_path.unlink()
            except:
                pass
        return False


def test_connection(camera_id: int) -> bool:
    """연결 테스트"""
    log_prefix = f"[CAM-{camera_id}]"
    try:
        camera = Cameras.objects.get(pk=camera_id)
        rtsp_url = camera.rtsp_url

        log_with_time(f"[TEST] {log_prefix} 연결 테스트 시작: {rtsp_url}")

        result = subprocess.run([
            "ffprobe",
            "-v", "error",
            "-rtsp_transport", "tcp",
            "-analyzeduration", "1000000",
            "-probesize", "1000000",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_name,r_frame_rate",
            "-of", "csv=p=0",
            rtsp_url
        ],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            info = result.stdout.strip().split(',')
            if len(info) >= 3:
                width, height, codec = info[0], info[1], info[2]
                log_with_time(f"[SUCCESS] {log_prefix} 연결 성공: {width}x{height}, {codec}")
                return True

        log_with_time(f"[ERROR] {log_prefix} 연결 실패: {result.stderr.strip()}")
        return False

    except subprocess.TimeoutExpired:
        log_with_time(f"[WARN] {log_prefix} 연결 테스트 시간 초과.")
        return False
    except Exception as e:
        log_with_time(f"[ERROR] {log_prefix} 연결 테스트 실패: {e}")
        return False


def capture_single_camera(camera):
    """단일 카메라 캡처"""
    log_prefix = f"[CAM-{camera.camera_id}]"
    try:
        if camera.source_type == "HLS":
            return capture_snapshot_hls_direct(camera.camera_id)
        else:
            return capture_snapshot_direct_ffmpeg(camera.camera_id)
    except Exception as e:
        log_with_time(f"[ERROR] {log_prefix} 캡처 처리 중 예외 발생: {e}")
        return False


def capture_all_active_cameras():
    """모든 활성 카메라 캡처 (병렬 처리)"""
    try:
        active_cameras = Cameras.objects.filter(status=CameraStatus.ACTIVE, is_active_monitoring=True)

        if not active_cameras.exists():
            log_with_time("[WARN] 활성화된 카메라가 없어 캡처를 건너뜁니다.")
            return

        camera_count = active_cameras.count()
        log_with_time(f"[INFO] {camera_count}개의 활성 카메라 캡처를 시작합니다...")

        success_count = 0

        with ThreadPoolExecutor(max_workers=min(camera_count, 10)) as executor:
            future_to_camera = {
                executor.submit(capture_single_camera, camera): camera
                for camera in active_cameras
            }

            for future in as_completed(future_to_camera):
                camera = future_to_camera[future]
                log_prefix = f"[CAM-{camera.camera_id}]"
                try:
                    success = future.result()
                    if success:
                        success_count += 1
                except Exception as e:
                    log_with_time(f"[ERROR] {log_prefix} 작업 처리 중 예외가 발생했습니다: {e}")

        success_rate = (success_count / camera_count) * 100 if camera_count > 0 else 0
        log_with_time(f"[STAT] 캡처 완료. 성공: {success_count}/{camera_count} ({success_rate:.1f}%)")

    except Exception as e:
        log_with_time(f"[ERROR] 전체 캡처 과정에서 심각한 오류가 발생했습니다: {e}")


def capture_all_active_cameras_task():
    """Django-Q2에서 실행할 태스크 함수"""
    log_with_time(">> Django-Q2 카메라 캡처 태스크를 시작합니다...")
    capture_all_active_cameras()
    log_with_time("<< Django-Q2 카메라 캡처 태스크를 완료했습니다.")


# 기존 메인 실행 부분 (테스트/디버깅용으로 유지)
if __name__ == "__main__":
    print("=" * 50)
    print("카메라 캡처 모드를 선택하세요:")
    print("1. 단일 카메라 연속 캡처")
    print("2. 모든 활성 카메라 1회 캡처")
    print("=" * 50)

    mode = input("모드 선택 (1 또는 2): ").strip()

    if mode == "2":
        capture_all_active_cameras()
    else:
        try:
            camera_id_input = input("캡처할 카메라 ID를 입력하세요: ")
            camera_id = int(camera_id_input)
        except ValueError:
            log_with_time("[ERROR] 잘못된 입력입니다. 정수를 입력해주세요.")
            exit(1)

        try:
            camera = Cameras.objects.get(pk=camera_id)
        except Cameras.DoesNotExist:
            log_with_time(f"[ERROR] ID가 {camera_id}인 카메라가 존재하지 않습니다.")
            exit(1)

        log_with_time("[INFO] 연결 테스트를 수행합니다...")
        if not test_connection(camera_id):
            log_with_time("[WARN] 연결 테스트에 실패했습니다. 계속 진행합니다.")

        if camera.source_type == "HLS":
            log_with_time(f"[INFO] 모드 선택: HLS 스트림 캡처 (카메라 ID: {camera.camera_id})")
            capture_func = capture_snapshot_hls_direct
        else:
            log_with_time(f"[INFO] 모드 선택: RTSP 스트림 캡처 (카메라 ID: {camera.camera_id})")
            capture_func = capture_snapshot_direct_ffmpeg

        log_with_time("[INFO] 30초 간격으로 캡처를 시작합니다 (Ctrl+C로 중지)")

        success_count = 0
        total_count = 0

        try:
            while True:
                start_time = time.time()
                total_count += 1

                success = capture_func(camera_id)
                if success:
                    success_count += 1

                if total_count % 10 == 0:
                    success_rate = (success_count / total_count) * 100
                    log_with_time(f"[STAT] 성공률: {success_count}/{total_count} ({success_rate:.1f}%)")

                elapsed = time.time() - start_time
                sleep_time = max(0, 30 - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            log_with_time("[INFO] 사용자가 프로그램을 중지했습니다.")
            if total_count > 0:
                success_rate = (success_count / total_count) * 100
                log_with_time(f"[STAT] 최종 성공률: {success_count}/{total_count} ({success_rate:.1f}%)")
        except Exception as e:
            log_with_time(f"[ERROR] 예기치 않은 오류가 발생했습니다: {e}")

    log_with_time("프로그램을 종료합니다.")