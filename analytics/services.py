import os
from django.utils import timezone
from django.db import transaction
from django_q.tasks import async_task

from .models import (
    Snapshots,
    DetectedObjects,
    CongestionEvents,
    ROIDefinitions,
    Cameras,
    CongestionLevelLabel,
    ProcessingStatus,
    ROIDefinitionType
)
from .ai_models.yolo_detector import detect_objects
from typing import Optional, Tuple, Dict, List
from django.conf import settings
from PIL import Image, ImageDraw

# --- Constants ---
MIN_DETECTION_CONFIDENCE = 0.6
CONGESTION_CALCULATION_R_RATIO = 0.05
CONGESTION_THRESHOLDS = {
    CongestionLevelLabel.LOW: 0.1,
    CongestionLevelLabel.MEDIUM: 0.35,
    CongestionLevelLabel.HIGH: 0.6
}


# --- [수정] 로그 함수를 파일 상단으로 이동 ---
def log_with_time(message):
    """현재 시간과 함께 로그 메시지를 출력합니다."""
    from django.utils.timezone import localtime, now
    print(f"[{localtime(now()).strftime('%H:%M:%S.%f')[:-3]}] {message}")


def get_active_roi_for_camera(camera: Cameras) -> Optional[Dict]:
    """주어진 카메라에 대해 현재 활성화된 ROI 정의를 가져옵니다."""
    active_roi_def = ROIDefinitions.objects.filter(
        camera=camera,
        is_active=True
    ).order_by('-updated_at').first()

    if active_roi_def and active_roi_def.definition_data:
        return active_roi_def.definition_data
    return None


def calculate_footprint_areas(detected_objects: List[DetectedObjects], r_ratio: float) -> Tuple[float, List[float]]:
    """탐지된 객체들의 '발 부분 면적' 추정치의 합계와 개별 면적 리스트를 계산합니다."""
    total_area = 0.0
    individual_areas = []
    for obj in detected_objects:
        if obj.class_label == 'person' and obj.bbox_width > 0 and obj.bbox_height > 0:
            slice_height = max(1.0, float(obj.bbox_height) * r_ratio)
            area_foot_i = float(obj.bbox_width) * slice_height
            total_area += area_foot_i
            individual_areas.append(round(area_foot_i, 2))

    return total_area, individual_areas


def determine_congestion_level(congestion_value_raw: float) -> CongestionLevelLabel:
    """계산된 원시 밀집도 값(congestion_value_raw)을 바탕으로 혼잡도 수준을 결정합니다."""
    if congestion_value_raw < CONGESTION_THRESHOLDS[CongestionLevelLabel.LOW]:
        return CongestionLevelLabel.LOW
    elif congestion_value_raw < CONGESTION_THRESHOLDS[CongestionLevelLabel.MEDIUM]:
        return CongestionLevelLabel.MEDIUM
    elif congestion_value_raw < CONGESTION_THRESHOLDS[CongestionLevelLabel.HIGH]:
        return CongestionLevelLabel.HIGH
    else:
        return CongestionLevelLabel.VERY_HIGH


@transaction.atomic
def calculate_and_save_congestion_event(snapshot_id: int) -> Optional[CongestionEvents]:
    """주어진 스냅샷 ID에 대해 혼잡도를 계산하고, 결과를 CongestionEvents에 저장하며, 상세 로그를 출력합니다."""
    log_prefix = f"[CONG-TASK|S-ID:{snapshot_id}]"
    log_with_time(f">> {log_prefix} 밀집도 분석 시작")

    try:
        snapshot = Snapshots.objects.select_related('camera').get(snapshot_id=snapshot_id)
    except Snapshots.DoesNotExist:
        log_with_time(f"[ERROR] {log_prefix} Snapshot을 찾을 수 없습니다.")
        return None

    if snapshot.processing_status_congestion == ProcessingStatus.COMPLETED:
        log_with_time(f"[INFO] {log_prefix} 이미 처리가 완료되어 건너뜁니다.")
        return None
    if snapshot.processing_status_ai != ProcessingStatus.COMPLETED:
        log_with_time(f"[WARN] {log_prefix} AI 분석이 완료되지 않아 대기합니다. (현재 상태: {snapshot.processing_status_ai})")
        snapshot.processing_status_congestion = ProcessingStatus.FAILED
        snapshot.save()
        return None

    camera = snapshot.camera
    detected_objects = list(DetectedObjects.objects.filter(snapshot=snapshot, class_label='person'))
    person_count = len(detected_objects)
    log_prefix_cam = f"[CONG-TASK|S-ID:{snapshot_id}|CAM:{camera.camera_id}]"  # 카메라 ID 추가

    active_roi_data = get_active_roi_for_camera(camera)
    if not active_roi_data or 'area' not in active_roi_data or active_roi_data['area'] <= 0:
        log_with_time(f"[ERROR] {log_prefix_cam} 유효한 ROI가 없어 계산을 중단합니다.")
        snapshot.processing_status_congestion = ProcessingStatus.FAILED
        snapshot.save()
        return None

    estimated_roi_pixel_area = float(active_roi_data['area'])
    total_footprint_area_sum, individual_areas = calculate_footprint_areas(detected_objects,
                                                                           CONGESTION_CALCULATION_R_RATIO)

    congestion_value_raw = total_footprint_area_sum / estimated_roi_pixel_area if estimated_roi_pixel_area > 0 else 0.0
    congestion_level = determine_congestion_level(congestion_value_raw)
    alert_triggered = congestion_level in [CongestionLevelLabel.HIGH, CongestionLevelLabel.VERY_HIGH]

    congestion_event = CongestionEvents.objects.create(
        camera=camera, snapshot=snapshot, event_timestamp=snapshot.captured_at, person_count=person_count,
        estimated_roi_pixel_area=estimated_roi_pixel_area, congestion_value_raw=congestion_value_raw,
        congestion_level=congestion_level, alert_triggered=alert_triggered, is_acknowledged=False,
    )

    snapshot.processing_status_congestion = ProcessingStatus.COMPLETED
    snapshot.save(update_fields=['processing_status_congestion'])

    # --- [수정] 상세 결과 로그를 새로운 포맷으로 출력 ---
    log_with_time(f"{log_prefix_cam} ├─ [결과] 최종 밀집도: {congestion_level.label} ({congestion_value_raw:.4f})")
    log_with_time(f"{log_prefix_cam} ├─ [결과] 탐지된 사람 수: {person_count}명")
    log_with_time(f"{log_prefix_cam} ├─ [결과] 사용된 ROI 면적: {estimated_roi_pixel_area:,.2f} 픽셀")
    log_with_time(f"{log_prefix_cam} └─ [결과] 객체별 추정 면적 (상위 5개): {individual_areas[:5]}")
    log_with_time(f"{log_prefix_cam} └─ [결과] 모든 객체 면적의 합: {total_footprint_area_sum:.5f} 픽셀")
    log_with_time(f"<< {log_prefix_cam} 밀집도 분석 완료 (Event ID: {congestion_event.event_id})")

    return congestion_event


