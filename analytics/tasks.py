from datetime import datetime
from analytics.services import calculate_and_save_congestion_event

def log_with_time(message: str):
    """시간과 함께 로그 메시지를 출력합니다."""
    current_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{current_time}] {message}")


def calculate_congestion_for_snapshot_task(snapshot_id: int):
    """
    주어진 스냅샷에 대한 혼잡도 계산 서비스 함수를 호출하는 비동기 작업 래퍼입니다.
    실제 계산 및 상세 로깅은 services.calculate_and_save_congestion_event 함수에서 처리됩니다.
    """
    log_prefix = f"[CONG-WRAPPER|S-ID:{snapshot_id}]"

    try:
        # 이 래퍼 태스크는 서비스 호출만 담당하므로 로그는 최소화합니다.
        log_with_time(f">> {log_prefix} 밀집도 분석 서비스 호출 시작")

        if not isinstance(snapshot_id, int) or snapshot_id <= 0:
            log_with_time(f"[ERROR] {log_prefix} 유효하지 않은 snapshot_id '{snapshot_id}' (타입: {type(snapshot_id)})")
            return

        # 실제 로직과 상세 로깅을 담당하는 서비스 함수를 호출합니다.
        calculate_and_save_congestion_event(snapshot_id)

        # 성공/실패에 대한 상세 로그는 서비스 함수에서 출력되므로 여기서는 호출 완료만 기록합니다.
        log_with_time(f"<< {log_prefix} 밀집도 분석 서비스 호출 완료")

    except Exception as e:
        # 이 래퍼 수준에서 예외가 발생한 경우에만 기록합니다 (예: 서비스 함수를 찾지 못하는 경우).
        # 서비스 내부의 예외는 서비스 함수에서 이미 로깅됩니다.
        log_with_time(f"[ERROR] {log_prefix} 작업 실행 중 예외 발생: {e}")
        # 태스크 큐가 실패를 인지하고 재시도 등을 처리할 수 있도록 예외를 다시 발생시킵니다.
        raise