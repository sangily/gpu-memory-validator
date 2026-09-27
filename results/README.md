# 저장한 실행 기록

각 폴더의 `run.json`과 원시 stdout/stderr를 함께 확인한다. 폴더명은 실제 실행한
UTC 시각이다. 아래 기록들은 2026-09-20에 개발 변경분을 정리하면서 Git에 추가했다.

| 기록 | 확인 내용 |
| --- | --- |
| [PyTorch 장치 오류 실습](20260927T102414.578693Z-pytorch-validation/run.json) | CPU 대조 4개·실행 경로 4개 PASS; 장치 불일치·반환값 누락·수정·GPU 비가시 상태, 수치 오차와 원시 예외 보존 |
| [로컬 GUI 검사](20260927T100952.318546Z-workbench-browser/run.json) | Chromium 9개·서버 6개 PASS; 소스 해시·실제 결과 화면·격리된 편집 화면 보존 |
| [사용자 패턴·프리셋 전체 검사](20260927T091428.416294Z-custom-input-validation/run.json) | CPU 28·런타임/버퍼 10·Python 17·CLI 34·프리셋 통합 5개 PASS; 전체 코드/입력 사본 및 해시 |
| [사용자 패턴 CLI 검사](20260927T091434.915971Z-modular-regression/run.json) | 단일/중복/비영 상수 목록의 정상·주입 및 기존 경계 검사 등 34개 PASS |
| [프리셋→실제 GPU 통합](20260927T091441.670707Z-profile-regression/run.json) | 다른 cwd, 설정 덮어쓰기, 중복/단일 패턴, 잘못된 파일 거부 등 5개 PASS |
| [CPU 버퍼 재사용 성능 비교](20260927T085149.505158Z-host-buffer-comparison/run.json) | 128/256 MiB, 각 버전 10회 + 준비 1회; 전체 시간 중앙값 40.9%/43.1% 감소. 모든 실행 정확성 확인 |
| [재사용 후 코어 검사](20260927T085114.800218Z-buffer-reuse-regression/run.json) | CPU 25개·런타임/버퍼 10개 및 CLI 26개 PASS |
| [재사용 후 CLI 검사](20260927T085118.116762Z-modular-regression/run.json) | 재사용으로 이전 패턴/반복 값이 남지 않는지 포함한 기존 26개 PASS |
| [기준 128 MiB 정상](20260927T085019.212400Z-2db5cbad-experiment/run.json) | 네 패턴×4회, 전체 CPU 대조 PASS |
| [기준 128 MiB 주입](20260927T085023.620221Z-aa65cdce-experiment/run.json) | 오류 3·기록 2·2회 반복, 종료 1 및 독립 CLI 대조 확인 |
| [변경 256 MiB 주입](20260927T085529.806146Z-70ae317b-experiment/run.json) | 큰 배열의 주입 후 정상 패턴/반복, 종료 1 및 독립 CLI 대조 확인 |
| [실험 실행기 검증](20260927T081626.772355Z-runner-validation/run.json) | 합성 프로세스/응답 테스트 10개 및 실제 validator 네 실행 경로 확인 |
| [실험 실행기: normal](20260927T081630.255797Z-86f2b24a-experiment/run.json) | PASS / COMPLETED; 설정·코드/실행 파일 해시·원시 로그·모니터링 보존 |
| [실험 실행기: injected](20260927T081632.002658Z-c4e643f7-experiment/run.json) | FAIL / COMPLETED; 설정·코드/실행 파일 해시·원시 로그·모니터링 보존 |
| [실험 실행기: timeout](20260927T081632.558840Z-63426f9e-experiment/run.json) | ERROR / TIMEOUT; 설정·코드/실행 파일 해시·원시 로그·모니터링 보존 |
| [실험 실행기: no_device](20260927T081632.934876Z-4514f3ad-experiment/run.json) | ERROR / VALIDATOR_ERROR; 설정·코드/실행 파일 해시·원시 로그·모니터링 보존 |
| [설정·반복 단위 및 런타임 검사](20260927T024926.964073Z-configuration-tests/run.json) | CPU 25개, 런타임·버퍼 10개 PASS. CLI 26개 실행 결과도 기록 |
| [설정·반복 CLI 회귀 검사](20260927T024929.746503Z-modular-regression/run.json) | 원소 1/2/3/255/256/257/1024/1025, K=0/1/2/4, 2~3회 반복, 기존 오류 경로 등 26개 PASS |
| [첫 빌드](20260920T070711Z-first-kernel/run.json) | CUDA 라이브러리 검색 경로 문제로 빌드 실패 |
| [첫 커널 실행](20260920T070753Z-first-kernel/run.json) | 경로 보완 후 1,000개 원소 검사 PASS, Compute Sanitizer 환경 오류 |
| [오류 주입 CLI](20260920T100111Z-injection-cli/run.json) | index 패턴의 정상 실행 0, 오류 주입 1, 잘못된 옵션 2 |
| [자동 회귀 테스트](20260920T132441.254349Z-regression/run.json) | 네 가지 고정 패턴, GPU 오류 기록, CPU 대조 및 세 실행 경우 PASS |
| [CPU 대조 단위 검사](20260920T140308.885397Z-reference-unit/run.json) | CUDA 없이 실행하는 정상·잘린 기록·오염·중복·누락 등의 15개 검사 PASS |
| [모듈 분리 후 CLI 검사](20260920T140315.464695Z-modular-regression/run.json) | 새 실행 파일을 기존 CLI 검사 기준으로 확인한 세 경우 PASS |
| [CLI·상태 단위 검사](20260921T060557.827757Z-application-unit/run.json) | 기존 대조 15개와 인자·상태 우선순위 5개, 총 20개 PASS |
| [CLI·출력 분리 후 GPU 검사](20260921T060557.980593Z-modular-regression/run.json) | 기존 판정 기준으로 새 main의 실제 GPU 실행 세 경우 PASS |
| [자원·런타임 오류 처리](20260921T135033.744131Z-runtime-cleanup/run.json) | CPU 20개와 제어된 반환값 오류 주입·실제 자원 추적 등의 런타임 8개 PASS |
| [GPU 비가시 상태 포함 CLI 검사](20260921T135040.526430Z-modular-regression/run.json) | 기존 세 경우와 cudaErrorNoDevice 경로, 총 네 경우 PASS |

이전 기록의 프로그램은 당시 기능 범위에 해당한다. 소스 사본이 있는 경우 그 파일과
로그를 함께 읽는다. 현재 프로그램의 사용법과 제한은 상위 README에 정리했다.

앞서 수동으로 확인한 기록 한도 초과와 상세 기록 변조 검사는 대화에서 결과를
확인했으며, 이 폴더에 별도의 원시 실행 로그가 저장되어 있지는 않다.
