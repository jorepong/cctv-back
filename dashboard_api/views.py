# dashboard_api/views.py
from datetime import timedelta, datetime

from django.db.models import Avg, Max
from django.db.models.functions import TruncDate, ExtractWeekDay, \
    ExtractHour
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView, UpdateAPIView
from rest_framework.pagination import PageNumberPagination  # 페이지네이션
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import CongestionEvents, CongestionLevelLabel, Snapshots
from cameras.models import Cameras
from .serializers import (
    CameraSerializer,
    CameraStreamURLSerializer,
    LatestCongestionSerializer,  # (이전 답변에서 제공된 Serializer)
    CongestionHistoryDataSerializer,
    ProcessedSnapshotImageSerializer,
    AlertSerializer,
    AlertAcknowledgeSerializer,
)


class CameraListView(ListAPIView):
    """
    시스템에 등록된 카메라 목록을 조회합니다. (GET /cameras/)
    Query Parameters:
        status (string): 카메라 상태 (ACTIVE, INACTIVE, ERROR)
        is_active_monitoring (boolean): 현재 모니터링 대상 여부 (true/false)
    """
    serializer_class = CameraSerializer

    def get_queryset(self):
        queryset = Cameras.objects.all()

        status_param = self.request.query_params.get('status')
        is_active_param = self.request.query_params.get('is_active_monitoring')

        if status_param:
            queryset = queryset.filter(status__iexact=status_param)  # 대소문자 구분 없이 필터링

        if is_active_param is not None:
            if is_active_param.lower() == 'true':
                queryset = queryset.filter(is_active_monitoring=True)
            elif is_active_param.lower() == 'false':
                queryset = queryset.filter(is_active_monitoring=False)
            # 다른 값의 경우 무시하거나 에러 처리 가능

        return queryset.order_by('camera_id')


class CameraDetailView(RetrieveAPIView):
    """
    지정된 camera_id에 해당하는 카메라의 상세 정보를 조회합니다. (GET /cameras/{camera_id}/)
    """
    queryset = Cameras.objects.all()
    serializer_class = CameraSerializer
    lookup_field = 'camera_id'  # URL 경로에서 camera_id를 사용


