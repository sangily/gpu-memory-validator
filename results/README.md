# 저장한 실행 기록

각 폴더의 `run.json`과 원시 stdout/stderr를 함께 확인한다. 폴더명은 실제 실행한
UTC 시각이다. 아래 기록들은 2026-09-20에 개발 변경분을 정리하면서 Git에 추가했다.

| 기록 | 확인 내용 |
| --- | --- |
| [첫 빌드](20260920T070711Z-first-kernel/run.json) | CUDA 라이브러리 검색 경로 문제로 빌드 실패 |
| [첫 커널 실행](20260920T070753Z-first-kernel/run.json) | 경로 보완 후 1,000개 원소 검사 PASS, Compute Sanitizer 환경 오류 |
| [오류 주입 CLI](20260920T100111Z-injection-cli/run.json) | index 패턴의 정상 실행 0, 오류 주입 1, 잘못된 옵션 2 |
| [자동 회귀 테스트](20260920T132441.254349Z-regression/run.json) | 네 가지 고정 패턴, GPU 오류 기록, CPU 대조 및 세 실행 경우 PASS |
| [CPU 대조 단위 검사](20260920T140308.885397Z-reference-unit/run.json) | CUDA 없이 실행하는 정상·잘린 기록·오염·중복·누락 등의 15개 검사 PASS |
| [모듈 분리 후 CLI 검사](20260920T140315.464695Z-modular-regression/run.json) | 새 실행 파일을 기존 CLI 검사 기준으로 확인한 세 경우 PASS |
| [CLI·상태 단위 검사](20260921T060557.827757Z-application-unit/run.json) | 기존 대조 15개와 인자·상태 우선순위 5개, 총 20개 PASS |
| [CLI·출력 분리 후 GPU 검사](20260921T060557.980593Z-modular-regression/run.json) | 기존 판정 기준으로 새 main의 실제 GPU 실행 세 경우 PASS |

이전 기록의 프로그램은 당시 기능 범위에 해당한다. 소스 사본이 있는 경우 그 파일과
로그를 함께 읽는다. 현재 프로그램의 사용법과 제한은 상위 README에 정리했다.

앞서 수동으로 확인한 기록 한도 초과와 상세 기록 변조 검사는 대화에서 결과를
확인했으며, 이 폴더에 별도의 원시 실행 로그가 저장되어 있지는 않다.
