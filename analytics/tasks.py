# analytics/tasks.py
from analytics.services import calculate_and_save_congestion_event

def calculate_congestion_for_snapshot_task(snapshot_id: int):
    """
    주어진 스냅샷에 대한 혼잡도를 계산하고 결과를 저장하는 Celery 작업입니다.
    실제 계산 로직은 analytics.services.calculate_and_save_congestion_event 함수를 호출합니다.
    """
    try:
        # snapshot_id 유효성 검사 등 추가 가능
        if not isinstance(snapshot_id, int):
            print(f"[Congestion Task] 유효하지 않은 snapshot_id 타입: {snapshot_id}")
            return

        print(f"[Congestion Task] Snapshot ID {snapshot_id}에 대한 혼잡도 분석 시작...")
        result_event = calculate_and_save_congestion_event(snapshot_id)

        if result_event:
            print(f"[Congestion Task] Snapshot ID {snapshot_id}의 혼잡도 분석 성공. Event ID: {result_event.event_id}, Level: {result_event.congestion_level}")

    except Exception as e:
        print(f"[Congestion Task] Snapshot ID {snapshot_id} 처리 중 심각한 오류 발생: {e}")
        raise