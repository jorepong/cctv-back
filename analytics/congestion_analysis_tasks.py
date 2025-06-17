# analytics/congestion_analysis_tasks.py

import os
import django

# Django 프로젝트 설정을 로드합니다. SmartCCTV.settings.local을 사용합니다.
# 스크립트가 Django ORM 및 설정을 사용할 수 있도록 환경을 설정합니다.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings.local')
django.setup()
print(__file__)

from django.utils import timezone
from django.db import transaction

# 프로젝트의 analytics 앱에서 필요한 모델들을 가져옵니다.
# Cameras: CCTV 카메라 정보
# DetectedObjects: AI에 의해 탐지된 객체 정보 (예: 사람, 바운딩 박스 좌표)
# ROIDefinitions: 카메라별 관심 영역(ROI) 정의 정보
# ROIDefinitionType: ROI 정의 방식에 대한 선택지 (예: 동적 컨벡스 헐)
from analytics.models import Cameras, DetectedObjects, ROIDefinitions, ROIDefinitionType

from typing import List, Dict, Tuple

# Shapely 라이브러리: 고급 기하학적 연산(폴리곤 면적, 컨벡스 헐 등)을 위해 사용됩니다.
# 이 라이브러리가 없으면 ROI 계산 기능 중 일부가 제한될 수 있습니다.
try:
    from shapely.geometry import Polygon, MultiPoint, Point
    from shapely.errors import GEOSException # Shapely 관련 예외 처리
except ImportError:
    Polygon = None
    MultiPoint = None
    Point = None
    GEOSException = None
    print("Shapely 라이브러리를 찾을 수 없습니다. 'pip install Shapely'로 설치해주세요.")

# --- Helper Functions ---

def calculate_polygon_area_with_shapely(coordinates: List[Dict[str, float]]) -> float:
    """
    주어진 좌표 리스트( [{'x': x1, 'y': y1}, ...] 형태)를 사용하여 폴리곤의 면적을 계산합니다.
    Shapely 라이브러리의 Polygon 객체를 활용하여 정확한 면적을 구합니다.

    Args:
        coordinates: 폴리곤을 구성하는 점들의 좌표 리스트. 각 점은 {'x': x_coord, 'y': y_coord} 형태의 딕셔너리입니다.

    Returns:
        계산된 폴리곤의 면적 (float). 유효하지 않거나 점이 부족하면 0.0을 반환합니다.
    """
    # Shapely 라이브러리가 없거나, 좌표가 없거나, 3개 미만의 점으로는 폴리곤을 만들 수 없습니다.
    if not Polygon or not coordinates or len(coordinates) < 3:
        return 0.0
    try:
        # 좌표 리스트로부터 Shapely Polygon 객체를 생성합니다.
        polygon = Polygon([(p['x'], p['y']) for p in coordinates])
        # 생성된 폴리곤의 면적을 반환합니다.
        return polygon.area
    except GEOSException:  # Shapely가 유효하지 않은 지오메트리(예: 자기 교차 폴리곤)를 처리하려 할 때 발생
        return 0.0


def get_footprints_from_detected_objects(camera_id: int, start_time: timezone.datetime) -> List[Tuple[float, float]]:
    """
    특정 카메라에서 지정된 시작 시간 이후에 탐지된 '사람' 객체들로부터 '발자취' 좌표 리스트를 추출합니다.
    여기서 '발자취'는 각 탐지된 사람의 바운딩 박스 하단 중앙 좌표로 가정합니다.
    이 발자취들은 동적 ROI(관심 영역)를 업데이트하는 데 사용됩니다.

    Args:
        camera_id: 발자취를 조회할 카메라의 ID.
        start_time: 이 시간 이후에 캡처된 스냅샷에서 탐지된 객체들을 대상으로 합니다.

    Returns:
        (x, y) 좌표 튜플의 리스트. 각 튜플은 탐지된 사람의 발자취를 나타냅니다.
        탐지된 객체가 없거나 유효한 좌표가 없으면 빈 리스트를 반환합니다.
    """
    # Django ORM을 사용하여 데이터베이스에서 관련 DetectedObjects를 조회합니다.
    # 조건: 특정 카메라 ID, 특정 시간 이후, 객체 레이블이 'person'인 경우
    # .only(): 필요한 필드(center_x, bbox_y, bbox_height)만 선택적으로 로드하여 성능을 최적화합니다.
    detected_objects = DetectedObjects.objects.filter(
        snapshot__camera_id=camera_id,      # Snapshots 모델을 통해 Cameras 모델과 연결
        snapshot__captured_at__gte=start_time, # 지정된 시간 이후의 스냅샷
        class_label='person'                 # '사람'으로 분류된 객체만 대상
    ).only('center_x', 'bbox_y', 'bbox_height')

    footprints = []
    for obj in detected_objects:
        # 객체의 중심 x좌표, 바운딩 박스 y좌표, 높이 정보가 모두 있어야 발자취 계산 가능
        if obj.center_x is not None and obj.bbox_y is not None and obj.bbox_height is not None:
            # 발자취의 x좌표는 객체의 중심 x좌표를 사용합니다.
            footprint_x = float(obj.center_x)
            # 발자취의 y좌표는 바운딩 박스의 하단 y좌표 (bbox_y + bbox_height)로 가정합니다.
            # (이미지 좌표계에서 y축이 아래로 갈수록 증가하는 것을 가정)
            footprint_y = float(obj.bbox_y + obj.bbox_height)
            footprints.append((footprint_x, footprint_y))
    return footprints


