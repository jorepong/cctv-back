# models.py

from django.db import models
from django.utils import timezone # now()를 직접 사용하기보다는 Django의 timezone 사용

# --- Enum 값들을 위한 Choices 정의 ---

class CameraStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', '활성'
    INACTIVE = 'INACTIVE', '비활성'
    ERROR = 'ERROR', '오류'

class CameraSourceType(models.TextChoices):
    TESTBED = 'TESTBED', '테스트베드'
    WONWOO_REMOTE = 'WONWOO_REMOTE', '원우 리모트' # 예시, 실제 값에 맞게 조정
    YOUTUBE_LIVE = 'YOUTUBE_LIVE', '유튜브 라이브' # 예시

class ProcessingStatus(models.TextChoices):
    PENDING = 'PENDING', '대기 중'
    PROCESSING = 'PROCESSING', '처리 중'
    COMPLETED = 'COMPLETED', '완료됨'
    FAILED = 'FAILED', '실패'

class CongestionLevel(models.TextChoices):
    LOW = 'LOW', '낮음'
    MEDIUM = 'MEDIUM', '중간'
    HIGH = 'HIGH', '높음'
    VERY_HIGH = 'VERY_HIGH', '매우 높음' # 또는 '주의', '혼잡' 등
    # KOREAN_LOW = '주의', '주의'
    # KOREAN_MEDIUM = '혼잡', '혼잡'
    # KOREAN_HIGH = '매우혼잡', '매우 혼잡'

class ROIDefinitionType(models.TextChoices):
    MANUAL_POLYGON = 'MANUAL_POLYGON', '수동 폴리곤'
    DYNAMIC_CONVEX_HULL = 'DYNAMIC_CONVEX_HULL', '동적 컨벡스헐'
    MOTION_PATTERN_BASED = 'MOTION_PATTERN_BASED', '움직임 패턴 기반'


# --- 모델 정의 ---

class Cameras(models.Model):
    camera_id = models.AutoField(primary_key=True, help_text='카메라 고유 ID')
    name = models.CharField(max_length=255, help_text='카메라 이름 (예: 신공학관 9층 엘리베이터 앞)')
    rtsp_url = models.CharField(max_length=512, null=True, blank=True, help_text='RTSP 스트리밍 URL (외부 CCTV용)')
    source_type = models.CharField(
        max_length=50,
        choices=CameraSourceType.choices,
        default=CameraSourceType.TESTBED,
        help_text='카메라 소스 타입'
    )
    location_description = models.TextField(null=True, blank=True, help_text='설치 위치 상세 설명')
    resolution_width = models.IntegerField(null=True, blank=True, help_text='해상도 너비')
    resolution_height = models.IntegerField(null=True, blank=True, help_text='해상도 높이')
    status = models.CharField(
        max_length=20,
        choices=CameraStatus.choices,
        default=CameraStatus.ACTIVE,
        help_text='카메라 상태'
    )
    is_active_monitoring = models.BooleanField(default=True, help_text='현재 모니터링(분석) 대상 여부')
    created_at = models.DateTimeField(auto_now_add=True, help_text='레코드 생성 시각')
    updated_at = models.DateTimeField(auto_now=True, help_text='레코드 수정 시각')

    def __str__(self):
        return f"{self.name} (ID: {self.camera_id})"

    class Meta:
        verbose_name = '카메라'
        verbose_name_plural = '카메라 목록'
        ordering = ['-created_at']
        db_table = 'Cameras' # 스키마에 명시된 테이블 이름 사용


class Snapshots(models.Model):
    snapshot_id = models.BigAutoField(primary_key=True, help_text='스냅샷 고유 ID')
    camera = models.ForeignKey(
        Cameras,
        on_delete=models.CASCADE, # 카메라 삭제 시 관련 스냅샷도 삭제 (정책에 따라 PROTECT 등 변경 가능)
        help_text='촬영된 카메라 ID'
        # db_column='camera_id' # Django는 camera_id로 자동 생성하므로 명시적 지정 불필요
    )
    captured_at = models.DateTimeField(help_text='스냅샷 캡처 시각')
    image_path = models.CharField(max_length=512, help_text='저장된 이미지 파일 경로 (서버 내 경로)')
    processing_status_ai = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        help_text='AI 분석 처리 상태'
    )
    processing_status_congestion = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        help_text='밀집도 계산 처리 상태'
    )
    analyzed_at_ai = models.DateTimeField(null=True, blank=True, help_text='AI 분석 완료 시각')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Snapshot {self.snapshot_id} for Camera {self.camera_id} at {self.captured_at}"

    class Meta:
        verbose_name = '스냅샷'
        verbose_name_plural = '스냅샷 목록'
        ordering = ['-captured_at']
        indexes = [
            models.Index(fields=['camera']),
            models.Index(fields=['captured_at']),
            models.Index(fields=['processing_status_ai']),
            models.Index(fields=['processing_status_congestion']),
        ]
        db_table = 'Snapshots'


