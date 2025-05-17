# models.py
from django.db import models
from django.utils import timezone # now() 대신 Django의 timezone.now 또는 auto_now/auto_now_add 사용

# Enum-like choices for relevant fields
# 이 클래스들은 models.py 상단이나 별도의 choices.py 파일에 정의할 수 있습니다.

class CameraStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', '활성 (ACTIVE)'
    INACTIVE = 'INACTIVE', '비활성 (INACTIVE)'
    ERROR = 'ERROR', '오류 (ERROR)'

class CameraSourceType(models.TextChoices):
    TESTBED = 'TESTBED', '테스트베드 (TESTBED)'
    WONWOO_REMOTE = 'WONWOO_REMOTE', '원우 리모트 (WONWOO_REMOTE)' # 예시, 실제 값으로 변경 가능
    YOUTUBE_LIVE = 'YOUTUBE_LIVE', '유튜브 라이브 (YOUTUBE_LIVE)'

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


class Cameras(models.Model):
    camera_id = models.AutoField(primary_key=True, help_text='카메라 고유 ID')
    name = models.CharField(max_length=255, help_text='카메라 이름 (예: 신공학관 9층 엘리베이터 앞)')
    rtsp_url = models.CharField(max_length=512, null=True, blank=True, help_text='RTSP 스트리밍 URL (외부 CCTV용)')
    source_type = models.CharField(
        max_length=50,
        choices=CameraSourceType.choices,
        default=CameraSourceType.TESTBED,
        help_text='카메라 소스 타입 (TESTBED, WONWOO_REMOTE, YOUTUBE_LIVE)'
    )
    location_description = models.TextField(null=True, blank=True, help_text='설치 위치 상세 설명')
    resolution_width = models.IntegerField(null=True, blank=True, help_text='해상도 너비')
    resolution_height = models.IntegerField(null=True, blank=True, help_text='해상도 높이')
    status = models.CharField(
        max_length=20,
        choices=CameraStatus.choices,
        default=CameraStatus.ACTIVE,
        help_text='카메라 상태 (ACTIVE, INACTIVE, ERROR)'
    )
    is_active_monitoring = models.BooleanField(default=True, help_text='현재 모니터링(분석) 대상 여부')
    created_at = models.DateTimeField(auto_now_add=True, help_text='레코드 생성 시각')
    updated_at = models.DateTimeField(auto_now=True, help_text='레코드 수정 시각')

    class Meta:
        db_table = 'Cameras'
        verbose_name = '카메라 (Camera)'
        verbose_name_plural = '카메라 목록 (Cameras)'

    def __str__(self):
        return f"{self.name} (ID: {self.camera_id})"


class Snapshots(models.Model):
    snapshot_id = models.BigAutoField(primary_key=True, help_text='스냅샷 고유 ID')
    camera = models.ForeignKey(
        Cameras,
        on_delete=models.CASCADE, # 카메라 삭제 시 관련 스냅샷도 삭제
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
            models.Index(fields=['camera']), # ForeignKey는 자동으로 인덱스 생성되지만 명시
            models.Index(fields=['captured_at']),
            models.Index(fields=['processing_status_ai']),
            models.Index(fields=['processing_status_congestion']),
        ]

    def __str__(self):
        return f"Snapshot ID: {self.snapshot_id} for Camera ID: {self.camera_id} at {self.captured_at}"


class DetectedObjects(models.Model):
    detection_id = models.BigAutoField(primary_key=True, help_text='객체 탐지 고유 ID')
    snapshot = models.ForeignKey(
        Snapshots,
        on_delete=models.CASCADE, # 스냅샷 삭제 시 관련 탐지 객체도 삭제
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
        db_table = 'Detected_Objects' # 스키마 명칭과 일치
        verbose_name = '탐지된 객체 (Detected Object)'
        verbose_name_plural = '탐지된 객체 목록 (Detected Objects)'
        indexes = [
            models.Index(fields=['snapshot']), # ForeignKey는 자동으로 인덱스 생성되지만 명시
            models.Index(fields=['class_label']),
        ]

    def __str__(self):
        return f"Detection ID: {self.detection_id} ({self.class_label}) in Snapshot ID: {self.snapshot_id}"


class CongestionEvents(models.Model):
    event_id = models.BigAutoField(primary_key=True, help_text='혼잡도 이벤트 고유 ID')
    camera = models.ForeignKey(
        Cameras,
        on_delete=models.CASCADE, # 카메라 삭제 시 관련 이벤트도 삭제
        related_name='congestion_events',
        help_text='대상 카메라 ID'
    )
    snapshot = models.ForeignKey(
        Snapshots,
        on_delete=models.SET_NULL, # 스냅샷이 삭제되어도 이벤트 기록은 남을 수 있도록 (필요시 CASCADE로 변경)
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
            models.Index(fields=['snapshot']), # snapshot_id가 null 가능하므로 별도 인덱스 고려
            models.Index(fields=['congestion_level']),
            models.Index(fields=['is_acknowledged']),
        ]

    def __str__(self):
        return f"Event ID: {self.event_id} for Camera ID: {self.camera_id} at {self.event_timestamp} - Level: {self.congestion_level}"


class ROIDefinitions(models.Model):
    roi_def_id = models.AutoField(primary_key=True, help_text='ROI 정의 고유 ID')
    camera = models.ForeignKey(
        Cameras,
        on_delete=models.CASCADE,
        related_name='roi_definitions',
        help_text='대상 카메라 ID'
    )
    definition_type = models.CharField(
        max_length=50,
        choices=ROIDefinitionType.choices,
        help_text='ROI 정의 방식 (MANUAL_POLYGON, DYNAMIC_CONVEX_HULL, MOTION_PATTERN_BASED)'
    )
    # MariaDB에서 JSONField를 사용하려면 Django 3.1+ 및 MariaDB 10.2.7+ 필요
    # 또는 TextField에 JSON 문자열을 저장하고 애플리케이션 레벨에서 직렬화/역직렬화 처리
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
        return f"ROI Definition ID: {self.roi_def_id} for Camera ID: {self.camera_id} (Version: {self.version})"