class CameraStreamURLView(APIView):
    """
    특정 카메라의 실시간 영상 피드를 위한 HLS 또는 MPEG-DASH 스트림 URL을 가져옵니다.
    (GET /cameras/{camera_id}/stream_url/)
    """

    def get_object(self, camera_id):
        try:
            return Cameras.objects.get(camera_id=camera_id)
        except Cameras.DoesNotExist:
            raise Http404

    def get(self, request, camera_id, format=None):
        camera = self.get_object(camera_id)

        # --- 스트리밍 URL 생성 로직 (이수연 팀원 담당 부분 연동) ---
        # 이 부분은 실제 스트리밍 서버, RTSP to HLS/DASH 변환 로직과 연동되어야 합니다.
        # 예시: HLS를 사용하고, 카메라 ID 기반으로 URL을 동적으로 생성한다고 가정
        # 실제 구현 시, camera.rtsp_url, camera.source_type 등을 활용하여
        # 스트림 변환 서비스 호출 또는 URL 생성 규칙 적용

        # 임시 하드코딩된 예시 URL (실제 환경에서는 동적으로 생성 또는 조회 필요)
        # 실제로는 camera 객체의 정보를 바탕으로 스트리밍 서버에 요청하거나,
        # 정해진 규칙에 따라 URL을 구성해야 합니다.
        # 예를 들어, 이수연 팀원이 개발한 함수를 호출할 수 있습니다.
        # streaming_info = get_hls_stream_url_for_camera(camera.camera_id, camera.rtsp_url)

        # 아래는 예시 응답 데이터입니다. 실제 로직으로 대체해야 합니다.
        if camera.status == Cameras.CameraStatus.ACTIVE:  # 예: 활성 상태인 카메라만 스트리밍 제공
            # 실제 스트리밍 URL 생성/조회 로직 필요
            # stream_url = f"https://streaming.example.com/live/{camera.camera_id}/playlist.m3u8"
            # stream_type = "HLS"

            # API 명세에 따른 더미 데이터 (실제 값으로 대체 필요)
            stream_url = f"https://your-streaming-server.com/live/{camera.camera_id}/playlist.m3u8"
            stream_type = "HLS"

            data = {
                "camera_id": camera.camera_id,
                "name": camera.name,
                "stream_url": stream_url,
                "stream_type": stream_type
            }
            serializer = CameraStreamURLSerializer(data=data)
            if serializer.is_valid():
                return Response(serializer.data, status=status.HTTP_200_OK)
            else:  # 보통 이 경우는 서버측 로직 오류
                return Response(serializer.errors, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({
                "error_code": "NOT_FOUND",  # 또는 SERVICE_UNAVAILABLE
                "message": f"카메라 ID {camera_id}의 스트리밍을 사용할 수 없거나 준비되지 않았습니다 (상태: {camera.status})."
            }, status=status.HTTP_404_NOT_FOUND)  # 또는 503


class LatestCongestionView(APIView):
    """
    최신 혼잡도 상태를 조회합니다.
    - 모든 활성 카메라: GET /api/v1/congestion/latest/
    - 특정 카메라: GET /api/v1/congestion/latest/?camera_id=<id>
    """

    def get(self, request, *args, **kwargs):
        camera_id_param = request.query_params.get('camera_id')

        target_cameras = []
        if camera_id_param:
            try:
                camera_id = int(camera_id_param)
                # 특정 카메라 조회 시에는 is_active_monitoring 조건을 명시적으로 확인할 필요가 있다면 추가
                # API 명세에는 "활성 카메라 또는 특정 카메라"로 되어있으므로, 특정 ID 조회 시에는 활성 여부를 필수로 체크하지 않을 수 있음
                # 여기서는 명세에 따라 카메라 존재 여부만 확인 (필요시 is_active_monitoring=True 추가)
                camera = Cameras.objects.get(camera_id=camera_id)
                target_cameras.append(camera)
            except Cameras.DoesNotExist:
                return Response({
                    "error_code": "NOT_FOUND",
                    "message": f"카메라 ID {camera_id_param}을(를) 찾을 수 없습니다."
                }, status=status.HTTP_404_NOT_FOUND)
            except ValueError:
                return Response({
                    "error_code": "INVALID_PARAMETER",
                    "message": "잘못된 camera_id 형식입니다."
                }, status=status.HTTP_400_BAD_REQUEST)
        else:
            # camera_id 파라미터가 없으면 is_active_monitoring=True 인 모든 카메라 조회
            target_cameras = Cameras.objects.filter(is_active_monitoring=True)
            if not target_cameras.exists():
                return Response({"message": "모니터링이 활성화된 카메라가 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        response_data_list = []
        single_camera_response = None

        for camera in target_cameras:
            # 각 카메라의 가장 최신 CongestionEvent 조회
            # select_related를 사용하여 ForeignKey 필드를 미리 JOIN하여 쿼리 효율성 증대
            latest_event = CongestionEvents.objects.filter(camera=camera) \
                .select_related('camera', 'snapshot') \
                .order_by('-event_timestamp') \
                .first()
            if latest_event:
                serializer = LatestCongestionSerializer(latest_event)
                if camera_id_param:  # 특정 카메라를 조회한 경우
                    single_camera_response = serializer.data
                    break  # 이미 특정 카메라를 찾았으므로 루프 종료
                response_data_list.append(serializer.data)

        if camera_id_param:
            if single_camera_response:
                return Response(single_camera_response, status=status.HTTP_200_OK)
            else:
                # 카메라는 존재하지만 혼잡도 데이터가 없는 경우
                return Response({
                    "message": f"카메라 ID {camera_id_param}에 대한 최신 혼잡도 데이터를 찾을 수 없습니다."
                }, status=status.HTTP_404_NOT_FOUND)
        else:
            if not response_data_list:  # 활성 카메라는 있지만 혼잡도 데이터가 없는 경우
                return Response({"message": "활성 카메라의 최신 혼잡도 데이터를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
            return Response(response_data_list, status=status.HTTP_200_OK)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 100  # 기본 페이지 크기 (API 명세: limit 기본값 100)
    page_size_query_param = 'limit'  # 클라이언트가 페이지 크기 설정 시 사용할 파라미터
    max_page_size = 1000  # 최대 페이지 크기


class CongestionHistoryView(ListAPIView):
    """
    특정 카메라의 과거 혼잡도 이력을 조회합니다. (GET /congestion/history/)
    Query Parameters (필수): camera_id
    Query Parameters (선택): start_time, end_time, period, limit, page
    """
    serializer_class = CongestionHistoryDataSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        camera_id_param = self.request.query_params.get('camera_id')
        if not camera_id_param:
            # DRF ListAPIView는 queryset을 반환해야 하므로, 빈 queryset 반환 또는 에러 발생
            # 여기서는 명시적으로 에러를 발생시키기보다, 아래 get 함수에서 처리
            return CongestionEvents.objects.none()

        try:
            camera_id = int(camera_id_param)
            # 카메라 존재 여부 확인
            if not Cameras.objects.filter(camera_id=camera_id).exists():
                raise Http404("카메라를 찾을 수 없습니다.")  # 이 예외는 아래 get에서 처리
        except ValueError:
            # 이 예외는 아래 get에서 처리
            raise ValueError("잘못된 camera_id 형식입니다.")
        except Http404:  # 위에서 발생한 Http404를 다시 발생시킴
            raise

        queryset = CongestionEvents.objects.filter(camera_id=camera_id) \
            .select_related('camera') \
            .order_by('event_timestamp')  # 기본 정렬

        start_time_str = self.request.query_params.get('start_time')
        end_time_str = self.request.query_params.get('end_time')
        period = self.request.query_params.get('period', 'minutely')  # 기본값 'minutely'

        if start_time_str:
            try:
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                queryset = queryset.filter(event_timestamp__gte=start_time)
            except ValueError:
                # 잘못된 형식의 날짜 문자열에 대한 처리 (또는 에러 응답)
                pass  # 여기서는 무시하고 진행하거나, 에러 응답을 고려할 수 있습니다.

        if end_time_str:
            try:
                end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                queryset = queryset.filter(event_timestamp__lte=end_time)
            except ValueError:
                pass

        # period 파라미터 처리:
        # API 명세는 minutely, hourly, daily, weekly를 언급.
        # 'minutely'는 현재처럼 개별 이벤트 데이터를 반환하는 것이 적합.
        # 'hourly', 'daily', 'weekly'는 데이터 집계(aggregation) 로직이 필요.
        # 1학기 범위에서는 'minutely'를 기본으로 하고, 다른 period에 대해서는
        # 집계 로직이 복잡하므로, 현재는 필터링된 데이터를 그대로 반환하거나,
        # 또는 "지원하지 않는 period" 에러를 반환할 수 있습니다.
        # 여기서는 period 값에 따른 분기 처리는 생략하고, 모든 데이터를 event_timestamp 기준으로 반환합니다.
        # 실제 집계가 필요하면 Django ORM의 annotate와 values를 사용해야 합니다.

        return queryset

    def list(self, request, *args, **kwargs):
        # camera_id 필수 파라미터 검증
        camera_id_param = request.query_params.get('camera_id')
        if not camera_id_param:
            return Response({
                "error_code": "INVALID_PARAMETER",
                "message": "필수 파라미터 'camera_id'가 누락되었습니다."
            }, status=status.HTTP_400_BAD_REQUEST)
        try:
            int(camera_id_param)  # 형식 검증
            if not Cameras.objects.filter(camera_id=camera_id_param).exists():
                raise Http404("카메라를 찾을 수 없습니다.")
        except ValueError:
            return Response({
                "error_code": "INVALID_PARAMETER",
                "message": "잘못된 camera_id 형식입니다."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Http404 as e:
            return Response({"error_code": "NOT_FOUND", "message": str(e)}, status=status.HTTP_404_NOT_FOUND)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        camera_name = ""
        if queryset.exists():  # queryset이 비어있지 않다면 카메라 이름 가져오기
            camera_name = queryset.first().camera.name
        elif camera_id_param:  # queryset이 비어있지만 camera_id로 조회 시도한 경우
            try:
                camera = Cameras.objects.get(camera_id=camera_id_param)
                camera_name = camera.name
            except Cameras.DoesNotExist:
                pass  # 위에서 이미 Http404 처리됨

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated_response = self.get_paginated_response(serializer.data)
            # API 명세에 맞게 응답 데이터 구조 수정
            custom_response_data = {
                'camera_id': int(camera_id_param) if camera_id_param else None,
                'name': camera_name,
                'period': request.query_params.get('period', 'minutely'),
                'data': paginated_response.data.pop('results'),  # results를 data로 변경
            }
            # paginated_response.data에 이미 pagination 정보가 있음
            custom_response_data.update(paginated_response.data)
            return Response(custom_response_data)

        serializer = self.get_serializer(queryset, many=True)
        # 페이지네이션이 적용되지 않는 경우 (예: pagination_class=None)
        return Response({
            'camera_id': int(camera_id_param) if camera_id_param else None,
            'name': camera_name,
            'period': request.query_params.get('period', 'minutely'),
            'data': serializer.data,
            'pagination': None  # 또는 빈 pagination 정보
        })


class CongestionStatisticsView(APIView):
    """
    특정 카메라 또는 전체 시스템의 집계된 통계 정보를 조회합니다. (GET /congestion/statistics/)
    Query Parameters (필수): camera_id ("all" 또는 integer)
    Query Parameters (선택): start_date, end_date, group_by
    """

    def get(self, request, *args, **kwargs):
        camera_id_param = request.query_params.get('camera_id')
        if not camera_id_param:
            return Response({
                "error_code": "INVALID_PARAMETER",
                "message": "필수 파라미터 'camera_id'가 누락되었습니다."
            }, status=status.HTTP_400_BAD_REQUEST)

        # 날짜 범위 설정 (API 명세 기본 동작: 지난 1주일)
        end_date_str = request.query_params.get('end_date')
        start_date_str = request.query_params.get('start_date')

        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).replace(hour=23, minute=59,
                                                                                               second=59,
                                                                                               microsecond=999999)
            except ValueError:
                return Response({"error_code": "INVALID_PARAMETER", "message": "잘못된 end_date 형식입니다."},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            end_date = timezone.now().replace(hour=23, minute=59, second=59, microsecond=999999)

        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).replace(hour=0, minute=0,
                                                                                                   second=0,
                                                                                                   microsecond=0)
            except ValueError:
                return Response({"error_code": "INVALID_PARAMETER", "message": "잘못된 start_date 형식입니다."},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            # start_date 또는 end_date 중 하나라도 입력되지 않으면 지난 1주일
            if not end_date_str:  # 둘 다 입력 안 된 경우, end_date도 재설정
                end_date = timezone.now().replace(hour=23, minute=59, second=59, microsecond=999999)
            start_date = (end_date - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

        group_by = request.query_params.get('group_by', 'date')  # 기본값 'date'

        queryset = CongestionEvents.objects.filter(
            event_timestamp__gte=start_date,
            event_timestamp__lte=end_date
        ).select_related('camera')

        camera_name = "전체 시스템"  # camera_id="all"일 경우
        target_camera_id_int = None

        if camera_id_param.lower() != 'all':
            try:
                target_camera_id_int = int(camera_id_param)
                camera_obj = Cameras.objects.get(camera_id=target_camera_id_int)
                queryset = queryset.filter(camera_id=target_camera_id_int)
                camera_name = camera_obj.name
            except Cameras.DoesNotExist:
                return Response({"error_code": "NOT_FOUND", "message": f"카메라 ID {camera_id_param}을(를) 찾을 수 없습니다."},
                                status=status.HTTP_404_NOT_FOUND)
            except ValueError:
                return Response({"error_code": "INVALID_PARAMETER", "message": "잘못된 camera_id 형식입니다."},
                                status=status.HTTP_400_BAD_REQUEST)

        # --- 집계 로직 시작 ---
        # API 명세의 응답 예시('statistics' 필드)는 avg_person_count, peak_congestion_level, avg_congestion_value_raw 포함
        # peak_congestion_level은 정의가 모호하여 구현이 복잡할 수 있음 (예: 가장 빈번했던 최고 수준 or 최고 인원수일 때의 수준)
        # 여기서는 avg_person_count, avg_congestion_value_raw, max_person_count를 중심으로 구현

        aggregation_fields = {
            'avg_person_count': Avg('person_count'),
            'avg_congestion_value_raw': Avg('congestion_value_raw'),
            'max_person_count': Max('person_count'),  # peak_congestion_level 대신 max_person_count로 대체 또는 추가 정보 활용
        }

        # CongestionLevelLabel 순서 (VERY_HIGH가 가장 높음)
        level_order = [CongestionLevelLabel.VERY_HIGH, CongestionLevelLabel.HIGH, CongestionLevelLabel.MEDIUM,
                       CongestionLevelLabel.LOW]
        # peak_congestion_level을 위해 각 그룹 내에서 가장 높은 빈도의 congestion_level 또는 특정 규칙에 따른 레벨 결정 필요.
        # 단순화를 위해 여기서는 max_person_count 시점의 congestion_level을 가져오거나, 그룹 내 최빈값 등을 고려해야 함.
        # 이 부분은 프로젝트의 정확한 요구사항에 따라 구현 방식이 달라질 수 있음.
        # 여기서는 peak_congestion_level을 제외하고 진행하거나, max_person_count로 대체 표현.
        # 만약 peak_congestion_level을 구현한다면 Subquery나 Window function 등을 고려해야 할 수 있음.

        statistics_data = []
        annotation_key = ''

        if group_by == 'date':
            annotation_key = 'date_group'
            queryset = queryset.annotate(date_group=TruncDate('event_timestamp')) \
                .values('date_group') \
                .annotate(**aggregation_fields) \
                .order_by('date_group')
            statistics_data = [
                {
                    "date": item['date_group'].isoformat(),
                    "avg_person_count": round(item['avg_person_count'], 1) if item['avg_person_count'] else 0,
                    "avg_congestion_value_raw": round(item['avg_congestion_value_raw'], 3) if item[
                        'avg_congestion_value_raw'] else 0,
                    # "peak_congestion_level": "TODO", # 별도 로직 필요
                } for item in queryset
            ]
        elif group_by == 'hour_of_day':  # 0-23시
            annotation_key = 'hour_group'
            # TruncHour는 날짜까지 포함하므로, ExtractHour 사용 또는 추가 처리 필요
            # 여기서는 시간대별 평균이므로, event_timestamp의 hour 부분만 사용
            queryset = queryset.annotate(hour_group=ExtractHour('event_timestamp')) \
                .values('hour_group') \
                .annotate(**aggregation_fields) \
                .order_by('hour_group')
            statistics_data = [
                {
                    "hour": item['hour_group'],
                    "avg_person_count": round(item['avg_person_count'], 1) if item['avg_person_count'] else 0,
                    "avg_congestion_value_raw": round(item['avg_congestion_value_raw'], 3) if item[
                        'avg_congestion_value_raw'] else 0,
                    # "peak_congestion_level": "TODO",
                } for item in queryset
            ]
        elif group_by == 'day_of_week':  # 1(일요일)-7(토요일) 또는 1(월요일)-7(일요일) (DB, Django 설정에 따라 다름)
            # Django의 ExtractWeekDay: 1 (일요일) to 7 (토요일)
            annotation_key = 'weekday_group'
            queryset = queryset.annotate(weekday_group=ExtractWeekDay('event_timestamp')) \
                .values('weekday_group') \
                .annotate(**aggregation_fields) \
                .order_by('weekday_group')
            # API 명세는 "Monday...Sunday 또는 숫자 1(월요일)...7(일요일)" 언급. 숫자 1=월요일로 가정하고 변환 필요.
            # (d % 7) + 1 로 하면 1(월) ~ 7(일) (단, d가 1=일요일일때 (1%7)+1 = 2가 되어버림. )
            # weekday_map = {1: 'Sunday', 2: 'Monday', ..., 7: 'Saturday'} 또는 숫자 그대로 사용
            statistics_data = [
                {
                    "day_of_week": item['weekday_group'],  # 필요시 문자열(Monday 등) 또는 1(월)~7(일)로 변환
                    "avg_person_count": round(item['avg_person_count'], 1) if item['avg_person_count'] else 0,
                    "avg_congestion_value_raw": round(item['avg_congestion_value_raw'], 3) if item[
                        'avg_congestion_value_raw'] else 0,
                } for item in queryset
            ]
        # 'week', 'month'에 대한 group_by 로직도 유사하게 TruncWeek, TruncMonth 사용 가능

        else:  # 지원하지 않는 group_by 값
            return Response({
                "error_code": "INVALID_PARAMETER",
                "message": f"지원하지 않는 group_by 값입니다: {group_by}. (사용 가능: date, hour_of_day, day_of_week 등)"
            }, status=status.HTTP_400_BAD_REQUEST)

        # --- 비교 데이터 (comparison_data) ---
        # 이 부분은 API 명세에 따라 상당히 복잡한 로직이 될 수 있습니다.
        # 예: "지난주 동시간대", "이전 7일간의 동일 요일별 평균" 등
        # 1학기 범위에서는 이 부분은 생략하거나 매우 단순화된 형태로 제공할 수 있습니다.
        # 여기서는 우선 빈 객체로 응답합니다.
        comparison_data = {
            "reference_period_info": "Comparison data not yet implemented.",
            # "last_week_statistics": [] # 또는 previous_week_daily_average_statistics
        }

        return Response({
            "camera_id": target_camera_id_int if camera_id_param.lower() != 'all' else "all",
            "name": camera_name,
            "date_range_processed": f"{start_date.isoformat()}/{end_date.isoformat()}",
            "group_by": group_by,
            "statistics": statistics_data,
            "comparison_data": comparison_data  # 우선 빈 데이터 또는 미구현 메시지
        }, status=status.HTTP_200_OK)


class ProcessedSnapshotImageView(APIView):
    """
    AI 분석 완료된 스냅샷 이미지를 조회합니다. (GET /snapshots/{snapshot_id}/processed_image/)
    API 명세 옵션 2: 이미지 URL 반환 (JSON)을 기본으로 구현합니다.
    옵션 1 (이미지 직접 반환)을 원할 경우, FileResponse를 사용하도록 수정할 수 있습니다.
    """

    def get(self, request, snapshot_id, format=None):
        try:
            snapshot = Snapshots.objects.select_related('camera').get(snapshot_id=snapshot_id)
        except Snapshots.DoesNotExist:
            return Response({
                "error_code": "NOT_FOUND",
                "message": "해당 스냅샷을 찾을 수 없습니다."
            }, status=status.HTTP_404_NOT_FOUND)

        # 옵션 2: 이미지 URL 반환 (JSON)
        if snapshot.processed_image_path:  # 처리된 이미지 경로가 있는지 확인
            serializer = ProcessedSnapshotImageSerializer(snapshot, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        # elif snapshot.image_path: # 처리된 이미지는 없지만 원본 이미지는 있는 경우 (정책에 따라)
        #     # 이 경우, 원본 이미지 URL을 반환하거나, "처리된 이미지 없음" 메시지 반환
        #     return Response({
        #         "snapshot_id": snapshot.snapshot_id,
        #         "original_image_url": request.build_absolute_uri(f"{settings.MEDIA_URL}{snapshot.image_path}"),
        #         "processed_image_url": None,
        #         "message": "처리된 이미지는 없지만 원본 이미지가 존재합니다."
        #     }, status=status.HTTP_200_OK)
        else:  # 처리된 이미지도, 원본 이미지 경로도 없는 경우 (또는 처리된 이미지만 확인)
            return Response({
                "error_code": "NOT_FOUND",
                "message": "해당 스냅샷에 대한 처리된 이미지를 찾을 수 없습니다 (경로 정보 없음)."
            }, status=status.HTTP_404_NOT_FOUND)

        # # 옵션 1: 이미지 직접 반환 (FileResponse 사용 예시)
        # if snapshot.processed_image_path:
        #     image_full_path = os.path.join(settings.MEDIA_ROOT, snapshot.processed_image_path)
        #     if os.path.exists(image_full_path):
        #         # 파일 확장자에 따라 Content-Type 결정
        #         content_type = 'image/jpeg' # 기본값
        #         if snapshot.processed_image_path.lower().endswith('.png'):
        #             content_type = 'image/png'
        #         # ... 다른 이미지 타입에 대한 처리
        #         return FileResponse(open(image_full_path, 'rb'), content_type=content_type)
        #     else:
        #         return Response({
        #             "error_code": "NOT_FOUND",
        #             "message": "처리된 이미지 파일을 서버에서 찾을 수 없습니다."
        #         }, status=status.HTTP_404_NOT_FOUND)
        # else:
        #     return Response({
        #         "error_code": "NOT_FOUND",
        #         "message": "해당 스냅샷에 대한 처리된 이미지 경로가 없습니다."
        #     }, status=status.HTTP_404_NOT_FOUND)


class AlertListView(ListAPIView):
    """
    최근 또는 특정 조건에 맞는 알림 목록을 조회합니다. (GET /alerts/)
    알림은 CongestionEvents 중 alert_triggered=True 인 경우를 기반으로 구성합니다.
    """
    serializer_class = AlertSerializer
    pagination_class = StandardResultsSetPagination  # 페이지네이션 적용

    def get_queryset(self):
        # CongestionEvents 중 'alert_triggered'=True 이고, 특정 혼잡도 이상인 경우를 알림으로 간주
        # 예: HIGH 또는 VERY_HIGH 수준일 때만 알림으로 표시 (프로젝트 정책에 따라 정의)
        alert_levels = [CongestionLevelLabel.HIGH, CongestionLevelLabel.VERY_HIGH]
        queryset = CongestionEvents.objects.filter(
            alert_triggered=True,
            congestion_level__in=alert_levels  # 예시: 높은 수준의 혼잡만 알림으로
        ).select_related('camera').order_by('-event_timestamp')  # 최신 알림부터

        status_param = self.request.query_params.get('status')
        camera_id_param = self.request.query_params.get('camera_id')

        if status_param:
            if status_param.lower() == 'active':  # 아직 확인(acknowledge)되지 않은 알림
                queryset = queryset.filter(is_acknowledged=False)
            elif status_param.lower() == 'acknowledged':  # 확인된 알림
                queryset = queryset.filter(is_acknowledged=True)
            # 'all' 또는 다른 값은 모든 알림 (위 기본 queryset)

        if camera_id_param:
            try:
                camera_id = int(camera_id_param)
                queryset = queryset.filter(camera_id=camera_id)
            except ValueError:
                # 잘못된 camera_id 형식은 무시하거나 에러 처리
                pass

        return queryset


class AlertAcknowledgeView(UpdateAPIView):
    """
    특정 알림을 확인했음을 시스템에 기록합니다. (POST /alerts/{alert_id}/acknowledge/)
    실제로는 CongestionEvents의 is_acknowledged 필드를 업데이트합니다.
    """
    queryset = CongestionEvents.objects.filter(alert_triggered=True)  # 알림으로 간주되는 이벤트만 대상
    serializer_class = AlertAcknowledgeSerializer
    lookup_field = 'event_id'  # URL 경로에서 alert_id (CongestionEvents.event_id)를 사용

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        # 요청 본문에서 is_acknowledged 값을 가져옴 (True로 강제하거나, 요청 값을 따르거나)
        # API 명세는 본문에 대한 언급이 없으므로, 이 API 호출 자체가 '확인'을 의미한다고 가정.
        # 또는, request.data 에서 {'is_acknowledged': True/False}를 받을 수 있도록 Serializer 수정 가능.
        # 여기서는 호출 시 is_acknowledged = True 로 설정.

        # Serializer의 update 메소드가 is_acknowledged와 acknowledged_at을 처리하도록 함.
        # POST 요청이므로 partial=True를 사용하거나, 모든 필수 필드를 보내야 함.
        # 여기서는 특정 필드만 업데이트하므로 partial=True가 적합할 수 있으나,
        # UpdateAPIView는 기본적으로 PUT을 전체 업데이트로, PATCH를 부분 업데이트로 간주.
        # POST로 이 기능을 구현하려면 APIView를 상속받아 직접 구현하는 것이 더 명확할 수 있음.
        # 여기서는 UpdateAPIView를 사용하되, serializer의 동작에 의존.
        # 명세가 POST 이므로, APIView로 변경하고 직접 처리하는 것이 더 적절해 보임.

        # APIView로 변경하여 POST 처리
        if request.method == 'POST':
            # 이 API는 확인 처리(is_acknowledged=True)만 한다고 가정
            # 만약 확인 취소도 지원하려면 request.data에서 is_acknowledged 값을 받아야 함.
            serializer = self.get_serializer(instance, data={'is_acknowledged': True}, partial=True)
            if serializer.is_valid():
                serializer.save()
                # API 명세 응답 형식에 맞춰 반환 데이터 구성
                response_data = {
                    "alert_id": instance.event_id,
                    "is_acknowledged": instance.is_acknowledged,
                    "acknowledged_at": instance.acknowledged_at.isoformat() if instance.acknowledged_at else None
                }
                return Response(response_data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        else:  # UpdateAPIView는 PUT/PATCH를 기대하므로, POST만 처리하려면 APIView 사용 권장
            return Response({"detail": "Method \"GET\" not allowed."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    # UpdateAPIView를 계속 사용한다면 perform_update를 오버라이드 하거나,
    # 요청 본문에 is_acknowledged 필드를 보내도록 클라이언트와 약속해야 함.
    # def perform_update(self, serializer):
    #     # 이 API는 '확인' 처리만 한다고 가정하고 is_acknowledged를 True로 설정
    #     # serializer.save(is_acknowledged=True, acknowledged_at=timezone.now()) # 이렇게 하면 acknowledged_at도 바로 설정
    #     # 아니면 serializer의 update 메소드에서 처리 (현재 방식)
    #     serializer.save() # validated_data에 is_acknowledged가 있어야 함

    # POST만 지원하도록 APIView로 변경하는 것이 더 명확한 경우:
    # class AlertAcknowledgeView(APIView):
    #     def post(self, request, event_id, format=None):
    #         try:
    #             alert_event = CongestionEvents.objects.get(event_id=event_id, alert_triggered=True)
    #         except CongestionEvents.DoesNotExist:
    #             return Response({"error_code": "NOT_FOUND", "message": "해당 알림을 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

    #         alert_event.is_acknowledged = True # 확인 처리
    #         alert_event.acknowledged_at = timezone.now()
    #         alert_event.save(update_fields=['is_acknowledged', 'acknowledged_at'])

    #         response_data = {
    #             "alert_id": alert_event.event_id,
    #             "is_acknowledged": alert_event.is_acknowledged,
    #             "acknowledged_at": alert_event.acknowledged_at.isoformat() if alert_event.acknowledged_at else None
    #         }
    #         return Response(response_data, status=status.HTTP_200_OK)