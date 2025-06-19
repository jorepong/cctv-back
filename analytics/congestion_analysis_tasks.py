import os
from pathlib import Path
import django
from datetime import datetime, timedelta
from collections import deque
from PIL import Image, ImageDraw, ImageFont
import logging

# Django 프로젝트 설정을 로드합니다.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings.local')
django.setup()

from django.utils import timezone
from django.db import transaction
from analytics.models import Cameras, DetectedObjects, ROIDefinitions, ROIDefinitionType, Snapshots
from typing import List, Tuple, Dict, Optional

# 통합된 import 및 예외 처리
try:
    import alphashape
    from shapely.geometry import Polygon, MultiPolygon, Point, LineString
    from shapely.errors import GEOSException

    SHAPELY_ALPHASHAPE_INSTALLED = True
except ImportError as e:
    Polygon, MultiPolygon, Point, LineString, GEOSException = None, None, None, None, None
    alphashape = None
    SHAPELY_ALPHASHAPE_INSTALLED = False
    logging.warning(f"Shapely/Alphashape 라이브러리를 찾을 수 없습니다: {e}. ROI 기능이 비활성화됩니다.")

# 설정 상수들
MAX_ROI_POINTS = 1000
ALPHA_CACHE_SIZE = 100
MIN_POINTS_FOR_ROI = 3
DEFAULT_ALPHA_VALUE = 0.01
# [추가] 최초 데이터 수집 기간 (예: 7일)
INITIAL_FETCH_DAYS = 7

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AlphaCache:
    """Alpha 값 캐싱을 위한 클래스"""

    def __init__(self, max_size: int = ALPHA_CACHE_SIZE):
        self._cache = {}
        self._access_order = deque()
        self._max_size = max_size

    def get_alpha(self, points_hash: str) -> Optional[float]:
        if points_hash in self._cache:
            self._access_order.remove(points_hash)
            self._access_order.append(points_hash)
            return self._cache[points_hash]
        return None

    def set_alpha(self, points_hash: str, alpha_value: float):
        if len(self._cache) >= self._max_size:
            oldest = self._access_order.popleft()
            del self._cache[oldest]
        self._cache[points_hash] = alpha_value
        self._access_order.append(points_hash)


alpha_cache = AlphaCache()


def log_with_time(message: str, level: str = "INFO"):
    """개선된 로그 함수"""
    current_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    formatted_message = f"[{current_time}] {message}"
    if level == "ERROR":
        logger.error(formatted_message)
    elif level == "WARN":
        logger.warning(formatted_message)
    else:
        logger.info(formatted_message)


def calculate_points_hash(points: List[Tuple[float, float]]) -> str:
    """포인트 리스트의 해시값 계산 (알파 캐싱용)"""
    return str(hash(tuple(sorted(points))))


