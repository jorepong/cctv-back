# analytics/models.py
from django.db import models
from django.utils import timezone # now() 대신 Django의 timezone.now 또는 auto_now/auto_now_add 사용

# cameras 앱의 Cameras 모델을 임포트합니다.
# 실제 프로젝트 구조에 따라 'project_name.cameras.models' 또는 'cameras.models'가 될 수 있습니다.
# 보통은 'app_name.models' 형태로 임포트합니다.
from cameras.models import Cameras, CameraStatus, CameraSourceType

# Enum-like choices for analytics models
class ProcessingStatus(models.TextChoices):
    PENDING = 'PENDING', '대기중 (PENDING)'
    PROCESSING = 'PROCESSING', '처리중 (PROCESSING)'
    COMPLETED = 'COMPLETED', '완료 (COMPLETED)'
    FAILED = 'FAILED', '실패 (FAILED)'

class CongestionLevelLabel(models.TextChoices):
    LOW = 'LOW', '낮음 (LOW)'
    MEDIUM = 'MEDIUM', '중간 (MEDIUM)'
    HIGH = 'HIGH', '높음 (HIGH)'
    VERY_HIGH = 'VERY_HIGH', '매우 높음 (VERY_HIGH)' # 스키마 노트에 따름

class ROIDefinitionType(models.TextChoices):
    MANUAL_POLYGON = 'MANUAL_POLYGON', '수동 폴리곤'
    DYNAMIC_CONVEX_HULL = 'DYNAMIC_CONVEX_HULL', '동적 컨벡스 헐'
    MOTION_PATTERN_BASED = 'MOTION_PATTERN_BASED', '움직임 패턴 기반'
    DYNAMIC_ALPHA_SHAPE = 'DYNAMIC_ALPHA_SHAPE', '동적 알파 셰이프'
    DYNAMIC_ALPHA_SHAPE_SLIDING = 'DYNAMIC_ALPHA_SHAPE_SLIDING', '동적 알파 셰이프 (슬라이딩 윈도우)'


class Snapshots(models.Model):
    snapshot_id = models.BigAutoField(primary_key=True, help_text='스냅샷 고유 ID')
    camera = models.ForeignKey(
        Cameras,  # cameras.models에서 임포트한 Cameras 모델 사용
        on_delete=models.CASCADE,
        related_name='snapshots',
        help_text='촬영된 카메라 ID'
    )
    captured_at = models.DateTimeField(help_text='스냅샷 캡처 시각')
    image_path = models.CharField(max_length=512, help_text='저장된 원본 이미지 파일 경로 (서버 내 경로)')
    processed_image_path = models.CharField(
        max_length=512,
        null=True,
        blank=True,
        help_text='AI 분석 후 바운딩 박스 등이 그려진 처리된 이미지 파일 경로 (서버 내 경로)'
    )
    processing_status_ai = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        help_text='AI 분석 처리 상태 (PENDING, PROCESSING, COMPLETED, FAILED)'
    )
    processing_status_congestion = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        help_text='밀집도 계산 처리 상태 (PENDING, PROCESSING, COMPLETED, FAILED)'
    )
    analyzed_at_ai = models.DateTimeField(null=True, blank=True, help_text='AI 분석 완료 시각')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'Snapshots'
        verbose_name = '스냅샷 (Snapshot)'
        verbose_name_plural = '스냅샷 목록 (Snapshots)'
        indexes = [
            models.Index(fields=['camera']),
            models.Index(fields=['captured_at']),
            models.Index(fields=['processing_status_ai']),
            models.Index(fields=['processing_status_congestion']),
        ]

    def __str__(self):
        # self.camera_id는 ForeignKey 필드 'camera'에 대해 Django가 자동으로 생성하는 ID 필드명입니다.
        return f"Snapshot ID: {self.snapshot_id} for Camera ID: {self.camera_id} at {self.captured_at}"


class DetectedObjects(models.Model):
    detection_id = models.BigAutoField(primary_key=True, help_text='객체 탐지 고유 ID')
    snapshot = models.ForeignKey(
        Snapshots, # 같은 파일 내에 정의된 Snapshots 모델 사용
        on_delete=models.CASCADE,
        related_name='detected_objects',
        help_text='분석된 스냅샷 ID'
    )
    object_track_id = models.IntegerField(null=True, blank=True, help_text='객체 추적 ID (2학기 활용 가능)')
    class_label = models.CharField(
        max_length=50,
        default='person',
        help_text='탐지된 객체 종류 (주로 person)'
    )
    confidence = models.FloatField(null=True, blank=True, help_text='탐지 신뢰도')
    bbox_x = models.IntegerField(help_text='바운딩 박스 좌상단 x 좌표')
    bbox_y = models.IntegerField(help_text='바운딩 박스 좌상단 y 좌표')
    bbox_width = models.IntegerField(help_text='바운딩 박스 너비')
    bbox_height = models.IntegerField(help_text='바운딩 박스 높이')
    center_x = models.IntegerField(null=True, blank=True, help_text='객체 중심 x 좌표 (2학기 분석용)')
    center_y = models.IntegerField(null=True, blank=True, help_text='객체 중심 y 좌표 (2학기 분석용)')

    class Meta:
        db_table = 'Detected_Objects'
        verbose_name = '탐지된 객체 (Detected Object)'
        verbose_name_plural = '탐지된 객체 목록 (Detected Objects)'
        indexes = [
            models.Index(fields=['snapshot']),
            models.Index(fields=['class_label']),
        ]

    def __str__(self):
        # self.snapshot_id는 ForeignKey 필드 'snapshot'에 대해 Django가 자동으로 생성하는 ID 필드명입니다.
        return f"Detection ID: {self.detection_id} ({self.class_label}) in Snapshot ID: {self.snapshot_id}"


