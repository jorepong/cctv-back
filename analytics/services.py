# analytics/services.py

import os
from django.utils import timezone
from django.db import transaction
from .models import (
    Snapshots,
    DetectedObjects,
    CongestionEvents,
    ROIDefinitions,
    Cameras,
    CongestionLevelLabel,
    ProcessingStatus,
    ROIDefinitionType  # ROIDefinitions에서 사용
)
from .ai_models.yolo_detector import detect_objects
from typing import Optional, Tuple, Dict, List
from django.conf import settings
from PIL import Image, ImageDraw

# --- Constants ---
# 이 값은 프로젝트 설정이나 DB에서 가져오도록 개선할 수 있습니다.
CONGESTION_CALCULATION_R_RATIO = 0.05  # 아이디어 3의 R 값 (바운딩 박스 높이 비례 슬라이스)

# 혼잡도 수준 판정 임계값 (실제 값은 데이터 기반 튜닝 필요)
CONGESTION_THRESHOLDS = {
    CongestionLevelLabel.LOW: 0.1,
    CongestionLevelLabel.MEDIUM: 0.3,
    CongestionLevelLabel.HIGH: 0.6,
    # VERY_HIGH는 HIGH 임계값 초과 시
}


def get_active_roi_for_camera(camera: Cameras) -> Optional[Dict]:
    """
    주어진 카메라에 대해 현재 활성화된 ROI 정의를 가져옵니다.
    ROIDefinitions 테이블에서 is_active=True인 가장 최근의 정의를 반환합니다.

    Args:
        camera: Cameras 모델 객체

    Returns:
        활성 ROI의 definition_data (딕셔셔리 형태) 또는 None (활성 ROI가 없는 경우)
    """
    active_roi_def = ROIDefinitions.objects.filter(
        camera=camera,
        is_active=True
    ).order_by('-updated_at').first()  # 가장 최근에 업데이트된 활성 ROI

    if active_roi_def and active_roi_def.definition_data:
        return active_roi_def.definition_data
    return None


def calculate_total_footprint_area(detected_objects: List[DetectedObjects], r_ratio: float) -> float:
    """
    탐지된 객체들(사람)의 '발 부분 면적' 추정치의 합계를 계산합니다.
    '발 부분 면적'은 아이디어 3 (바운딩 박스 높이 비례 슬라이스) 방식을 따릅니다.
    Area_foot_i = bbox_width_i * max(1, bbox_height_i * R)

    Args:
        detected_objects: DetectedObjects 모델 객체 리스트 (사람 객체들)
        r_ratio: 바운딩 박스 높이에 곱해지는 비율 R

    Returns:
        모든 탐지된 사람 객체들의 추정 발 부분 면적 합계 (float)
    """
    total_area = 0.0
    for obj in detected_objects:
        if obj.class_label == 'person' and obj.bbox_width > 0 and obj.bbox_height > 0:
            # 각 객체의 발 부분 면적 추정
            # slice_height = max(1, obj.bbox_height * r_ratio) # 최소 1픽셀 보장
            # area_foot_i = obj.bbox_width * slice_height

            # 아이디어 3의 의미: "각 객체의 기여도는 ≈ R * (해당 객체의 전체 바운딩 박스 면적)"
            # 따라서, (모든 사람의 전체 바운딩 박스 픽셀 면적의 합) * R 로 계산 가능
            # 여기서는 문서에 나온 식을 최대한 따르겠습니다.
            slice_height = max(1.0, float(obj.bbox_height) * r_ratio)  # 부동소수점 연산 명시
            area_foot_i = float(obj.bbox_width) * slice_height
            total_area += area_foot_i
    return total_area


def determine_congestion_level(congestion_value_raw: float) -> CongestionLevelLabel:
    """
    계산된 원시 밀집도 값(congestion_value_raw)을 바탕으로 혼잡도 수준을 결정합니다.

    Args:
        congestion_value_raw: 계산된 원시 밀집도 값.

    Returns:
        CongestionLevelLabel Enum 값 (LOW, MEDIUM, HIGH, VERY_HIGH)
    """
    if congestion_value_raw < CONGESTION_THRESHOLDS[CongestionLevelLabel.LOW]:
        return CongestionLevelLabel.LOW
    elif congestion_value_raw < CONGESTION_THRESHOLDS[CongestionLevelLabel.MEDIUM]:
        return CongestionLevelLabel.MEDIUM
    elif congestion_value_raw < CONGESTION_THRESHOLDS[CongestionLevelLabel.HIGH]:
        return CongestionLevelLabel.HIGH
    else:
        return CongestionLevelLabel.VERY_HIGH


