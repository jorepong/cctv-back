# analytics/congestion_analysis_tasks.py

import os
import django
from datetime import datetime

# Django 프로젝트 설정을 로드합니다.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings.local')
django.setup()

from django.utils import timezone
from django.db import transaction
from analytics.models import Cameras, DetectedObjects, ROIDefinitions, ROIDefinitionType
from typing import List, Tuple, Dict

# Shapely 라이브러리
try:
    from shapely.geometry import Polygon, MultiPoint, Point
    from shapely.errors import GEOSException
except ImportError:
    Polygon = None
    MultiPoint = None
    Point = None
    GEOSException = None
    # --- [수정] 시작 시점에 한 번만 경고 로그를 남기도록 변경 ---
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ⚠️ Shapely 라이브러리를 찾을 수 없습니다. 'pip install Shapely'로 설치해주세요. ROI 관련 기능이 비활성화됩니다.")


# --- [추가] 표준 로그 함수 ---
def log_with_time(message: str):
    """시간과 함께 로그 메시지 출력 (프로젝트 표준)"""
    current_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{current_time}] {message}")


# --- Helper Functions (내용 변경 없음) ---

def calculate_polygon_area_with_shapely(coordinates: List[Dict[str, float]]) -> float:
    if not Polygon or not coordinates or len(coordinates) < 3:
        return 0.0
    try:
        polygon = Polygon([(p['x'], p['y']) for p in coordinates])
        return polygon.area
    except GEOSException:
        return 0.0


def get_footprints_from_detected_objects(camera_id: int, start_time: timezone.datetime) -> List[Tuple[float, float]]:
    detected_objects = DetectedObjects.objects.filter(
        snapshot__camera_id=camera_id,
        snapshot__captured_at__gte=start_time,
        class_label='person'
    ).only('center_x', 'bbox_y', 'bbox_height')

    footprints = []
    for obj in detected_objects:
        if obj.center_x is not None and obj.bbox_y is not None and obj.bbox_height is not None:
            footprint_x = float(obj.center_x)
            footprint_y = float(obj.bbox_y + obj.bbox_height)
            footprints.append((footprint_x, footprint_y))
    return footprints