def efficient_point_management(existing_points: List[Tuple[float, float]],
                               new_points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """메모리 효율적인 포인트 관리"""
    if not existing_points:
        return new_points[-MAX_ROI_POINTS:]

    total_points = existing_points + new_points
    if len(total_points) <= MAX_ROI_POINTS:
        return total_points

    # [수정] 슬라이딩 윈도우 로직을 더 명확하고 안전하게 변경
    # 필요한 포인트 수만큼 최신 데이터부터 잘라냄
    return total_points[-MAX_ROI_POINTS:]


def calculate_alpha_shape_with_cache(unique_points: List[Tuple[float, float]]) -> Tuple[Optional[Polygon], float]:
    """캐시를 활용한 Alpha Shape 계산"""
    points_hash = calculate_points_hash(unique_points)
    cached_alpha = alpha_cache.get_alpha(points_hash)

    if cached_alpha is not None:
        log_with_time(f"캐시된 알파 값을 사용합니다: {cached_alpha:.4f}")
        alpha_value = cached_alpha
    else:
        if len(unique_points) > 500:
            import random
            sample_points = random.sample(unique_points, 300)
            log_with_time(f"알파 최적화를 위해 {len(sample_points)}개의 샘플 포인트를 사용합니다")
        else:
            sample_points = unique_points
        try:
            alpha_value = alphashape.optimizealpha(sample_points)
            alpha_cache.set_alpha(points_hash, alpha_value)
            log_with_time(f"새로운 알파 값을 계산했습니다: {alpha_value:.4f}")
        except Exception as e:
            log_with_time(f"알파 최적화에 실패하여 기본값을 사용합니다: {e}", "WARN")
            alpha_value = DEFAULT_ALPHA_VALUE
    try:
        alpha_shape = alphashape.alphashape(unique_points, alpha_value)
        return alpha_shape, alpha_value
    except Exception as e:
        log_with_time(f"알파 쉐이프 생성에 실패했습니다: {e}", "ERROR")
        return None, alpha_value


def save_roi_visualization_image_async(camera: Cameras, roi_polygon_points: List[Tuple[float, float]] = None,
                                       new_footprints: List[Tuple[float, float]] = None,
                                       all_roi_points: List[Tuple[float, float]] = None,
                                       roi_calculation_failed: bool = False):
    """[수정] 비동기식 이미지 저장 - ROI 계산 성공 시에도 모든 포인트를 표시하도록 개선"""
    log_prefix = f"[ROI:{camera.camera_id} '{camera.name}']"
    try:
        # 1. 시각화의 배경이 될 최신 스냅샷을 가져옵니다.
        latest_snapshot = Snapshots.objects.filter(camera=camera).latest('captured_at')
        base_path = Path(latest_snapshot.image_path)
        script_dir = Path(__file__).resolve().parent
        image_path = script_dir / base_path if not base_path.is_absolute() else base_path

        if not image_path.exists():
            log_with_time(f"{log_prefix} 배경 이미지를 찾을 수 없습니다: {image_path}", "WARN")
            return

        # 2. 결과 이미지를 저장할 경로를 설정합니다.
        output_dir = script_dir / 'captured' / f'{camera.camera_id}_ROI'
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now().strftime('%y%m%d%H%M%S')

        # 3. 계산 성공/실패에 따라 파일명을 다르게 지정합니다.
        filename_prefix = "roi_points_only" if roi_calculation_failed else "roi_snap"
        output_filename = output_dir / f"{filename_prefix}_{latest_snapshot.snapshot_id}_{timestamp_str}.png"

        with Image.open(image_path).convert("RGBA") as base_image:
            # 4. 원본 이미지 위에 그림을 그릴 투명한 오버레이 레이어를 생성합니다.
            overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # 5. [개선] 계산 성공/실패 여부와 관계없이 누적된 모든 포인트를 먼저 연한 회색으로 그립니다.
            # 이를 통해 데이터가 유실되지 않고 유지되고 있음을 시각적으로 확인할 수 있습니다.
            print(all_roi_points)
            if all_roi_points:
                point_radius = 3
                point_fill = (181, 230, 29, 200)
                # new_footprints에 포함된 점들은 나중에 노란색으로 덮어 그릴 것이므로 먼저 그리지 않습니다.
                points_to_draw = [p for p in all_roi_points if not new_footprints or p not in new_footprints]
                for x, y in points_to_draw:
                    draw.ellipse((x - point_radius, y - point_radius, x + point_radius, y + point_radius),
                                 fill=point_fill)

            # 6. ROI 계산이 성공했을 경우, 파란색으로 ROI 영역을 그립니다.
            if roi_polygon_points and not roi_calculation_failed:
                draw.polygon(roi_polygon_points, fill=(66, 135, 245, 80), outline=(66, 135, 245, 180), width=4)

            # 7. '이번 주기'에 새로 추가된 포인트가 있다면, 눈에 띄는 노란색으로 맨 위에 덮어 그립니다.
            if new_footprints:
                point_radius = 4
                for x, y in new_footprints:
                    draw.ellipse((x - point_radius, y - point_radius, x + point_radius, y + point_radius),
                                 fill=(255, 255, 0, 200), outline=(255, 215, 0, 255), width=2)

            # 8. [생략 없앤 부분] ROI 계산이 실패한 경우, 이미지에 실패 상태 텍스트를 추가합니다.
            if roi_calculation_failed:
                try:
                    # 시스템 기본 폰트를 사용하며, 없을 경우를 대비해 예외 처리를 합니다.
                    font = ImageFont.load_default()
                except OSError:
                    font = None

                status_text = f"ROI 계산 실패 - 포인트 수: {len(all_roi_points) if all_roi_points else 0}"

                # Pillow 10.0.0 이후 버전에서는 textbbox, 이전 버전에서는 textsize를 사용합니다.
                if hasattr(draw, 'textbbox'):
                    text_bbox = draw.textbbox((10, 10), status_text, font=font)
                else:
                    # 구버전 호환성
                    text_width, text_height = draw.textsize(status_text, font=font)
                    text_bbox = (10, 10, 10 + text_width, 10 + text_height)

                # 텍스트 배경을 먼저 그립니다.
                draw.rectangle([text_bbox[0] - 5, text_bbox[1] - 5, text_bbox[2] + 5, text_bbox[3] + 5],
                               fill=(255, 0, 0, 150))
                # 텍스트를 그립니다.
                draw.text((10, 10), status_text, fill=(255, 255, 255, 255), font=font)

            # 9. 원본 이미지와 오버레이 레이어를 합친 후, RGB 모드로 변환하여 저장합니다.
            composited_image = Image.alpha_composite(base_image, overlay)
            composited_image.convert("RGB").save(output_filename, "PNG")
            log_with_time(f"{log_prefix} ROI 시각화 이미지를 저장했습니다: {output_filename}")

    except Snapshots.DoesNotExist:
        log_with_time(f"{log_prefix} 시각화를 위한 스냅샷을 찾을 수 없습니다", "WARN")
    except Exception as e:
        log_with_time(f"{log_prefix} 시각화 이미지 저장 중 오류가 발생했습니다: {e}", "ERROR")

def update_roi_for_camera_service(camera_id: int, new_footprints: List[Tuple[float, float]],
                                  current_task_start_time: timezone.datetime) -> bool:
    """[수정] ROI 업데이트 서비스 - 마지막 처리 시간을 명시적으로 기록"""
    if not SHAPELY_ALPHASHAPE_INSTALLED:
        log_with_time("Shapely/Alphashape를 사용할 수 없습니다", "ERROR")
        return False

    try:
        camera = Cameras.objects.get(camera_id=camera_id)
        log_prefix = f"[ROI:{camera.camera_id} '{camera.name}']"
    except Cameras.DoesNotExist:
        log_with_time(f"카메라를 찾을 수 없습니다: {camera_id}", "ERROR")
        return False

    current_roi_def = ROIDefinitions.objects.filter(camera=camera, is_active=True).first()
    existing_points = []
    if current_roi_def and 'roi_defining_points' in current_roi_def.definition_data:
        existing_points = [tuple(p) for p in current_roi_def.definition_data.get('roi_defining_points', [])]

    log_with_time(f"{log_prefix} 처리 중: 기존 {len(existing_points)}개 + 신규 {len(new_footprints)}개 포인트")

    updated_points = efficient_point_management(existing_points, new_footprints)
    unique_points = list(set(updated_points))

    if len(unique_points) < MIN_POINTS_FOR_ROI:
        log_with_time(f"{log_prefix} ROI 계산을 위한 포인트가 부족합니다 ({len(unique_points)} < {MIN_POINTS_FOR_ROI})")
        save_points_only(camera, current_roi_def, unique_points, log_prefix, current_task_start_time)
        # 시각화 호출 시 모든 포인트를 넘겨줌
        save_roi_visualization_image_async(camera=camera, new_footprints=new_footprints, all_roi_points=unique_points,
                                           roi_calculation_failed=True)
        return False

    roi_calculation_success = False
    new_roi_alpha_shape, alpha_value = calculate_alpha_shape_with_cache(unique_points)

    if new_roi_alpha_shape and isinstance(new_roi_alpha_shape,
                                          (Polygon, MultiPolygon)) and not new_roi_alpha_shape.is_empty:
        roi_calculation_success = True
        if isinstance(new_roi_alpha_shape, Polygon):
            new_vertex_points = list(new_roi_alpha_shape.exterior.coords)
        else:
            main_polygon = max(new_roi_alpha_shape.geoms, key=lambda p: p.area)
            new_vertex_points = list(main_polygon.exterior.coords)

        new_roi_area = new_roi_alpha_shape.area
        # [수정] DB에 저장할 데이터에 마지막 처리 시각을 명시적으로 추가
        roi_definition_data = {
            "type": ROIDefinitionType.DYNAMIC_ALPHA_SHAPE_SLIDING.value,
            "area": new_roi_area,
            "vertices": [{"x": p[0], "y": p[1]} for p in new_vertex_points[:-1]],
            "roi_defining_points": [list(p) for p in unique_points],
            "alpha_value": alpha_value,
            "last_processed_timestamp": current_task_start_time.isoformat()
        }

        with transaction.atomic():
            if current_roi_def:
                current_roi_def.definition_data = roi_definition_data
                current_roi_def.save()
            else:
                ROIDefinitions.objects.create(camera=camera,
                                              definition_type=ROIDefinitionType.DYNAMIC_ALPHA_SHAPE_SLIDING,
                                              definition_data=roi_definition_data, is_active=True, version=1)
            log_with_time(f"{log_prefix} ROI가 업데이트되었습니다 - 면적: {new_roi_area:.2f}, 포인트 수: {len(unique_points)}")

        # [수정] 시각화 호출 시 모든 포인트를 넘겨줌
        save_roi_visualization_image_async(camera=camera, roi_polygon_points=new_vertex_points,
                                           new_footprints=new_footprints, all_roi_points=unique_points,
                                           roi_calculation_failed=False)
    else:
        log_with_time(f"{log_prefix} ROI 계산에 실패했지만, 추후 사용을 위해 {len(unique_points)}개의 포인트를 보존합니다")
        save_points_only(camera, current_roi_def, unique_points, log_prefix, current_task_start_time)
        # [수정] 시각화 호출 시 모든 포인트를 넘겨줌
        save_roi_visualization_image_async(camera=camera, new_footprints=new_footprints, all_roi_points=unique_points,
                                           roi_calculation_failed=True)
    return roi_calculation_success


def save_points_only(camera: Cameras, current_roi_def: Optional[ROIDefinitions],
                     unique_points: List[Tuple[float, float]], log_prefix: str,
                     current_task_start_time: timezone.datetime):
    """[수정] ROI 계산 실패시에도 포인트와 마지막 처리 시각을 저장하는 함수"""
    try:
        with transaction.atomic():
            if current_roi_def:
                current_data = current_roi_def.definition_data.copy()
                current_data['roi_defining_points'] = [list(p) for p in unique_points]
                # [수정] 실패 시에도 마지막 처리 시각을 기록하여 데이터 누락 방지
                current_data['last_processed_timestamp'] = current_task_start_time.isoformat()
                current_roi_def.definition_data = current_data
                current_roi_def.save()
                log_with_time(f"{log_prefix} 기존 ROI 정의에 {len(unique_points)}개의 포인트를 보존했습니다")
            else:
                points_only_data = {
                    "type": ROIDefinitionType.DYNAMIC_ALPHA_SHAPE_SLIDING.value,
                    "roi_defining_points": [list(p) for p in unique_points],
                    "status": "points_only",
                    # [수정] 최초 생성 시에도 마지막 처리 시각 기록
                    "last_processed_timestamp": current_task_start_time.isoformat(),
                    "note": "ROI calculation pending - accumulating points"
                }
                ROIDefinitions.objects.create(camera=camera,
                                              definition_type=ROIDefinitionType.DYNAMIC_ALPHA_SHAPE_SLIDING,
                                              definition_data=points_only_data, is_active=True, version=1)
                log_with_time(f"{log_prefix} {len(unique_points)}개의 포인트를 포함하는 새 ROI 정의를 생성했습니다")
    except Exception as e:
        log_with_time(f"{log_prefix} 포인트 저장에 실패했습니다: {e}", "ERROR")


def get_footprints_from_detected_objects(camera_id: int, start_time: timezone.datetime) -> List[Tuple[float, float]]:
    """[수정] 발자국 데이터 조회 - `start_time` 이후의 모든 데이터를 조회"""
    detected_objects = DetectedObjects.objects.filter(
        snapshot__camera_id=camera_id,
        snapshot__captured_at__gt=start_time,  # [수정] gte(이상) 대신 gt(초과)를 사용하여 중복 방지
        class_label='person'
    ).only('center_x', 'bbox_y', 'bbox_height').order_by('snapshot__captured_at')  # 순서 보장

    footprints = []
    for obj in detected_objects:
        if all(x is not None for x in [obj.center_x, obj.bbox_y, obj.bbox_height]):
            footprints.append((float(obj.center_x), float(obj.bbox_y + obj.bbox_height)))
    return footprints


def update_all_camera_rois_periodic_task():
    """[수정] 주기적 ROI 업데이트 태스크 - 마지막 처리 시점부터 조회하도록 로직 전면 수정"""
    log_with_time(f"주기적 ROI 업데이트를 시작합니다.")

    active_cameras = Cameras.objects.filter(is_active_monitoring=True)
    if not active_cameras.exists():
        log_with_time("활성화된 카메라를 찾을 수 없습니다", "WARN")
        return

    updated_count = 0
    error_count = 0
    total_cameras = active_cameras.count()

    for i, camera in enumerate(active_cameras):
        try:
            log_with_time(f"카메라 처리 중 {i + 1}/{total_cameras}: '{camera.name}' (ID: {camera.camera_id})")

            # [수정] DB에 저장된 마지막 처리 시각을 가져옴
            current_roi_def = ROIDefinitions.objects.filter(camera=camera, is_active=True).first()
            start_time = timezone.now() - timedelta(days=INITIAL_FETCH_DAYS)  # 기본값: 최초 실행 시 N일치 데이터 수집

            if current_roi_def and 'last_processed_timestamp' in current_roi_def.definition_data:
                try:
                    from dateutil.parser import isoparse
                    start_time = isoparse(current_roi_def.definition_data['last_processed_timestamp'])
                except (ValueError, TypeError):
                    log_with_time(f"[ROI:{camera.camera_id}] 저장된 타임스탬프 파싱 오류. 기본값으로 재설정합니다.", "WARN")

            # [추가] 다음 처리를 위해 현재 작업 시작 시간을 기록
            current_task_start_time = timezone.now()

            log_with_time(
                f"[ROI:{camera.camera_id}] '{start_time.strftime('%Y-%m-%d %H:%M:%S')}' 이후의 발자국 데이터 조회를 시작합니다.")
            new_footprints = get_footprints_from_detected_objects(camera.camera_id, start_time)

            if not new_footprints:
                log_with_time(f"[ROI:{camera.camera_id}] 새로운 발자국 데이터를 찾을 수 없습니다.")
                # [추가] 새 데이터가 없더라도, 주기적으로 현재 시간을 기록하여 타임스탬프를 갱신 (선택적)
                # save_points_only(camera, current_roi_def, [], log_prefix, current_task_start_time)
                continue

            log_with_time(f"[ROI:{camera.camera_id}] {len(new_footprints)}개의 새로운 발자국 데이터를 발견하여 업데이트를 시작합니다...")

            # [수정] 업데이트 서비스에 현재 작업 시작 시간도 함께 전달
            if update_roi_for_camera_service(camera.camera_id, new_footprints, current_task_start_time):
                updated_count += 1
            else:
                error_count += 1

        except Exception as e:
            error_count += 1
            log_with_time(f"카메라 {camera.camera_id} 처리 중 심각한 오류가 발생했습니다: {e}", "ERROR")

    log_with_time("-" * 80)
    log_with_time(f"ROI 업데이트 완료: 총 {total_cameras}대의 카메라 중 {updated_count}대 성공, {error_count}대 오류")