def analyze_snapshot_task(snapshot_id):
    """주어진 스냅샷에 대해 AI 객체 탐지를 수행하는 비동기 작업입니다."""
    snapshot = None
    log_prefix = f"[AI-TASK|S-ID:{snapshot_id}]"
    try:
        log_with_time(f">> {log_prefix} AI 분석 시작")
        snapshot = Snapshots.objects.get(pk=snapshot_id)

        snapshot.processing_status_ai = "PROCESSING"
        snapshot.save(update_fields=['processing_status_ai'])

        image_path = snapshot.image_path
        if not os.path.isabs(image_path):
            image_path = os.path.join(settings.MEDIA_ROOT, image_path)

        log_with_time(f"{log_prefix} ├─ 객체 탐지 실행: {os.path.basename(image_path)}")
        all_detections = detect_objects(image_path)
        log_with_time(f"{log_prefix} ├─ > 총 {len(all_detections)}개 객체 원본 탐지 완료")

        # --- [수정] 신뢰도(confidence)가 MIN_DETECTION_CONFIDENCE 이상인 객체만 필터링합니다. ---
        detections = [
            det for det in all_detections
            if det.get("confidence", 0) >= MIN_DETECTION_CONFIDENCE
        ]
        num_detections = len(detections)
        log_with_time(f"{log_prefix} ├─ > 신뢰도 {MIN_DETECTION_CONFIDENCE} 이상 유효 객체: {num_detections}개")
        # --- 수정 끝 ---


        if num_detections > 0:
            log_with_time(f"{log_prefix} ├─ 탐지된 객체 정보 DB 저장 중...")
            # 이제 필터링된 'detections' 리스트를 사용합니다.
            for det in detections:
                DetectedObjects.objects.create(
                    snapshot=snapshot, class_label=det["label"], confidence=det["confidence"],
                    bbox_x=det["bbox_x"], bbox_y=det["bbox_y"], bbox_width=det["bbox_width"],
                    bbox_height=det["bbox_height"], center_x=det["center_x"], center_y=det["center_y"]
                )
            log_with_time(f"{log_prefix} ├─ > DB 저장 완료")

        log_with_time(f"{log_prefix} ├─ 처리된 이미지 생성 및 저장 중...")
        image = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(image)
        # 처리된 이미지에도 필터링된 'detections'만 그립니다.
        for det in detections:
            x, y, w, h = det["bbox_x"], det["bbox_y"], det["bbox_width"], det["bbox_height"]
            label = f"{det['label']} ({det['confidence']:.2f})"
            draw.rectangle([x, y, x + w, y + h], outline="red", width=2)
            text_bbox = draw.textbbox((x, y - 10), label)
            draw.rectangle(text_bbox, fill="red")
            draw.text((x, y - 10), label, fill="yellow")

        base_dir = os.path.dirname(os.path.abspath(__file__))  # 현재 파일 기준 디렉토리
        output_dir = os.path.join(base_dir, "processed_image", f"camera_{snapshot.camera.camera_id}")
        os.makedirs(output_dir, exist_ok=True)

        output_filename = f"snap_{snapshot.snapshot_id}_bbox.jpg"
        output_path = os.path.join(output_dir, output_filename)
        image.save(output_path)
        log_with_time(f"{log_prefix} ├─ > 처리된 이미지 저장 완료: {output_filename}")

        # DB에는 상대경로 저장 (예: processed_image/camera_1/snap_123_bbox.jpg)
        snapshot.processed_image_path = os.path.relpath(output_path, base_dir)
        snapshot.processing_status_ai = "COMPLETED"
        snapshot.analyzed_at_ai = timezone.now()
        snapshot.save()

        log_with_time(f"{log_prefix} ├─ [TASK] 다음 단계 (밀집도 분석) 비동기 작업 등록")
        async_task(
            'analytics.services.calculate_and_save_congestion_event',  # 경로 수정 가능성 고려
            snapshot.snapshot_id,
            q_options={'group': f'congestion-analysis-{snapshot.camera.camera_id}'}
        )

        log_with_time(f"<< {log_prefix} AI 분석 완료")

        return {"snapshot_id": snapshot.snapshot_id, "num_detected_objects": num_detections}

    except Exception as e:
        log_with_time(f"[ERROR] {log_prefix} AI 분석 실패: {e}")
        if snapshot:
            snapshot.processing_status_ai = "FAILED"
            snapshot.save()
        raise e