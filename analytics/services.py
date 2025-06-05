import os
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from PIL import Image, ImageDraw

from analytics.models import Snapshots, DetectedObjects
from analytics.ai_models.yolo_detector import detect_objects


@shared_task
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