class CongestionEvents(models.Model):
    event_id = models.BigAutoField(primary_key=True, help_text='혼잡도 이벤트 고유 ID')
    camera = models.ForeignKey(
        Cameras,  # cameras.models에서 임포트한 Cameras 모델 사용
        on_delete=models.CASCADE,
        related_name='congestion_events',
        help_text='대상 카메라 ID'
    )
    snapshot = models.ForeignKey(
        Snapshots, # 같은 파일 내에 정의된 Snapshots 모델 사용
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='congestion_events',
        help_text='이벤트 계산에 사용된 대표 스냅샷 ID'
    )
    event_timestamp = models.DateTimeField(help_text='혼잡도 측정/이벤트 발생 시각')
    person_count = models.IntegerField(help_text='해당 시점/스냅샷에서 탐지된 총 사람 수')
    estimated_roi_pixel_area = models.IntegerField(
        null=True,
        blank=True,
        help_text='추정된 ROI 픽셀 면적 (1학기에는 단순 값, 2학기 정밀 계산)'
    )
    congestion_value_raw = models.FloatField(
        null=True,
        blank=True,
        help_text='계산된 원시 밀집도 값 (예: person_count / estimated_roi_pixel_area)'
    )
    congestion_level = models.CharField(
        max_length=20,
        choices=CongestionLevelLabel.choices,
        help_text='최종 판정된 혼잡도 수준 (LOW, MEDIUM, HIGH 등)'
    )
    comparison_historical_avg_count = models.IntegerField(
        null=True,
        blank=True,
        help_text='비교 기준으로 사용된 과거 동일 시간대 평균 인원 수'
    )
    alert_triggered = models.BooleanField(default=False, help_text='위험 상황 알림 발생 여부')
    is_acknowledged = models.BooleanField(default=False, help_text='해당 이벤트(알림)에 대한 관리자 확인 여부')
    acknowledged_at = models.DateTimeField(null=True, blank=True, help_text='관리자가 해당 이벤트(알림)를 확인한 시각')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'Congestion_Events'
        verbose_name = '혼잡도 이벤트 (Congestion Event)'
        verbose_name_plural = '혼잡도 이벤트 목록 (Congestion Events)'
        indexes = [
            models.Index(fields=['camera', 'event_timestamp'], name='idx_congestion_camera_time'),
            models.Index(fields=['snapshot']),
            models.Index(fields=['congestion_level']),
            models.Index(fields=['is_acknowledged']),
        ]

    def __str__(self):
        # self.camera_id는 ForeignKey 필드 'camera'에 대해 Django가 자동으로 생성하는 ID 필드명입니다.
        return f"Event ID: {self.event_id} for Camera ID: {self.camera_id} at {self.event_timestamp} - Level: {self.congestion_level}"


class ROIDefinitions(models.Model):
    roi_def_id = models.AutoField(primary_key=True, help_text='ROI 정의 고유 ID')
    camera = models.ForeignKey(
        Cameras,  # cameras.models에서 임포트한 Cameras 모델 사용
        on_delete=models.CASCADE,
        related_name='roi_definitions',
        help_text='대상 카메라 ID'
    )
    definition_type = models.CharField(
        max_length=50,
        choices=ROIDefinitionType.choices,
        help_text='ROI 정의 방식 (MANUAL_POLYGON, DYNAMIC_CONVEX_HULL, MOTION_PATTERN_BASED)'
    )
    definition_data = models.JSONField(
        null=True,
        blank=True,
        help_text='ROI 정의 데이터 (폴리곤 좌표, 파라미터 등)'
    )
    is_active = models.BooleanField(default=True, help_text='현재 사용 중인 ROI 정의인지 여부')
    version = models.IntegerField(default=1, help_text='ROI 정의 버전')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ROI_Definitions'
        verbose_name = 'ROI 정의 (ROI Definition)'
        verbose_name_plural = 'ROI 정의 목록 (ROI Definitions)'
        indexes = [
            models.Index(fields=['camera', 'is_active']),
        ]

    def __str__(self):
        # self.camera_id는 ForeignKey 필드 'camera'에 대해 Django가 자동으로 생성하는 ID 필드명입니다.
        return f"ROI Definition ID: {self.roi_def_id} for Camera ID: {self.camera_id} (Version: {self.version})"