@transaction.atomic  # DB 작업을 하나의 트랜잭션으로 묶어 데이터 정합성 보장
def calculate_and_save_congestion_event(snapshot_id: int) -> Optional[CongestionEvents]:
    """
    주어진 스냅샷 ID에 대해 혼잡도(밀집도)를 계산하고, 그 결과를 CongestionEvents 테이블에 저장합니다.

    이 함수는 다음 단계를 수행합니다:
    1. 스냅샷 정보 및 관련 데이터(카메라, 탐지된 객체들)를 조회합니다.
    2. 해당 카메라의 활성화된 ROI 정보를 가져옵니다. (ROI 면적 필요)
    3. 탐지된 사람 객체 수를 집계합니다.
    4. "밀집도 추정 방식 고도화 논의" (아이디어 3)에 따라 원시 밀집도 값을 계산합니다.
       - 밀집도_raw = (탐지된 모든 사람의 발 부분 면적 추정치 합) / (ROI 픽셀 면적)
    5. 계산된 원시 밀집도 값을 바탕으로 혼잡도 수준(LOW, MEDIUM, HIGH, VERY_HIGH)을 판정합니다.
    6. 위 정보를 포함하여 CongestionEvents 레코드를 생성하고 데이터베이스에 저장합니다.
    7. 해당 Snapshots 레코드의 밀집도 분석 상태(processing_status_congestion)를 업데이트합니다.
    8. 특정 수준 이상의 혼잡도 발생 시 알림 트리거 플래그(alert_triggered)를 설정합니다.

    Args:
        snapshot_id: 분석할 스냅샷의 고유 ID.

    Returns:
        성공적으로 생성된 CongestionEvents 객체 또는 실패/조건 미충족 시 None.
    """
    try:
        snapshot = Snapshots.objects.select_related('camera').get(snapshot_id=snapshot_id)
    except Snapshots.DoesNotExist:
        print(f"[Congestion Service] Snapshot ID {snapshot_id}를 찾을 수 없습니다.")
        return None

    # 이미 밀집도 분석이 완료되었거나 AI 분석이 완료되지 않은 경우 중복 처리 방지
    if snapshot.processing_status_congestion == ProcessingStatus.COMPLETED:
        print(f"[Congestion Service] Snapshot ID {snapshot_id}는 이미 밀집도 분석이 완료되었습니다.")
        return None  # 이미 처리된 경우 다시 처리하지 않음 (또는 기존 이벤트 반환)
    if snapshot.processing_status_ai != ProcessingStatus.COMPLETED:
        print(f"[Congestion Service] Snapshot ID {snapshot_id}의 AI 분석이 완료되지 않았습니다. 밀집도 분석을 진행할 수 없습니다.")
        snapshot.processing_status_congestion = ProcessingStatus.FAILED  # AI 분석 선행 필요
        snapshot.save()
        return None

    camera = snapshot.camera
    detected_objects = list(DetectedObjects.objects.filter(snapshot=snapshot, class_label='person'))
    person_count = len(detected_objects)

    # 활성 ROI 정보 가져오기
    active_roi_data = get_active_roi_for_camera(camera)
    if not active_roi_data or 'area' not in active_roi_data or active_roi_data['area'] <= 0:
        print(f"[Congestion Service] 카메라 ID {camera.camera_id}에 유효한 활성 ROI 면적 정보가 없습니다. 밀집도 계산 불가.")
        snapshot.processing_status_congestion = ProcessingStatus.FAILED
        snapshot.save()
        return None

    estimated_roi_pixel_area = float(active_roi_data['area'])

    # 원시 밀집도 값 계산 (아이디어 3 기반)
    total_footprint_area_sum = calculate_total_footprint_area(detected_objects, CONGESTION_CALCULATION_R_RATIO)

    congestion_value_raw = 0.0
    if estimated_roi_pixel_area > 0:  # ROI 면적이 0보다 클 때만 계산
        congestion_value_raw = total_footprint_area_sum / estimated_roi_pixel_area

    # 혼잡도 수준 판정
    congestion_level = determine_congestion_level(congestion_value_raw)

    # 알림 발생 여부 결정
    alert_triggered = congestion_level in [CongestionLevelLabel.HIGH, CongestionLevelLabel.VERY_HIGH]

    # CongestionEvents 객체 생성 및 저장
    # event_timestamp는 스냅샷 캡처 시각을 사용하는 것이 일반적입니다.
    event_timestamp = snapshot.captured_at

    # 과거 데이터 비교 로직은 1학기 범위에서는 생략하거나 단순화 가능 (예: 이 필드는 2학기용)
    # comparison_historical_avg_count = get_historical_average_for_comparison(camera, event_timestamp)

    congestion_event = CongestionEvents.objects.create(
        camera=camera,
        snapshot=snapshot,
        event_timestamp=event_timestamp,
        person_count=person_count,
        estimated_roi_pixel_area=estimated_roi_pixel_area,  # 실제 사용된 ROI 면적
        congestion_value_raw=congestion_value_raw,
        congestion_level=congestion_level,
        # comparison_historical_avg_count=comparison_historical_avg_count, # 2학기 구현 또는 Null
        alert_triggered=alert_triggered,
        is_acknowledged=False,  # 초기값은 미확인
        # acknowledged_at = None # 초기값
    )

    # Snapshot의 밀집도 분석 상태 업데이트
    snapshot.processing_status_congestion = ProcessingStatus.COMPLETED
    snapshot.save(update_fields=['processing_status_congestion'])

    print(
        f"[Congestion Service] Snapshot ID {snapshot_id}의 혼잡도 분석 완료. Event ID: {congestion_event.event_id}, Level: {congestion_level}")
    return congestion_event

