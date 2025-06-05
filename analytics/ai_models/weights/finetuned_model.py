import gdown
from ultralytics import YOLO

# 모델 파일 다운로드
file_id = "1abcD1234EfGhi567JKlMn89pq"
url = "https://drive.google.com/uc?id=1u2uWFxbRw8BzopIJaydzvEtH5pB4iRLt"
gdown.download(url, "best.pt", quiet=False)










