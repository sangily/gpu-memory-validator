# 실험 실행과 결과 기록

2026-09-27. 실행기는 이미 빌드된 validator를 실행하고 환경·설정·원시 로그·시각·상태를 저장한다.
판정 테스트와 실제 실험을 구분한다. `--inject` 실행에서 도구의 FAIL/종료 1은 예상한 결과지만,
실험 기록 자체의 상태를 PASS로 바꾸지는 않는다.

## 실행

```bash
source cuda-env.sh
cmake --build build/cuda
python3 scripts/run_experiment.py --count 1048576 --iterations 64
python3 scripts/run_experiment.py --count 257 --max-records 2 --iterations 3 --inject
```

count는 32-bit 원소 개수다. 1,048,576개는 4 MiB이며 전체 VRAM 검사량이 아니다.
CUDA 프로그램의 입력 외에 다음 실행기 옵션이 있다.

- `--timeout-seconds 60`: 자식 실행 구간의 제한 시간. 준비 단계의 소스/환경 수집은 제외한다.
  종료를 확인하는 주기와 최대 2초의 정상 종료 대기로 실제 종료가 제한 시각보다 늦을 수 있다.
- `--sample-interval 1`: 모니터링 조회 시작 사이 목표 간격(초). 각 조회에는 3초 timeout이 있다.
  조회가 오래 걸리면 정확히 1Hz를 보장하지 않는다. 실제 시각과 조회 소요 시간을 저장한다.
- `--no-telemetry`: 모니터링을 끈다. DISABLED로 기록한다.
- `--binary PATH`, `--output-root PATH`: 실행 파일과 결과 저장 위치 지정.

각 실행은 UTC 시각과 임의 식별자로 새 폴더를 만든다. 콘솔의 `run_dir=`에서 찾는다.

| 파일 | 내용 |
|---|---|
| `run.json` | 설정, 명령, OS/Python/Toolkit, CUDA 가시성 설정, Git 상태, 소스/실행 파일 해시, 실행 상태·원인·종료 코드·소요 시간 |
| `stdout.txt`, `stderr.txt` | 자식 프로세스가 실제 출력한 원문 |
| `telemetry.jsonl` | 조회별 UTC 시각·상대 시간·조회 시간·원시 응답·GPU UUID·지표별 값과 가용성 |
| `source/` | 수집 당시 코드·테스트 사본 |

소스 사본과 실행 파일 해시는 각각 수집한다. 실행기가 빌드하지 않으므로 현재 소스로 만든
실행 파일인지는 해시 두 개만으로 보장하지 못한다. 위 예제처럼 먼저 빌드한다.
Git 작업 트리가 dirty여도 실행을 허용하고 상태와 실제 사본을 남긴다.

## 종료와 결과 신뢰성

실행 전에 `run.json`을 RUNNING으로 기록하고 종료 후 임시 파일 교체 방식으로 갱신한다.
PASS/FAIL로 인정하려면 종료 코드가 각각 0/1이고, 마지막 요약 상태가 일치하며,
완료한 패턴 수가 요청한 반복 횟수 × 4여야 한다. 이 확인은 별도 회귀 테스트의
원소·기록 내용 검사 전체를 대신하지 않는다.

| 상황 | 실험 상태 / 원인 | 실행기 종료 코드 |
|---|---|---:|
| 정상 검사 완료 | PASS / COMPLETED | 0 |
| 데이터 불일치를 보고하고 완료 | FAIL / COMPLETED | 1 |
| validator가 실행 오류 보고 | ERROR / VALIDATOR_ERROR | 2 |
| 시간 초과 | ERROR / TIMEOUT | 2 |
| Ctrl+C 또는 SIGTERM | ERROR / INTERRUPTED | 2 |
| 종료 0이지만 요약 누락·불일치 | ERROR / INVALID_RESULT | 2 |
| 실행 파일 누락 등 실행기 오류 | ERROR / RUNNER_ERROR | 2 |

시간 초과나 중단이면 자식 프로세스 그룹에 SIGTERM을 보내고, 2초 뒤에도 종료하지 않으면
SIGKILL로 정리한다. 실제 자식 종료 코드는 별도로 보존한다. 예를 들어 -15는 종료 신호에
의한 자식 종료이며, 실행기의 ERROR/2와 구분한다. Linux/WSL 환경을 대상으로 한다.

현재 C++ 도구는 모든 결과를 메모리에 모았다가 정상 종료 또는 처리 가능한 오류 이후 출력한다.
따라서 강제 중단 시 stdout이 비어 있어도 이미 내부에서 수행한 검사가 없었다는 뜻은 아니다.
실행기는 받은 출력만 보존하고 완료 개수를 추정하지 않는다. iteration별 실시간 결과 저장은
아직 구현하지 않았다. 실행기 자체가 SIGKILL되거나 OS가 중단되면 RUNNING 기록이 남을 수 있다.
이 상태는 완료 증거가 아니다.

## 모니터링과 시간 해석

현재 조회 항목은 온도(°C), 전력(W), SM/메모리 클록(MHz), 전체/사용 메모리(MiB)다.
값을 얻으면 AVAILABLE, N/A 등은 UNAVAILABLE과 null, 파싱/조회 실패는 ERROR로 기록한다.
일부만 수집하면 요약은 PARTIAL이며, 조회 전에 종료되면 NOT_SAMPLED다. 0으로 대체하지 않는다.

`nvidia-smi`가 보여주는 모든 GPU를 UUID와 함께 저장한다. 이 목록은 자식 프로세스의
CUDA_VISIBLE_DEVICES와 다를 수 있다. 모니터링 성공은 validator 실행 성공을 의미하지 않는다.
현재 단일 RTX 3060 환경에서는 장비를 확인할 수 있으며, 여러 GPU의 자동 연결은 구현하지 않았다.
샘플은 조회 구간의 관측값이며 커널별 추적·최댓값·평균 전력의 완전한 측정이 아니다.

`process_elapsed_seconds`는 프로세스 시작 준비부터 종료 관찰까지의 monotonic 시간이다.
CUDA 초기화·전체 CPU 대조·결과 출력·종료 확인 주기를 포함하며 GPU 커널 시간과 구분한다.
소스/환경 수집 및 종료 후 모니터링 스레드 정리 시간은 제외한다. 모니터링 자체의 부하는
존재하므로 변경 전후 성능 비교에서는 동일한 수집 설정을 유지해야 한다.

## 테스트

```bash
python3 -m unittest discover -s tests/runner -v
```

10개 검사: 요약/종료 계약, 정상/FAIL 전달, 종료 0인데 요약 없음, 시간 초과와 강제 종료,
SIGINT와 자식 정리, 실행 파일 누락, 지표 N/A/오류, 조회 명령 없음, 조회 실패, 샘플 전 중단.
합성 자식 프로세스와 주입한 조회 응답을 사용하며 실제 GPU 장애 재현으로 표현하지 않는다.
실제 validator를 사용한 정상/주입/시간 초과/GPU 비가시 실행 증거는 results 목록에서 확인한다.
