# analytics/ai_models/yolo_detector.py
import torch
from PIL import Image
import numpy as np

# 전역 모델 캐싱용 변수
model = None


# 모델 로딩 함수
def load_model(weights_path="analytics/ai_models/weights/best.pt"):
    global model
    if model is None:
        model = torch.hub.load("ultralytics/yolo11x.pt", "custom", path=weights_path)
        model.conf = 0.15  # confidence threshold
        model.iou = 0.5  # optional: NMS IOU threshold
    return model


# 이미지 분석 함수
def detect_objects(image_path):
    model = load_model()
    image = Image.open(image_path).convert("RGB")
    results = model(image)

    detections = []
    for *xyxy, conf, cls in results.xyxy[0].tolist():
        label = model.names[int(cls)]
        if label != "person":
            continue
        x1, y1, x2, y2 = map(int, xyxy)
        detections.append({
            "label": label,
            "confidence": conf,
            "bbox_x": x1,
            "bbox_y": y2,
            "bbox_width": x2 - x1,
            "bbox_height": y2 - y1,
            "center_x": (x1 + x2) // 2,
            "center_y": (y1 + y2) // 2
        })
    return detections
