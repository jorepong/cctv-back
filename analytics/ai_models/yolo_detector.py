import os
import cv2
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from ultralytics import YOLO

from pathlib import Path
from matplotlib.backend_bases import KeyEvent

# 경로 설정
capture_dir = Path("captures")
labeled_dir = Path("labeled")
labeled_dir.mkdir(exist_ok=True)


# 모델 로드
model = YOLO('yolo11x.pt')

# 처리 대상 이미지 필터링
def get_unprocessed_images():
    all_images = sorted(
        list(capture_dir.glob("snap_*.png")) +
        list(capture_dir.glob("snap_*.jpg"))
    )
    processed_names = {img.name.replace("_labeled", "") for img in labeled_dir.glob("snap_*_labeled.*")}
    return [img for img in all_images if img.name not in processed_names]
# 글로벌 변수
annotations = []
drawn_boxes = []
start_point = []
current_image = None
current_image_path = None

# 시각화 함수
def draw_annotations(ax, fig, image):
    global drawn_boxes
    for patch in drawn_boxes:
        patch.remove()
    drawn_boxes.clear()

    ax.clear()
    ax.imshow(image)

    for ann in annotations:
        x1, y1, x2, y2 = ann['box']
        label = ann['label']
        rect = patches.Rectangle((x1, y1), x2 - x1, y2 - y1,
                                 linewidth=2, edgecolor='g', facecolor='none')
        ax.add_patch(rect)
        ax.text(x1, y1 - 5, label, color='green', fontsize=9)
        drawn_boxes.append(rect)
    fig.canvas.draw()

# 바운딩 박스 선택
def get_box_index_at(x, y):
    for i, ann in enumerate(annotations):
        x1, y1, x2, y2 = ann['box']
        if x1 <= x <= x2 and y1 <= y <= y2:
            return i
    return None

# 마우스 이벤트
def on_click(event):
    if event.inaxes is None:
        return
    if event.button == 1:  # 왼쪽 클릭 → 드래그 시작
        start_point.clear()
        start_point.append((event.xdata, event.ydata))
    elif event.button == 3:  # 오른쪽 클릭 → 삭제
        idx = get_box_index_at(event.xdata, event.ydata)
        if idx is not None:
            del annotations[idx]
            draw_annotations(ax, fig, current_image)
    elif event.button == 2:  # 가운데 클릭 → 라벨 토글
        idx = get_box_index_at(event.xdata, event.ydata)
        if idx is not None:
            current = annotations[idx]['label']
            annotations[idx]['label'] = 'unknown' if current == 'person' else 'person'
            draw_annotations(ax, fig, current_image)

def on_release(event):
    if event.inaxes is None or not start_point or event.button != 1:
        return
    x1, y1 = start_point[0]
    x2, y2 = event.xdata, event.ydata
    new_box = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
    annotations.append({'box': new_box, 'label': 'person'})
    draw_annotations(ax, fig, current_image)

# 키 입력 처리
def on_key(event: KeyEvent):
    if event.key == 'enter':
        save_labeled_data()
        plt.close()

# 결과 저장
def save_labeled_data():
    if current_image_path is None:
        return

    # 이미지 확장자 유지 (예: .png → .png, .jpg → .jpg)
    ext = current_image_path.suffix.lower()
    filename = current_image_path.stem + "_labeled" + ext
    output_path = labeled_dir / filename

    # 이미지 저장
    cv2.imwrite(str(output_path), cv2.cvtColor(current_image, cv2.COLOR_RGB2BGR))
    print(f"✅ 이미지 저장됨: {output_path.name}")

    # 라벨 저장 (YOLO 포맷, .txt 확장자)
    label_txt_path = labeled_dir / (current_image_path.stem + "_labeled.txt")
    h, w, _ = current_image.shape
    with open(label_txt_path, 'w') as f:
        for ann in annotations:
            x1, y1, x2, y2 = ann['box']
            cx = ((x1 + x2) / 2) / w
            cy = ((y1 + y2) / 2) / h
            bw = (x2 - x1) / w
            bh = (y2 - y1) / h
            f.write(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")


# 메인 루프
images_to_process = get_unprocessed_images()
print(f"처리할 이미지 수: {len(images_to_process)}")

for image_path in images_to_process:
    print(f"\n[검수 시작] {image_path.name}")
    current_image_path = image_path
    img_bgr = cv2.imread(str(image_path))
    current_image = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    # YOLO 예측
    results = model.predict(source=current_image, conf=0.1, iou=0.4, classes=[0], agnostic_nms=True)
    boxes = results[0].boxes.xyxy.cpu().numpy()
    annotations = [{'box': box.tolist(), 'label': 'person'} for box in boxes]

    # 시각화
    fig, ax = plt.subplots()
    fig.canvas.mpl_connect('button_press_event', on_click)
    fig.canvas.mpl_connect('button_release_event', on_release)
    fig.canvas.mpl_connect('key_press_event', on_key)

    draw_annotations(ax, fig, current_image)
    plt.title(f"{image_path.name} - Enter 키로 저장")
    plt.show()