# (선택적) 과거 데이터 비교 함수 예시 (2학기 고도화 내용)
# def get_historical_average_for_comparison(camera: Cameras, current_timestamp: timezone.datetime) -> Optional[int]:
#     # 예: 지난 주 같은 요일, 같은 시간대의 평균 인원 수 조회 로직
#     # 이 부분은 실제 데이터와 요구사항에 따라 복잡하게 구현될 수 있습니다.
#     return None

def analyze_snapshot_task(snapshot_id):
    try:
        snapshot = Snapshots.objects.get(pk=snapshot_id)
        snapshot.processing_status_ai = "PROCESSING"
        snapshot.save()

        # 원본 이미지 경로
        image_path = snapshot.image_path
        if not os.path.isabs(image_path):
            image_path = os.path.join(settings.MEDIA_ROOT, image_path)

        # 1. 객체 탐지
        detections = detect_objects(image_path)

        # 2. DetectedObjects 테이블에 객체 하나씩 저장
        for det in detections:
            DetectedObjects.objects.create(
                snapshot=snapshot,
                class_label=det["label"],
                confidence=det["confidence"],
                bbox_x=det["bbox_x"],
                bbox_y=det["bbox_y"],
                bbox_width=det["bbox_width"],
                bbox_height=det["bbox_height"],
                center_x=det["center_x"],
                center_y=det["center_y"]
            )

        # 3. 바운딩 박스 그리기 및 이미지 저장
        image = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(image)

        for det in detections:
            x, y = det["bbox_x"], det["bbox_y"]
            w, h = det["bbox_width"], det["bbox_height"]
            label = f"{det['label']} ({det['confidence']:.2f})"
            draw.rectangle([x, y, x + w, y + h], outline="red", width=2)
            draw.text((x, y - 10), label, fill="yellow")

        # 저장 경로 설정
        output_dir = os.path.join(settings.MEDIA_ROOT, "processed_snapshots", f"camera{snapshot.camera.camera_id}")
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"snap{snapshot.snapshot_id}_bbox.jpg"
        output_path = os.path.join(output_dir, output_filename)

        image.save(output_path)

        # 4. Snapshots 테이블 업데이트 (객체는 DetectedObjects에 저장함!)
        snapshot.processed_image_path = os.path.relpath(output_path, settings.MEDIA_ROOT)
        snapshot.processing_status_ai = "COMPLETED"
        snapshot.analyzed_at_ai = timezone.now()
        snapshot.save()

        return {
            "snapshot_id": snapshot.snapshot_id,
            "num_detected_objects": len(detections)
        }

    except Exception as e:
        if snapshot:
            snapshot.processing_status_ai = "FAILED"
            snapshot.save()
        raise e