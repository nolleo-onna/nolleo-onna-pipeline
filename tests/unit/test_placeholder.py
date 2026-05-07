"""pytest exit code 5(no tests collected) 회피용 placeholder.

CI는 테스트가 0건이면 exit 5를 실패로 처리. 첫 진짜 단위 테스트가
추가되는 시점에 이 파일은 삭제할 것.
"""


def test_placeholder() -> None:
    assert True
