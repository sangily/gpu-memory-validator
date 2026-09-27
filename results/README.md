# 검증 기록

대표 결과와 원시 증거의 색인이다. 각 `run.json`의 조건·대상 버전·소스 해시와 stdout/stderr를 함께 확인한다.
폴더명 시각은 UTC이며, 저장된 결과는 해당 시점의 코드에 대한 증거다.

| 기록 | 확인 내용 |
|---|---|
| [128/256 MiB 읽기·반전](20260927T144637.446263Z-invert-matrix/matrix.json) | 정상/16회차 주입 네 건, 두 seed×4회×32 검사, 각 CPU 대조 8회 |
| [GPU 읽기·반전 검사](20260927T144247.102175Z-invert-regression/run.json) | 146개; CPU/런타임 46·Python 19·기존 CLI 109·반복 51 등 회귀 로그 포함 |
| [반전 프리셋 GUI](20260927T144249.096566Z-workbench-browser/run.json) | 검사 동작 선택·저장 포함 실제 브라우저 9개 |
| [PyTorch–CUDA 배치 검사](20260927T143507.557698Z-layout-regression/run.json) | 실제 GPU 74개; 비연속·빈 입력·stream·신경망·입력 거부 |
| [의도적 stride 결함](20260927T143523.883373Z-layout-lab/run.json) | 전치 입력 323개 중 279개 불일치, FAIL |
| [배치 수정·비용 비교](20260927T143527.181130Z-layout-lab/run.json) | 두 수정 방식과 PyTorch, 배치별 20회 CUDA event 구간·CPU 대조 |
| [256 MiB 반복 읽기](20260927T133107.035927Z-8000d7a5-experiment/summary.json) | 609.94초, GPU 409,600회·CPU 400회 PASS; 지표 579/581회 성공, 그래프·집계 스크립트 포함 |
| [256 MiB 중간 회차 주입](20260927T134128.392697Z-f4c9c0fb-experiment/summary.json) | 512회차 오류 3건·최초 실패 보존, 후속 정상 묶음 이후에도 최종 FAIL 유지 |
| [GPU 반복 검사](20260927T132823.238763Z-load-regression/run.json) | 51개; CPU/런타임 44·CLI 109·Python 18·GUI 서버 6개 로그 포함 |
| [GPU 반복 설정 GUI](20260927T132749.931160Z-workbench-browser/run.json) | GPU 검사·주입 회차 저장과 기존 결과 조회 등 9개 |
| [128/256 MiB 위치·seed 실험](20260927T125846.124407Z-spatial-matrix/matrix.json) | 2가지 모드×2크기×정상/주입 8개, 각 2패턴×4회 CPU 전체 대조; CTest 41개 로그 포함 |
| [DCGM 실행](20260927T125551.327375Z-dcgm/dcgm_lab.json) | 장치 검색·지표 수집 성공, Level 1 배포 환경 검사 실패(error 20) |
| [위치·seed 패턴 CLI](20260927T125306.432779Z-modular-regression/run.json) | 실제 GPU 경계·주입·기록 한도 포함 109개 |
| [세 모드 프리셋 통합](20260927T125454.883084Z-profile-regression/run.json) | 패턴 JSON→실행기→GPU→독립 대조 9개 |
| [패턴 방식 GUI](20260927T125418.674258Z-workbench-browser/run.json) | seed 패턴 생성·재조회 포함 브라우저 9개 |
| [검증 코어·입력 전체 검사](20260927T091428.416294Z-custom-input-validation/run.json) | CPU 28·런타임/버퍼 10·Python 17·CLI 34·프리셋 통합 5개 통과 |
| [사용자 패턴 CLI](20260927T091434.915971Z-modular-regression/run.json) | 실제 GPU 정상·주입·경계·사용자 패턴 34개 |
| [프리셋→GPU 통합](20260927T091441.670707Z-profile-regression/run.json) | 경로·덮어쓰기·단일/중복 패턴·입력 거부 5개 |
| [GUI](20260927T100952.318546Z-workbench-browser/run.json) | 서버 6개·브라우저 9개, 소스와 화면 캡처 |
| [PyTorch](20260927T102414.578693Z-pytorch-validation/run.json) | CPU 대조 4개·실행 경로 4개, 원시 예외와 수치 비교 |
| [성능 비교](20260927T085149.505158Z-host-buffer-comparison/run.json) | 128/256 MiB 각 버전 10회, 전체 시간 중앙값 40.9%/43.1% 감소 |
| [128 MiB 정상](20260927T085019.212400Z-2db5cbad-experiment/run.json) | 네 패턴×4회, CPU 전체 대조 PASS |
| [256 MiB 오류 주입](20260927T085529.806146Z-70ae317b-experiment/run.json) | 큰 배열의 주입 검출과 후속 정상 패턴·반복 |
| [실행기 시간 초과](20260927T081632.558840Z-63426f9e-experiment/run.json) | ERROR / TIMEOUT |
| [GPU 비가시 실행](20260927T081632.934876Z-4514f3ad-experiment/run.json) | ERROR / VALIDATOR_ERROR |
| [Sanitizer 실행](20260920T070753Z-first-kernel/run.json) | CUDA 예제 실행 성공, Sanitizer는 WDDM 환경 오류로 미검증 |

단계별 원시 기록과 소스 사본은 그대로 보존한다. 일반 실행은 Git에서 제외하며 필요한 증거만 선택해 포함한다.
재현 명령은 [테스트](../docs/TESTING.md), 측정 해석은 [성능 비교](../docs/PERFORMANCE.md)를 따른다.
