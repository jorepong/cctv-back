import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings.local')
django.setup()

import subprocess
from pathlib import Path
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from django.db import transaction
from analytics.models import Cameras, DetectedObjects, ROIDefinitions, ROIDefinitionType # ROIDefinitionType 추가

from typing import List, Dict, Tuple

# Shapely 라이브러리 임포트
try:
    from shapely.geometry import Polygon, MultiPoint, Point
    from shapely.errors import GEOSException
except ImportError:
    Polygon = None
    MultiPoint = None
    Point = None
    GEOSException = None
    print("Shapely library not found. Please install it: pip install Shapely")

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


# --- Helper Functions ---
def calculate_polygon_area_with_shapely(coordinates: List[Dict[str, float]]) -> float:
    """Shapely를 사용하여 폴리곤 면적 계산"""
    if not Polygon or not coordinates or len(coordinates) < 3:
        return 0.0
    try:
        polygon = Polygon([(p['x'], p['y']) for p in coordinates])
        return polygon.area
    except GEOSException:  # 유효하지 않은 지오메트리일 경우
        return 0.0


def get_footprints_from_detected_objects(camera_id: int, start_time: timezone.datetime) -> List[Tuple[float, float]]:
    """
    주어진 카메라와 시작 시간 이후에 탐지된 객체들로부터 발자취 좌표 리스트를 반환합니다.
    (객체의 바닥 중심 좌표를 발자취로 가정)
    """
    # 실제 필드명과 발자취 정의에 따라 쿼리 수정 필요
    detected_objects = DetectedObjects.objects.filter(
        snapshot__camera_id=camera_id,
        snapshot__captured_at__gte=start_time,
        class_label='person'  # 사람 객체만 고려하는 경우
    ).only('center_x', 'bbox_y', 'bbox_height')  # 필요한 필드만 가져오기

    footprints = []
    for obj in detected_objects:
        if obj.center_x is not None and obj.bbox_y is not None and obj.bbox_height is not None:
            # 바운딩 박스의 하단 중앙을 발자취로 가정
            footprint_x = float(obj.center_x)
            footprint_y = float(obj.bbox_y + obj.bbox_height)  # y축이 아래로 갈수록 커지는 경우
            footprints.append((footprint_x, footprint_y))
    return footprints