class DetectedObjects(models.Model):
    detection_id = models.BigAutoField(primary_key=True, help_text='객체 탐지 고유 ID')
    snapshot = models.ForeignKey(
        Snapshots,
        on_delete=models.CASCADE, # 스냅샷 삭제 시 관련 탐지 객체도 삭제
        help_text='분석된 스냅샷 ID'
    )
    object_track_id = models.IntegerField(null=True, blank=True, help_text='객체 추적 ID (2학기 활용 가능)')
    class_label = models.CharField(max_length=50, default='person', help_text='탐지된 객체 종류 (주로 person)')
    confidence = models.FloatField(null=True, blank=True, help_text='탐지 신뢰도')
    bbox_x = models.IntegerField(help_text='바운딩 박스 좌상단 x 좌표')
    bbox_y = models.IntegerField(help_text='바운딩 박스 좌상단 y 좌표')
    bbox_width = models.IntegerField(help_text='바운딩 박스 너비')
    bbox_height = models.IntegerField(help_text='바운딩 박스 높이')
    center_x = models.IntegerField(null=True, blank=True, help_text='객체 중심 x 좌표 (2학기 분석용)')
    center_y = models.IntegerField(null=True, blank=True, help_text='객체 중심 y 좌표 (2학기 분석용)')

    def __str__(self):
        return f"Detection {self.detection_id} ({self.class_label}) in Snapshot {self.snapshot_id}"

    class Meta:
        verbose_name = '탐지된 객체'
        verbose_name_plural = '탐지된 객체 목록'
        indexes = [
            models.Index(fields=['snapshot']),
            models.Index(fields=['class_label']),
        ]
        db_table = 'Detected_Objects' # 스키마 이름과 일치시키기 위해 Detected_Objects 사용


class CongestionEvents(models.Model):
    event_id = models.BigAutoField(primary_key=True, help_text='혼잡도 이벤트 고유 ID')
    camera = models.ForeignKey(
        Cameras,
        on_delete=models.CASCADE,
        help_text='대상 카메라 ID'
    )
    snapshot = models.ForeignKey(
        Snapshots,
        on_delete=models.SET_NULL, # 스냅샷이 삭제되어도 이벤트 기록은 남길 수 있도록 SET_NULL (또는 다른 정책)
        null=True, blank=True, # 스키마에서 snapshot_id가 null 허용
        help_text='이벤트 계산에 사용된 대표 스냅샷 ID'
    )
    event_timestamp = models.DateTimeField(help_text='혼잡도 측정/이벤트 발생 시각')
    person_count = models.IntegerField(help_text='해당 시점/스냅샷에서 탐지된 총 사람 수')
    estimated_roi_pixel_area = models.IntegerField(null=True, blank=True, help_text='추정된 ROI 픽셀 면적')
    congestion_value_raw = models.FloatField(null=True, blank=True, help_text='계산된 원시 밀집도 값')
    congestion_level = models.CharField(
        max_length=20,
        choices=CongestionLevel.choices,
        help_text='최종 판정된 혼잡도 수준'
    )
    comparison_historical_avg_count = models.IntegerField(null=True, blank=True, help_text='비교 기준으로 사용된 과거 동일 시간대 평균 인원 수')
    alert_triggered = models.BooleanField(default=False, help_text='위험 상황 알림 발생 여부')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Congestion Event {self.event_id} for Camera {self.camera_id} at {self.event_timestamp} ({self.congestion_level})"

    class Meta:
        verbose_name = '혼잡도 이벤트'
        verbose_name_plural = '혼잡도 이벤트 목록'
        ordering = ['-event_timestamp']
        indexes = [
            models.Index(fields=['camera', 'event_timestamp'], name='idx_congestion_camera_time'),
            models.Index(fields=['snapshot']),
            models.Index(fields=['congestion_level']),
        ]
        db_table = 'Congestion_Events'


class ROIDefinitions(models.Model):
    roi_def_id = models.AutoField(primary_key=True, help_text='ROI 정의 고유 ID') # 스키마에서 integer pk
    camera = models.ForeignKey(
        Cameras,
        on_delete=models.CASCADE,
        help_text='대상 카메라 ID'
    )
    definition_type = models.CharField(
        max_length=50,
        choices=ROIDefinitionType.choices, # 정의한 Choices 사용
        help_text='ROI 정의 방식'
    )
    definition_data = models.JSONField(null=True, blank=True, help_text='ROI 정의 데이터 (폴리곤 좌표, 파라미터 등)')
    is_active = models.BooleanField(default=True, help_text='현재 사용 중인 ROI 정의인지 여부')
    version = models.IntegerField(default=1, help_text='ROI 정의 버전')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ROI Definition {self.roi_def_id} for Camera {self.camera_id} (v{self.version})"

    class Meta:
        verbose_name = 'ROI 정의'
        verbose_name_plural = 'ROI 정의 목록'
        ordering = ['camera', '-version']
        indexes = [
            models.Index(fields=['camera', 'is_active']),
        ]
        db_table = 'ROI_Definitions'