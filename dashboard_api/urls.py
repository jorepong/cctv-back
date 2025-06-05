from django.urls import path
from .views import (
    CameraListView,
    CameraDetailView,
    CameraStreamURLView,
    # 다른 View들을 이곳에 추가할 예정
)

from .views import (
    # CameraListView, CameraDetailView, CameraStreamURLView, (이전 답변에서 제공)
    LatestCongestionView, # (이전 답변에서 제공된 View)
    CongestionHistoryView,
    CongestionStatisticsView,
    ProcessedSnapshotImageView,
    AlertListView,
    AlertAcknowledgeView,
)

urlpatterns = [
    # 카메라 관리 API
    path('cameras/', CameraListView.as_view(), name='camera-list'),
    path('cameras/<int:camera_id>/', CameraDetailView.as_view(), name='camera-detail'),
    path('cameras/<int:camera_id>/stream_url/', CameraStreamURLView.as_view(), name='camera-stream-url'),

    # 혼잡도 및 이벤트 데이터 API
    path('congestion/latest/', LatestCongestionView.as_view(), name='latest_congestion'),
    path('congestion/history/', CongestionHistoryView.as_view(), name='congestion-history'),
    path('congestion/statistics/', CongestionStatisticsView.as_view(), name='congestion-statistics'),

    # AI 분석 완료된 스냅샷 이미지 조회 API
    path('snapshots/<int:snapshot_id>/processed_image/', ProcessedSnapshotImageView.as_view(), name='processed-snapshot-image'),

    # 알림 관리 API
    path('alerts/', AlertListView.as_view(), name='alert-list'),
    path('alerts/<int:event_id>/acknowledge/', AlertAcknowledgeView.as_view(), name='alert-acknowledge'), # alert_id는 CongestionEvents.event_id를 사용
]
