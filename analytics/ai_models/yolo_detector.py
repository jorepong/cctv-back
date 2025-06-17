# analytics/ai_models/yolo_detector.py
import os

import torch
from PIL import Image
import numpy as np
from ultralytics import YOLO

# 전역 모델 캐싱용 변수
model = None


def load_model(weights_path="weights/best.pt"):
    global model
    if model is None:
        # 절대 경로 변환
        base_dir = os.path.dirname(__file__)  # analytics/ai_models/
        abs_path = os.path.join(base_dir, weights_path)  # weights 폴더가 ai_models 하위에 있다고 가정

        # YOLO 모델 로드 (구조 + 가중치 포함된 .pt 파일)
        model = YOLO(abs_path)
        model.conf = 0.15
        model.iou = 0.5
        print(f"✅ YOLO 모델 로딩 완료: {abs_path}")
    return model


# 이미지 분석 함수
def detect_objects(image_path):
    model = load_model()
    image = Image.open(image_path).convert("RGB")
    results = model(image)

    detections = []

    # --- 🔽 [수정] 데이터 추출 방식을 최신 라이브러리에 맞게 변경합니다. ---
    if results and results[0]:
        # results 리스트의 첫 번째 결과 객체를 가져옵니다.
        result_data = results[0]

        # .boxes 속성을 통해 모든 탐지된 박스 정보에 접근합니다.
        # .data는 [x1, y1, x2, y2, confidence, class] 형태의 텐서를 포함합니다.
        for row in result_data.boxes.data.tolist():
            # row에서 각 정보를 추출합니다.
            x1, y1, x2, y2, conf, cls = row

            label = model.names[int(cls)]
            if label != "person":
                continue

            # 정수형으로 변환하여 detections 리스트에 추가합니다.
            detections.append({
                "label": label,
                "confidence": conf,
                "bbox_x": int(x1),
                "bbox_y": int(y1),
                "bbox_width": int(x2 - x1),
                "bbox_height": int(y2 - y1),
                "center_x": int((x1 + x2) / 2),
                "center_y": int((y1 + y2) / 2)
            })
    # --- 🔼 [수정] 여기까지 변경 ---

    return detections