# --- Main ROI Update Logic (Service Function) ---

# @transaction.atomic 데코레이터는 이 함수 내의 모든 데이터베이스 작업이
# 하나의 트랜잭션으로 처리되도록 보장합니다. 즉, 모든 작업이 성공하거나,
# 하나라도 실패하면 모든 변경사항이 롤백(취소)됩니다. 데이터 정합성을 유지하는 데 중요합니다.
@transaction.atomic
def update_roi_for_camera_service(camera_id: int, new_footprints: List[Tuple[float, float]]) -> bool:
    """
    주어진 카메라의 동적 ROI(관심 영역)를 새로운 발자취 데이터를 기반으로 업데이트(확장)합니다.
    이 함수는 기존 ROI에 새로운 발자취들을 포함하는 최소 크기의 볼록 다각형(Convex Hull)을 계산하여
    ROI를 갱신합니다. 현재 로직은 ROI를 확장만 하며, 축소는 고려하지 않습니다.

    Args:
        camera_id: ROI를 업데이트할 카메라의 ID.
        new_footprints: ROI 업데이트에 사용할 새로운 발자취 좌표 리스트. (get_footprints_from_detected_objects의 결과)

    Returns:
        ROI가 성공적으로 업데이트되거나 새로 생성되었으면 True를 반환합니다.
        Shapely 라이브러리가 없거나, 카메라가 없거나, 업데이트할 유효한 포인트가 없거나,
        기존 ROI와 동일하여 변경이 없는 경우 False를 반환합니다.
    """
    # Shapely 라이브러리가 설치되어 있지 않으면 ROI 계산 및 업데이트를 수행할 수 없습니다.
    if not Polygon:
        print("Shapely 라이브러리가 없어 ROI 업데이트를 수행할 수 없습니다.")
        return False

    try:
        # 업데이트 대상 카메라 정보를 데이터베이스에서 가져옵니다.
        camera = Cameras.objects.get(camera_id=camera_id)
    except Cameras.DoesNotExist:
        print(f"[ROI 업데이트] ID가 {camera_id}인 카메라를 찾을 수 없습니다.")
        return False

    # 현재 카메라에 활성화된(is_active=True) ROI 정의를 가져옵니다.
    # .first()는 조건에 맞는 첫 번째 객체를 반환하거나, 없으면 None을 반환합니다.
    current_roi_def = ROIDefinitions.objects.filter(camera=camera, is_active=True).first()

    existing_roi_shapely_polygon = None # 기존 ROI를 Shapely Polygon 객체로 변환하여 저장할 변수
    existing_roi_points_for_hull = []   # 기존 ROI의 정점들을 (x,y) 튜플 리스트로 저장할 변수

    # 기존 ROI 정의가 있고, 그 안에 'coordinates' 데이터가 있는 경우
    if current_roi_def and current_roi_def.definition_data and 'coordinates' in current_roi_def.definition_data:
        existing_coords_dict = current_roi_def.definition_data['coordinates']
        # 최소 3개의 점이 있어야 유효한 폴리곤을 형성할 수 있습니다.
        if len(existing_coords_dict) >= 3:
            try:
                # 기존 ROI 좌표를 (x,y) 튜플 리스트로 변환
                existing_roi_points_for_hull = [(p['x'], p['y']) for p in existing_coords_dict]
                # 이 좌표들로 Shapely Polygon 객체 생성
                existing_roi_shapely_polygon = Polygon(existing_roi_points_for_hull)
            except (GEOSException, TypeError, KeyError) as e:
                # 기존 ROI 데이터가 유효하지 않아 폴리곤 생성에 실패한 경우
                print(f"[ROI 업데이트] 카메라 {camera_id}의 기존 ROI 폴리곤 생성 오류: {e}")
                existing_roi_shapely_polygon = None
                existing_roi_points_for_hull = []

    # 새 Convex Hull을 계산하기 위한 포인트 리스트. 기존 ROI의 정점들로 시작합니다.
    points_for_new_hull = list(existing_roi_points_for_hull)

    added_new_points = False # 새 발자취 중 기존 ROI 외부에 있는 것이 추가되었는지 여부
    if new_footprints:
        for fp_x, fp_y in new_footprints:
            point_to_check = Point(fp_x, fp_y) # 새 발자취를 Shapely Point 객체로 변환
            # 기존 ROI가 없거나(처음 ROI 생성 시), 또는 새 발자취가 기존 ROI 내부에 포함되지 않는 경우
            if not existing_roi_shapely_polygon or not existing_roi_shapely_polygon.contains(point_to_check):
                points_for_new_hull.append((fp_x, fp_y)) # 새 Convex Hull 계산을 위해 포인트 추가
                added_new_points = True

    # 만약 기존 ROI가 있고, 새롭게 추가된 *외부* 발자취가 없다면, ROI는 변경되지 않습니다.
    if not added_new_points and existing_roi_shapely_polygon:
        print(f"[ROI 업데이트] 카메라 {camera_id}의 ROI를 업데이트할 새로운 *외부* 발자취가 없습니다. 현재 ROI 유지.")
        return False

    # Convex Hull을 계산하기에 포인트 수가 부족한 경우 (최소 3개 필요)
    if len(points_for_new_hull) < 3:
        print(f"[ROI 업데이트] 카메라 {camera_id}의 ROI를 형성/업데이트하기에 포인트({len(points_for_new_hull)}개)가 충분하지 않습니다.")
        return False

    # 중복된 포인트를 제거합니다 (선택적 단계, Convex Hull 알고리즘은 중복에 비교적 강인함).
    unique_points_for_hull = list(set(points_for_new_hull))
    if len(unique_points_for_hull) < 3:
        print(
            f"[ROI 업데이트] 카메라 {camera_id}의 중복 제거 후 유니크한 포인트({len(unique_points_for_hull)}개)가 충분하지 않습니다.")
        return False

    try:
        # 유니크한 포인트들로 MultiPoint 객체를 생성하고, 이로부터 Convex Hull을 계산합니다.
        # Convex Hull은 주어진 모든 점을 포함하는 가장 작은 볼록 다각형입니다.
        multi_point = MultiPoint(unique_points_for_hull)
        new_roi_convex_hull_polygon = multi_point.convex_hull
    except GEOSException as e:
        print(f"[ROI 업데이트] 카메라 {camera_id}의 Convex Hull 계산 실패: {e}")
        return False

    # 계산된 Convex Hull이 유효한 폴리곤인지, 비어있지 않은지, 최소 3개의 정점을 가졌는지 확인합니다.
    if not isinstance(new_roi_convex_hull_polygon, Polygon) or new_roi_convex_hull_polygon.is_empty or len(
            new_roi_convex_hull_polygon.exterior.coords) < 3: # exterior.coords는 폴리곤 외부 경계선 좌표들
        print(f"[ROI 업데이트] 카메라 {camera_id}에 대해 새로 계산된 Convex Hull이 유효한 폴리곤이 아닙니다.")
        return False

    # 새 ROI 폴리곤의 외부 경계선 좌표를 가져옵니다.
    new_roi_coordinates_shapely = list(new_roi_convex_hull_polygon.exterior.coords)
    # Shapely의 exterior.coords는 마지막 점이 첫 점과 동일하게 중복되므로, 마지막 점을 제거합니다.
    # 또한, DB에 저장할 형태인 {'x':x, 'y':y} 딕셔너리 리스트로 변환합니다.
    new_roi_coordinates_dict_list = [{"x": p[0], "y": p[1]} for p in new_roi_coordinates_shapely[:-1]]

    if len(new_roi_coordinates_dict_list) < 3:
        print(f"[ROI 업데이트] 카메라 {camera_id}에 대한 새 ROI 좌표 리스트가 충분하지 않습니다.")
        return False

    # 새 ROI의 면적을 계산합니다.
    new_roi_area = new_roi_convex_hull_polygon.area

    # 새로 계산된 ROI가 기존 ROI와 동일한지 비교합니다. (부동소수점 정밀도 오차 고려)
    # Shapely의 `equals_exact` 메소드는 허용 오차(tolerance) 내에서 두 지오메트리가 동일한지 비교합니다.
    if existing_roi_shapely_polygon and existing_roi_shapely_polygon.equals_exact(new_roi_convex_hull_polygon,
                                                                                  tolerance=1e-5):
        print(f"[ROI 업데이트] 새 ROI가 카메라 {camera_id}의 현재 ROI와 동일합니다. 업데이트 불필요.")
        return False

    # --- 데이터베이스 업데이트 ---
    # ROIDefinitions 모델에 저장할 데이터 구조를 준비합니다.
    roi_definition_data = {
        "type": "DYNAMIC_CONVEX_HULL",  # 이 ROI가 동적 Convex Hull 방식으로 생성되었음을 명시
        "coordinates": new_roi_coordinates_dict_list, # 새 ROI의 정점 좌표
        "area": new_roi_area  # 계산된 새 ROI의 면적 (나중에 혼잡도 계산 등에 활용 가능)
    }

    if current_roi_def: # 기존 ROI 정의가 있으면 업데이트
        current_roi_def.definition_data = roi_definition_data
        current_roi_def.updated_at = timezone.now() # 수정 시각 업데이트
        # 만약 ROI 정의에 버전 관리가 필요하다면, 아래 주석 처리된 코드처럼 버전을 증가시킬 수 있습니다.
        # from django.db.models import F
        # current_roi_def.version = F('version') + 1
        current_roi_def.save()
        print(f"[ROI 업데이트] 카메라 {camera.name}(ID: {camera_id})의 ROI가 업데이트되었습니다. 새 면적: {new_roi_area:.2f}")
    else: # 기존 ROI 정의가 없으면 새로 생성
        ROIDefinitions.objects.create(
            camera=camera,
            definition_type=ROIDefinitionType.DYNAMIC_CONVEX_HULL, # models.py에 정의된 Enum 값 사용
            definition_data=roi_definition_data,
            is_active=True, # 새로 생성된 ROI를 활성 상태로 설정
            version=1       # 초기 버전은 1
        )
        print(f"[ROI 업데이트] 카메라 {camera.name}(ID: {camera_id})의 ROI가 새로 생성되었습니다. 면적: {new_roi_area:.2f}")

    return True # 성공적으로 업데이트 또는 생성됨


