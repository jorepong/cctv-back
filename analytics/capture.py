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
    try:
        camera = Cameras.objects.get(pk=camera_id)
    except Cameras.DoesNotExist:
        log_with_time(f"❌ 존재하지 않는 카메라 ID: {camera_id}")
        return False

    timestamp = localtime(dj_now())
    timestamp_str = "snap_" + timestamp.strftime('%y%m%d%H%M%S')

    # --- [수정된 부분 1] ---
    # Path.cwd() 대신 __file__을 사용하여 현재 파일의 위치를 기준으로 경로를 설정합니다.
    # 이렇게 하면 어디서 실행되든 항상 'analytics/captured/' 폴더에 저장됩니다.
    script_dir = Path(__file__).resolve().parent
    cam_dir = script_dir / "captured" / str(camera.camera_id)
    # --- [수정 끝] ---
    cam_dir.mkdir(parents=True, exist_ok=True)

    image_path = cam_dir / f"{timestamp_str}.jpg"
    rtsp_url = camera.rtsp_url

    log_with_time(f"📸 직접 캡처 시작 (카메라 {camera_id})")

    try:
        # RTSP에서 직접 JPG로 캡처 (1단계)
        result = subprocess.run([
            "ffmpeg",
            "-rtsp_transport", "tcp",  # TCP 전송 (더 안정적)
            "-analyzeduration", "5000000",  # 5초 분석
            "-probesize", "5000000",  # 5MB 프로브
            "-i", rtsp_url,  # 입력 RTSP
            "-frames:v", "1",  # 첫 번째 프레임만
            "-q:v", "2",  # 고품질 (1-31, 낮을수록 좋음)
            "-y",  # 덮어쓰기 허용
            str(image_path)
        ],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            log_with_time(f"❌ ffmpeg 실패: {result.stderr}")
            return False

        if not image_path.exists():
            log_with_time(f"❌ 이미지 파일 생성 실패")
            return False

        # 파일 크기 확인 (너무 작으면 오류)
        file_size = image_path.stat().st_size
        if file_size < 1000:  # 1KB 미만이면 오류
            log_with_time(f"❌ 이미지 파일이 너무 작음 ({file_size} bytes)")
            image_path.unlink()  # 잘못된 파일 삭제
            return False

        # 데이터베이스에 저장
        snapshot = Snapshots.objects.create(
            camera=camera,
            captured_at=timestamp,
            image_path=str(image_path),
            processing_status_ai='PENDING',
            processing_status_congestion='PENDING'
        )

        log_with_time(f"✅ 스냅샷 저장 완료: {image_path.name} ({file_size:,} bytes)")

        async_task(
            'analytics.services.analyze_snapshot_task',
            snapshot.snapshot_id,
            q_options={'group': f'snapshot-analysis-{camera_id}'}
        )

        return True

    except subprocess.TimeoutExpired:
        log_with_time("⚠️ ffmpeg 타임아웃 (15초)")
        return False
    except Exception as e:
        log_with_time(f"❌ 캡처 오류: {e}")
        # 실패 시 생성된 파일 정리
        if image_path.exists():
            try:
                image_path.unlink()
            except:
                pass
        return False


def capture_snapshot_hls_direct(camera_id: int) -> bool:
    """HLS에서 직접 JPG 캡처"""
    try:
        camera = Cameras.objects.get(pk=camera_id)
    except Cameras.DoesNotExist:
        log_with_time(f"❌ 존재하지 않는 카메라 ID: {camera_id}")
        return False

    timestamp = localtime(dj_now())
    timestamp_str = "snap_" + timestamp.strftime('%y%m%d%H%M%S')

    # --- [수정된 부분 2] ---
    # Path.cwd() 대신 __file__을 사용하여 현재 파일의 위치를 기준으로 경로를 설정합니다.
    script_dir = Path(__file__).resolve().parent
    cam_dir = script_dir / "captured" / str(camera.camera_id)
    # --- [수정 끝] ---
    cam_dir.mkdir(parents=True, exist_ok=True)

    image_path = cam_dir / f"{timestamp_str}.jpg"
    hls_url = camera.rtsp_url

    log_with_time(f"🌐 HLS 직접 캡처 시작 (카메라 {camera_id})")

    try:
        # HLS에서 직접 JPG로 캡처
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
            log_with_time(f"❌ ffmpeg 실패: {result.stderr}")
            return False

        if not image_path.exists():
            log_with_time(f"❌ 이미지 파일 생성 실패")
            return False

        file_size = image_path.stat().st_size
        if file_size < 1000:
            log_with_time(f"❌ 이미지 파일이 너무 작음 ({file_size} bytes)")
            image_path.unlink()
            return False

        snapshot = Snapshots.objects.create(
            camera=camera,
            captured_at=timestamp,
            image_path=str(image_path),
            processing_status_ai='PENDING',
            processing_status_congestion='PENDING'
        )

        log_with_time(f"✅ HLS 스냅샷 저장 완료: {image_path.name} ({file_size:,} bytes)")

        async_task(
            'analytics.services.analyze_snapshot_task',
            snapshot.snapshot_id,
            q_options={'group': f'snapshot-analysis-{camera_id}'}
        )

        return True

    except subprocess.TimeoutExpired:
        log_with_time("⚠️ ffmpeg 타임아웃 (15초)")
        return False
    except Exception as e:
        log_with_time(f"❌ 캡처 오류: {e}")
        if image_path.exists():
            try:
                image_path.unlink()
            except:
                pass
        return False


def test_connection(camera_id: int) -> bool:
    """연결 테스트"""
    try:
        camera = Cameras.objects.get(pk=camera_id)
        rtsp_url = camera.rtsp_url

        log_with_time(f"🧪 연결 테스트: {rtsp_url}")

        # 매우 짧은 테스트 (1초만)
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
                log_with_time(f"✅ 연결 성공: {width}x{height}, {codec}")
                return True

        log_with_time(f"❌ 연결 실패: {result.stderr}")
        return False

    except subprocess.TimeoutExpired:
        log_with_time("⚠️ 연결 테스트 타임아웃")
        return False
    except Exception as e:
        log_with_time(f"❌ 연결 테스트 오류: {e}")
        return False


def capture_single_camera(camera):
    """단일 카메라 캡처"""
    try:
        if camera.source_type == "HLS":
            return capture_snapshot_hls_direct(camera.camera_id)
        else:
            return capture_snapshot_direct_ffmpeg(camera.camera_id)
    except Exception as e:
        log_with_time(f"❌ 카메라 {camera.camera_id} 캡처 중 오류: {e}")
        return False


def capture_all_active_cameras():
    """모든 활성 카메라 캡처 (병렬 처리)"""
    try:
        # 활성화된 카메라들 조회 (is_active 필드가 있다고 가정)
        # 필드명이 다르다면 적절히 수정해주세요
        active_cameras = Cameras.objects.filter(status=CameraStatus.ACTIVE, is_active_monitoring=True)

        if not active_cameras.exists():
            log_with_time("⚠️ 활성화된 카메라가 없습니다.")
            return

        camera_count = active_cameras.count()
        log_with_time(f"📸 {camera_count}개 활성 카메라 캡처 시작")

        success_count = 0

        # 병렬 처리로 모든 카메라 동시 캡처
        with ThreadPoolExecutor(max_workers=min(camera_count, 10)) as executor:
            # 모든 카메라에 대해 캡처 작업 제출
            future_to_camera = {
                executor.submit(capture_single_camera, camera): camera
                for camera in active_cameras
            }

            # 결과 수집
            for future in as_completed(future_to_camera):
                camera = future_to_camera[future]
                try:
                    success = future.result()
                    if success:
                        success_count += 1
                except Exception as e:
                    log_with_time(f"❌ 카메라 {camera.camera_id} 처리 중 예외 발생: {e}")

        success_rate = (success_count / camera_count) * 100
        log_with_time(f"📊 캡처 완료: {success_count}/{camera_count} ({success_rate:.1f}%)")

    except Exception as e:
        log_with_time(f"❌ 전체 캡처 과정에서 오류 발생: {e}")


def capture_all_active_cameras_task():
    """Django-Q2에서 실행할 태스크 함수"""
    log_with_time("🚀 Django-Q2 카메라 캡처 태스크 시작")

    # 30초 간격으로 2번 실행 (1분마다 스케줄되므로)
    for i in range(2):
        if i > 0:
            time.sleep(30)  # 30초 대기

        capture_all_active_cameras()

    log_with_time("✅ Django-Q2 카메라 캡처 태스크 완료")


# 기존 메인 실행 부분 (테스트/디버깅용으로 유지)
if __name__ == "__main__":
    print("=" * 50)
    print("카메라 캡처 모드 선택:")
    print("1. 단일 카메라 연속 캡처 (기존 방식)")
    print("2. 모든 활성 카메라 한 번 캡처 (테스트)")
    print("=" * 50)

    mode = input("모드를 선택하세요 (1 또는 2): ").strip()

    if mode == "2":
        # 모든 활성 카메라 한 번 캡처
        capture_all_active_cameras()
    else:
        # 기존 단일 카메라 연속 캡처
        try:
            camera_id = int(input("🎥 캡처할 카메라 ID를 입력하세요: "))
        except ValueError:
            log_with_time("❌ 잘못된 입력입니다. 정수를 입력해주세요.")
            exit(1)

        # 카메라 확인
        try:
            camera = Cameras.objects.get(pk=camera_id)
        except Cameras.DoesNotExist:
            log_with_time(f"❌ 존재하지 않는 카메라 ID: {camera_id}")
            exit(1)

        # 연결 테스트
        log_with_time("🔍 연결 테스트 중...")
        if not test_connection(camera_id):
            log_with_time("⚠️ 연결 테스트 실패, 그래도 계속 진행합니다.")

        # 캡처 함수 선택
        if camera.source_type == "HLS":
            log_with_time(f"🌐 HLS 스트림 캡처 모드")
            capture_func = capture_snapshot_hls_direct
        else:
            log_with_time(f"📹 RTSP 스트림 캡처 모드")
            capture_func = capture_snapshot_direct_ffmpeg

        log_with_time("📸 30초 간격 캡처 시작 (Ctrl+C로 중지)")

        # 통계 변수
        success_count = 0
        total_count = 0

        try:
            while True:
                start_time = time.time()
                total_count += 1

                success = capture_func(camera_id)
                if success:
                    success_count += 1

                # 통계 출력 (10회마다)
                if total_count % 10 == 0:
                    success_rate = (success_count / total_count) * 100
                    log_with_time(f"📊 성공률: {success_count}/{total_count} ({success_rate:.1f}%)")

                # 정확한 30초 간격 유지
                elapsed = time.time() - start_time
                sleep_time = max(0, 30 - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            log_with_time("🛑 사용자에 의해 중지됨")
            if total_count > 0:
                success_rate = (success_count / total_count) * 100
                log_with_time(f"📊 최종 성공률: {success_count}/{total_count} ({success_rate:.1f}%)")
        except Exception as e:
            log_with_time(f"❌ 예상치 못한 오류: {e}")

    log_with_time("🔄 프로그램 종료")