# 실험 실행과 결과 기록

실행기는 빌드된 CUDA 프로그램을 실행하고 환경·설정·원시 결과·GPU 지표를 저장한다.
패턴과 프리셋의 정의는 [입력 설정](INPUTS.md)을 따른다.

## 실행

```bash
source cuda-env.sh
cmake --build build/cuda
python3 scripts/run_experiment.py --count 1048576 --iterations 64
python3 scripts/run_experiment.py --count 257 --max-records 2 --iterations 3 --inject
```

각 실행은 UTC 시각과 식별자로 새 폴더를 만들며 `run_dir=`로 경로를 출력한다.
1,048,576개 원소는 4 MiB다. 반복 횟수와 동시에 할당한 메모리 크기를 구분한다.

| 실행기 옵션 | 기본값 | 의미 |
|---|---|---|
| `--timeout-seconds` | 60 | 자식 프로세스 실행 제한; 환경·소스 수집 제외 |
| `--sample-interval` | 1 | GPU 조회 시작 사이 목표 간격(초) |
| `--telemetry` / `--no-telemetry` | 활성 | GPU 지표 수집 여부 |
| `--binary` | build/cuda/gpu_memory_validator | 실행 파일 |
| `--output-root` | results/ | 결과 저장 위치 |

## 저장 파일

| 파일 | 내용 |
|---|---|
| `run.json` | 명령·설정·환경·Git 상태·소스/바이너리 해시·상태·종료 원인·실행 시간 |
| `resolved_config.json` | CLI 덮어쓰기를 반영한 설정과 정규화 패턴 목록 |
| `inputs/profile.json`, `inputs/patterns.json` | 사용한 입력 파일의 원문 사본; 파일 입력 시 생성 |
| `stdout.txt`, `stderr.txt` | 자식 프로세스의 원시 출력 |
| `telemetry.jsonl` | 시각·조회 시간·원시 응답·GPU UUID·지표별 값/가용성 |
| `source/` | 수집 시점의 코드·테스트 사본 |

입력은 한 번 읽은 내용으로 검증·해석·사본 저장한다. 이후 원본을 편집해도 실행 당시 조건은 보존된다.
소스와 바이너리의 해시는 각각 기록하며 실행기가 자동 빌드하지는 않는다. 변경한 소스를 실행하려면 먼저 빌드한다.

## 상태와 중단

| 상황 | 실험 상태 / 원인 | 종료 코드 |
|---|---|---:|
| 불일치 없이 완료 | PASS / COMPLETED | 0 |
| 데이터 불일치를 검출하고 완료 | FAIL / COMPLETED | 1 |
| CUDA 프로그램의 실행 오류 | ERROR / VALIDATOR_ERROR | 2 |
| 시간 초과 | ERROR / TIMEOUT | 2 |
| Ctrl+C 또는 SIGTERM | ERROR / INTERRUPTED | 2 |
| 종료 코드·요약·완료 개수 불일치 | ERROR / INVALID_RESULT | 2 |
| 실행 파일 누락 등 | ERROR / RUNNER_ERROR | 2 |

PASS/FAIL에는 종료 코드·최종 요약 상태의 일치와 `완료 개수 = 패턴 수 × 반복 횟수`를 요구한다.
오류 주입의 예상 결과도 실험 기록에는 FAIL로 남긴다. 테스트가 그 결과를 기대해 통과한 것과 구분한다.

Linux/WSL에서 시간 초과·중단 시 자식 프로세스 그룹에 SIGTERM을 보내고 2초 후에도 남으면 SIGKILL한다.
종료 관찰 주기와 정리 시간 때문에 제한 시각보다 늦게 끝날 수 있다. 자식의 실제 종료 코드는 별도로 기록한다.
C++ 결과는 종료 시 출력되므로 강제 중단 시 로그가 비어 있을 수 있다. 완료 개수를 추정하지 않는다.
실행기 자체가 강제 종료되면 RUNNING 기록이 남을 수 있으며 이는 완료 증거가 아니다.

## 지표와 시간 해석

온도·전력·SM/메모리 클록·전체/사용 메모리를 nvidia-smi로 조회한다.
값은 AVAILABLE, 미지원은 UNAVAILABLE/null, 조회·파싱 실패는 ERROR로 기록한다.
요약에는 PARTIAL·NOT_SAMPLED·DISABLED도 사용하며 누락을 0으로 대체하지 않는다.
조회당 timeout은 3초이고 정확히 1Hz를 보장하지 않으므로 실제 시각과 조회 시간을 함께 저장한다.

조회되는 GPU 목록은 CUDA_VISIBLE_DEVICES와 다를 수 있다. UUID로 장비를 확인해야 하며,
여러 GPU 중 검사 장비를 자동 연결하지 않는다. 지표는 조회 시점의 관측값으로 커널별 추적이나 최대치 보장이 아니다.

`process_elapsed_seconds`는 자식 프로세스 시작 준비부터 종료 관찰까지의 시간이다.
CUDA 초기화·CPU 전체 대조·출력·종료 확인을 포함하고, 환경 수집·종료 후 모니터링 정리는 제외한다.
GPU 커널 시간이나 메모리 대역폭으로 해석하지 않는다. [성능 비교](PERFORMANCE.md)는 별도 측정 절차를 사용한다.