# --- Main ROI Update Logic ---
@transaction.atomic  # 데이터베이스 트랜잭션 보장
def update_roi_for_camera_service(camera_id: int, new_footprints: List[Tuple[float, float]]):
    """
    주어진 카메라의 ROI를 새 발자취를 기반으로 업데이트 (확장 중심, 축소 미고려).
    성공 시 True, 실패 또는 변경 없음 시 False 반환.
    """
    if not Polygon:  # Shapely가 없는 경우
        print("Shapely is not available. Cannot update ROI.")
        return False

    try:
        camera = Cameras.objects.get(camera_id=camera_id)
    except Cameras.DoesNotExist:
        print(f"[ROI Update] Camera with ID {camera_id} not found.")
        return False

    current_roi_def = ROIDefinitions.objects.filter(camera=camera, is_active=True).first()

    existing_roi_shapely_polygon = None
    existing_roi_points_for_hull = []

    if current_roi_def and current_roi_def.definition_data and 'coordinates' in current_roi_def.definition_data:
        existing_coords_dict = current_roi_def.definition_data['coordinates']
        if len(existing_coords_dict) >= 3:
            try:
                existing_roi_points_for_hull = [(p['x'], p['y']) for p in existing_coords_dict]
                existing_roi_shapely_polygon = Polygon(existing_roi_points_for_hull)
            except (GEOSException, TypeError, KeyError) as e:
                print(f"[ROI Update] Error creating existing ROI polygon for camera {camera_id}: {e}")
                existing_roi_shapely_polygon = None
                existing_roi_points_for_hull = []

    points_for_new_hull = list(existing_roi_points_for_hull)  # 기존 ROI 정점으로 시작

    # 새 발자취 중 기존 ROI 외부에 있는 것들만 points_for_new_hull에 추가
    added_new_points = False
    if new_footprints:
        for fp_x, fp_y in new_footprints:
            point_to_check = Point(fp_x, fp_y)
            # 기존 ROI가 없거나, 점이 기존 ROI 내부에 있지 않은 경우 추가
            if not existing_roi_shapely_polygon or not existing_roi_shapely_polygon.contains(point_to_check):
                points_for_new_hull.append((fp_x, fp_y))
                added_new_points = True

    # 새롭게 추가된 외부 포인트가 없거나, 전체 포인트 수가 3개 미만이면 업데이트 불필요/불가
    if not added_new_points and existing_roi_shapely_polygon:
        print(f"[ROI Update] No new *outside* footprints to update ROI for camera {camera_id}. Current ROI maintained.")
        return False

    if len(points_for_new_hull) < 3:
        print(f"[ROI Update] Not enough points ({len(points_for_new_hull)}) to form/update ROI for camera {camera_id}.")
        return False

    # 중복 제거 (선택적, Convex Hull은 중복에 강한편)
    unique_points_for_hull = list(set(points_for_new_hull))
    if len(unique_points_for_hull) < 3:
        print(
            f"[ROI Update] Not enough unique points ({len(unique_points_for_hull)}) after deduplication for camera {camera_id}.")
        return False

    try:
        multi_point = MultiPoint(unique_points_for_hull)
        new_roi_convex_hull_polygon = multi_point.convex_hull
    except GEOSException as e:
        print(f"[ROI Update] Could not compute convex hull for camera {camera_id}: {e}")
        return False

    if not isinstance(new_roi_convex_hull_polygon, Polygon) or new_roi_convex_hull_polygon.is_empty or len(
            new_roi_convex_hull_polygon.exterior.coords) < 3:
        print(f"[ROI Update] New convex hull is not a valid polygon for camera {camera_id}.")
        return False

    new_roi_coordinates_shapely = list(new_roi_convex_hull_polygon.exterior.coords)
    # Shapely의 exterior.coords는 마지막 점이 첫 점과 동일하므로, 중복 제거
    new_roi_coordinates_dict_list = [{"x": p[0], "y": p[1]} for p in new_roi_coordinates_shapely[:-1]]

    if len(new_roi_coordinates_dict_list) < 3:
        print(f"[ROI Update] New ROI coordinates list is insufficient for camera {camera_id}.")
        return False

    new_roi_area = new_roi_convex_hull_polygon.area

    # 기존 ROI와 동일한 경우 업데이트 안 함 (좌표 순서 및 부동소수점 정밀도 고려 필요 시 정교한 비교 필요)
    # 간단히 면적과 좌표 수로 비교하거나, 더 정확하게는 폴리곤 객체 자체를 비교
    if existing_roi_shapely_polygon and existing_roi_shapely_polygon.equals_exact(new_roi_convex_hull_polygon,
                                                                                  tolerance=1e-5):
        print(f"[ROI Update] New ROI is identical to the current ROI for camera {camera_id}. No update needed.")
        return False

    # --- 데이터베이스 업데이트 ---
    roi_definition_data = {
        "type": "DYNAMIC_CONVEX_HULL",  # 또는 다른 적절한 타입
        "coordinates": new_roi_coordinates_dict_list,
        "area": new_roi_area  # 계산된 면적을 함께 저장
    }

    if current_roi_def:
        current_roi_def.definition_data = roi_definition_data
        current_roi_def.updated_at = timezone.now()
        # current_roi_def.version = F('version') + 1 # 버전 관리 시
        current_roi_def.save()
        print(f"[ROI Update] ROI for camera {camera.name} (ID: {camera_id}) UPDATED. New Area: {new_roi_area:.2f}")
    else:
        ROIDefinitions.objects.create(
            camera=camera,
            definition_type=ROIDefinitionType.DYNAMIC_CONVEX_HULL,
            definition_data=roi_definition_data,
            is_active=True,
            version=1
        )
        print(f"[ROI Update] ROI for camera {camera.name} (ID: {camera_id}) CREATED. Area: {new_roi_area:.2f}")

    return True


# --- Celery Periodic Task ---
@shared_task(name="update_all_camera_rois_periodic")
def update_all_camera_rois_periodic_task():
    """
    모든 활성 카메라에 대해 주기적으로 ROI를 업데이트하는 Celery 작업.
    (예: 매 시간 실행되도록 Celery Beat에 등록)
    """
    # ROI 업데이트를 위한 발자취 수집 시간 범위 (예: 지난 1시간)
    # 이 작업의 마지막 실행 시간을 기록하고 해당 시간부터 현재까지의 데이터를 가져오는 것이 더 정확함
    # 여기서는 간단히 1시간으로 설정
    start_time_for_footprints = timezone.now() - timezone.timedelta(hours=1)

    print(f"[ROI Task] Starting periodic ROI update for data since {start_time_for_footprints}...")

    active_cameras = Cameras.objects.filter(is_active_monitoring=True)
    if not active_cameras.exists():
        print("[ROI Task] No active cameras found for ROI update.")
        return

    updated_count = 0
    for camera in active_cameras:
        print(f"[ROI Task] Processing camera: {camera.name} (ID: {camera.camera_id})")
        new_footprints = get_footprints_from_detected_objects(camera.camera_id, start_time_for_footprints)

        if not new_footprints:
            print(f"[ROI Task] No new footprints found for camera {camera.name} since {start_time_for_footprints}.")
            continue

        print(f"[ROI Task] Found {len(new_footprints)} new footprints for camera {camera.name}.")
        if update_roi_for_camera_service(camera.camera_id, new_footprints):
            updated_count += 1

    print(f"[ROI Task] Periodic ROI update finished. {updated_count} camera(s) had their ROIs updated/created.")