def update_all_camera_rois_periodic_task():
    """
    모든 활성 모니터링 대상 카메라에 대해 주기적으로 동적 ROI를 업데이트하는 Celery 작업입니다.
    이 작업은 설정된 시간 간격(예: 지난 1시간) 동안 수집된 객체 발자취를 사용하여
    각 카메라의 ROI를 최신 상태로 유지하려고 시도합니다.
    """
    # ROI 업데이트를 위해 발자취를 수집할 시간 범위를 설정합니다.
    # 예: 현재 시간으로부터 지난 1시간 동안의 데이터를 사용합니다.
    # 더 정확한 방법은 이 작업의 마지막 성공적 실행 시간을 기록하고,
    # 그 시간부터 현재까지의 데이터를 가져오는 것입니다. (여기서는 단순화된 방식 사용)
    start_time_for_footprints = timezone.now() - timezone.timedelta(hours=1)
    print(f"[ROI 주기적 작업] {start_time_for_footprints} 이후 데이터에 대한 주기적 ROI 업데이트 시작...")

    # is_active_monitoring=True 인 카메라들만 대상으로 ROI를 업데이트합니다.
    active_cameras = Cameras.objects.filter(is_active_monitoring=True)
    if not active_cameras.exists():
        print("[ROI 주기적 작업] ROI 업데이트 대상인 활성 카메라가 없습니다.")
        return

    updated_count = 0 # ROI가 업데이트/생성된 카메라 수
    for camera in active_cameras:
        print(f"[ROI 주기적 작업] 카메라 처리 중: {camera.name} (ID: {camera.camera_id})")
        # 해당 카메라의 지정된 시간 범위 내 발자취를 가져옵니다.
        new_footprints = get_footprints_from_detected_objects(camera.camera_id, start_time_for_footprints)

        if not new_footprints:
            print(f"[ROI 주기적 작업] 카메라 {camera.name}에 대해 {start_time_for_footprints} 이후 새로운 발자취가 없습니다.")
            continue # 다음 카메라로 넘어감

        print(f"[ROI 주기적 작업] 카메라 {camera.name}에 대해 {len(new_footprints)}개의 새로운 발자취를 찾았습니다.")
        # 실제 ROI 업데이트 로직을 호출합니다.
        if update_roi_for_camera_service(camera.camera_id, new_footprints):
            updated_count += 1

    print(f"[ROI 주기적 작업] 주기적 ROI 업데이트 완료. {updated_count}개 카메라의 ROI가 업데이트/생성되었습니다.")