# --- Main ROI Update Logic (Service Function) ---
@transaction.atomic
def update_roi_for_camera_service(camera_id: int, new_footprints: List[Tuple[float, float]]) -> bool:
    """
    주어진 카메라의 동적 ROI를 새로운 발자취 데이터를 기반으로 업데이트합니다.
    (로그 메시지 위주로 수정)
    """
    if not Polygon:
        # Shapely가 없는 경우, 시작 시점에만 경고하므로 여기서는 조용히 실패 처리합니다.
        return False

    try:
        camera = Cameras.objects.get(camera_id=camera_id)
    except Cameras.DoesNotExist:
        # --- [수정] 표준 로그 형식 적용 ---
        log_with_time(f"❌ [ROI] 존재하지 않는 카메라 ID: {camera_id}")
        return False

    current_roi_def = ROIDefinitions.objects.filter(camera=camera, is_active=True).first()
    existing_roi_shapely_polygon = None
    existing_roi_points_for_hull = []

    if current_roi_def and current_roi_def.definition_data and 'coordinates' in current_roi_def.definition_data:
        existing_coords_dict = current_roi_def.definition_data.get('coordinates', [])
        if len(existing_coords_dict) >= 3:
            try:
                existing_roi_points_for_hull = [(p['x'], p['y']) for p in existing_coords_dict]
                existing_roi_shapely_polygon = Polygon(existing_roi_points_for_hull)
            except (GEOSException, TypeError, KeyError) as e:
                # --- [수정] 표준 로그 형식 적용 ---
                log_with_time(f"⚠️ [ROI] 카메라 {camera_id}의 기존 ROI 데이터 파싱 오류: {e}")
                existing_roi_shapely_polygon = None
                existing_roi_points_for_hull = []

    points_for_new_hull = list(existing_roi_points_for_hull)
    added_new_points = False
    if new_footprints:
        for fp_x, fp_y in new_footprints:
            point_to_check = Point(fp_x, fp_y)
            if not existing_roi_shapely_polygon or not existing_roi_shapely_polygon.contains(point_to_check):
                points_for_new_hull.append((fp_x, fp_y))
                added_new_points = True

    # --- [삭제] "새로운 외부 발자취 없음" 로그 삭제 (정상 상황이므로 노이즈 감소) ---
    if not added_new_points and existing_roi_shapely_polygon:
        return False

    # --- [삭제] "포인트 부족" 로그 삭제 (노이즈 감소, 최종 실패로 처리) ---
    if len(points_for_new_hull) < 3:
        return False

    unique_points_for_hull = list(set(points_for_new_hull))
    if len(unique_points_for_hull) < 3:
        return False

    try:
        multi_point = MultiPoint(unique_points_for_hull)
        new_roi_convex_hull_polygon = multi_point.convex_hull
    except GEOSException as e:
        # --- [수정] 표준 로그 형식 적용 ---
        log_with_time(f"❌ [ROI] 카메라 {camera_id} Convex Hull 계산 오류: {e}")
        return False

    if not isinstance(new_roi_convex_hull_polygon, Polygon) or new_roi_convex_hull_polygon.is_empty:
        return False

    new_roi_coordinates_shapely = list(new_roi_convex_hull_polygon.exterior.coords)
    new_roi_coordinates_dict_list = [{"x": p[0], "y": p[1]} for p in new_roi_coordinates_shapely[:-1]]

    if len(new_roi_coordinates_dict_list) < 3:
        return False

    # --- [삭제] "새 ROI가 현재 ROI와 동일" 로그 삭제 (정상 상황이므로 노이즈 감소) ---
    if existing_roi_shapely_polygon and existing_roi_shapely_polygon.equals_exact(new_roi_convex_hull_polygon, tolerance=1e-5):
        return False

    new_roi_area = new_roi_convex_hull_polygon.area
    roi_definition_data = {
        "type": "DYNAMIC_CONVEX_HULL",
        "coordinates": new_roi_coordinates_dict_list,
        "area": new_roi_area
    }

    # --- [수정] 생성/업데이트 시 로그 메시지 개선 ---
    if current_roi_def:
        current_roi_def.definition_data = roi_definition_data
        current_roi_def.updated_at = timezone.now()
        current_roi_def.save()
        log_with_time(f"🔄 [ROI] 카메라 '{camera.name}'({camera_id}) ROI 업데이트됨. 면적: {new_roi_area:.2f}")
    else:
        ROIDefinitions.objects.create(
            camera=camera,
            definition_type=ROIDefinitionType.DYNAMIC_CONVEX_HULL,
            definition_data=roi_definition_data,
            is_active=True,
            version=1
        )
        log_with_time(f"✨ [ROI] 카메라 '{camera.name}'({camera_id}) ROI 생성됨. 면적: {new_roi_area:.2f}")

    return True


def update_all_camera_rois_periodic_task():
    """
    주기적으로 동적 ROI를 업데이트하는 태스크 (로그 메시지 위주로 수정)
    """
    start_time_for_footprints = timezone.now() - timezone.timedelta(hours=1)
    # --- [수정] 시작 로그 개선 ---
    log_with_time(f"🚀 주기적 ROI 업데이트 태스크 시작 (대상 시간: {start_time_for_footprints.strftime('%Y-%m-%d %H:%M:%S')} 이후)")

    active_cameras = Cameras.objects.filter(is_active_monitoring=True)
    if not active_cameras.exists():
        # --- [수정] 표준 로그 형식 적용 및 메시지 개선 ---
        log_with_time("⚠️ 활성 모니터링 카메라가 없어 ROI 업데이트를 건너뜁니다.")
        return

    updated_count = 0
    for camera in active_cameras:
        new_footprints = get_footprints_from_detected_objects(camera.camera_id, start_time_for_footprints)

        # --- [삭제] "카메라 처리중", "새로운 발자취 없음" 로그 삭제 (노이즈 감소) ---
        if not new_footprints:
            continue

        # --- [수정] 실제 업데이트가 필요한 경우에만 로그를 남기도록 변경 ---
        log_with_time(f"🔍 [ROI] 카메라 '{camera.name}'({camera.camera_id})에서 새 발자취 {len(new_footprints)}개 발견, ROI 업데이트 시도")
        if update_roi_for_camera_service(camera.camera_id, new_footprints):
            updated_count += 1

    # --- [수정] 완료 로그 개선 ---
    log_with_time(f"✅ 주기적 ROI 업데이트 완료. 📊 {updated_count}개 카메라의 ROI가 업데이트/생성되었습니다.")