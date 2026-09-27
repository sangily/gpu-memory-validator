# gpu-memory-validator

CUDA 기반 GPU 메모리 검증 학습 프로젝트. 기본 네 패턴과 사용자 지정 상수의 쓰기·검증 커널,
별도 XOR 오류 주입, GPU 오류 카운터와 최대 K건의 상세 기록을 구현했다.
CPU 전체 검사 결과로 GPU 오류 개수와 기록을 대조한다.
원소 수·기록 한도·반복 횟수를 설정할 수 있으며, 경계 회귀 검사와 별도로 128/256 MiB의 정상·주입 실행 및 조건을 통제한 성능 비교를 수행했다.

최종 범위와 책임별 분리안은 [프로젝트 정의와 구조 설계](docs/PROJECT.md)에 정리했다.
현재 CLI(`src/cli.cpp`), GPU 실행(`src/validator.cu`), CPU 대조(`src/reference.cpp`),
출력(`src/report.cpp`)을 분리했다. `src/main.cpp`는 설정 읽기 → 실행 → 출력 → 종료를 연결한다.
GPU 버퍼는 RAII로 소유하고, CUDA 오류 시 완료된 패턴과 실패 원인을 반환한다.
기존 `examples/first_kernel.cu`는 학습 기준 버전으로 보존한다.

## 로컬 실험 화면

```bash
python3 scripts/workbench.py
```

브라우저에서 http://127.0.0.1:8765 에 접속한다. Python 표준 라이브러리만으로 실행한다.
패턴·프리셋을 생성/편집/저장하고 실행 명령을 복사할 수 있다. 결과 화면에서는 저장된
PASS/FAIL/ERROR, 실행 조건, 원시 로그, GPU 지표를 조회한다. GPU 실험은 복사한 CLI 명령으로 실행한다.

![실험 결과 화면](results/20260927T100952.318546Z-workbench-browser/results.png)

화면은 실제 128 MiB 실험 기록을 복사한 테스트 공간에서 촬영했다.
[사용법·책임 분리·테스트 근거](docs/GUI.md)에 구현 범위와 재현 방법을 정리했다.

## 새 실행 파일 빌드와 테스트

CPU 단위 테스트는 CUDA Toolkit이나 GPU 없이 실행할 수 있다.

```bash
cmake -S . -B build/cpu -DGMV_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpu
ctest --test-dir build/cpu --output-on-failure
```

현재 CPU 단위 테스트는 28개다. [CPU 대조 15개](tests/unit/test_reference.cpp)는
정상 패턴, 기록 순서·잘림, 잘못된 값·위치·개수, 중복·누락, 상태 독립성을 확인한다.
[CLI·상태 판정 13개](tests/unit/test_application.cpp)는 기본 설정, 주입 옵션,
입력 형식·상한·중복·누락 거부와 ERROR > FAIL > PASS 우선순위를 확인한다.

실제 GPU 실행 파일과 CLI 회귀 검사는 다음과 같이 실행한다.

```bash
source cuda-env.sh
cmake -S . -B build/cuda -DGMV_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build/cuda
ctest --test-dir build/cuda -L gpu --output-on-failure
python3 tests/cli/test_validator.py
./build/cuda/gpu_memory_validator --inject
```

런타임·버퍼 검사 10개와 직접 CLI 검사 34개가 있다. CPU만 수행하는 입력·버퍼 경계 검사도
런타임 대상에 포함되어 있으므로 10개 모두 커널 실행 검사라는 뜻은 아니다.
CLI 검사는 정상 0, 주입 1, 잘못된 옵션 2를 기대한다. GPU 비가시 상태 검사는
해당 자식 프로세스에만 `CUDA_VISIBLE_DEVICES`를 빈 값으로 지정하고 실제 CUDA 오류와
종료 코드 2를 확인한다. 마지막 직접 주입 실행의 종료 코드 1은 의도한 데이터 FAIL이다.
CUDA 아키텍처 기본값은 실측 장비인 RTX 3060의 86이며 다른 장비는 CMake 설정으로 변경한다.

`check_reference()`는 GPU 오류 개수와 원본 데이터를 독립 대조하고, 기록 수가
`min(실제 오류 수, 기록 한도)`인지도 확인한다. 기록이 잘리면 어떤 오류 부분집합이든
유효하지만 중복·잘못된 값은 허용하지 않는다. CPU 상세 기록도 한도로 제한하고
전체 CPU 오류 수는 모든 원소를 검사해 계산한다.

검사 결과는 GPU 포인터가 없는 `RunResult`/`PatternResult`로 전달한다. 출력 모듈은
이미 판정한 결과를 표현하며 상태를 다시 계산하지 않는다. 정상 종료 또는 처리 가능한
실행 오류 이후 결과를 출력한다. 완료된 패턴만 결과 목록에 추가하며, 중간 오류는
`run_status=ERROR completed_patterns=N`과 호출명·CUDA 코드·패턴을 함께 기록한다.
C++의 장시간 실행 중 점진적 저장은 후속 작업이다. 아래 Python 실행기는 중단과 시간 초과를 구분한다.

## 크기·기록 한도·반복 설정 — 2026-09-27

```bash
./build/cuda/gpu_memory_validator --count 257 --max-records 2 --iterations 3 --inject
echo "exit_code=$?"
```

| 옵션 | 의미 | 기본값 / 범위 |
|---|---|---|
| `--count N` | 32-bit 원소 개수; 바이트 수는 N × 4 | 1025 / 1~UINT_MAX, 바이트 수 표현 가능 범위 |
| `--max-records K` | 패턴별 GPU·CPU 상세 기록 한도; 전체 오류 수는 제한하지 않음 | 3 / 0~UINT_MAX, 기록 바이트 수 표현 가능 범위 |
| `--iterations N` | 선택한 패턴 목록 전체를 검사하는 횟수 | 1 / 1~10000 |
| `--inject` | 첫 반복의 첫 패턴에만 XOR 주입 | 기본 비활성 |

십진 정수만 받으며 음수·부호·소수·남는 문자·범위 초과·중복 옵션은 GPU 실행 전에
사용법과 종료 코드 2로 거부한다. 파싱 가능한 크기라도 실제 메모리 할당 성공을 보장하지는 않는다.
반복 상한 10000은 결과를 종료 시까지 보관하는 현재 구조의 도구 정책이다.
원소 수 상한은 모든 원소가 불일치할 때도 unsigned int 오류 카운터가 넘치지 않도록 정했다.

주입 후보는 `[0, count/2, count-1]`, XOR mask는 `[1, 3, 1]`이다.
겹치는 위치는 처음 나온 후보만 사용한다. 따라서 count=1은 `{0:1}`, count=2는
`{0:1, 1:3}`으로 변조한다. XOR가 중복 적용되어 의도한 변조가 바뀌는 일을 방지한다.

위 예제에서는 첫 반복의 첫 패턴에서 오류 3건·상세 2건·truncated=true가 나오고,
나머지 11개 패턴 검사는 정상이다. GPU 상세는 실행 순서에 따라 서로 다른 두 위치일 수 있다.
CPU 전체 대조는 모든 패턴에서 수행한다. 마지막은 `run_status=FAIL completed_patterns=12`,
종료 코드는 1이다. 각 패턴의 카운터는 새로 초기화하지만 전체 FAIL은 이후 PASS로 지우지 않는다.

반복 도중 실행 오류가 나면 완료된 결과와 실패한 iteration/pattern을 보존한다.
장시간 안정성은 아직 확인하지 않았다. 성능 비교 및 실행기 확인 결과를 포함한 검증 근거는
[테스트 전략](docs/TESTING.md)과 [실행 기록](results/README.md)에 있다.

## 실험 실행기 — 2026-09-27

```bash
source cuda-env.sh
python3 scripts/run_experiment.py --count 1048576 --iterations 64
python3 scripts/run_experiment.py --count 257 --max-records 2 --iterations 3 --inject
```

콘솔에 표시된 `run_dir`에 `run.json`, 원시 stdout/stderr, `telemetry.jsonl`, 코드 사본을 저장한다.
정상은 종료 0, 데이터 불일치는 1, 시간 초과·중단·실행 오류는 2다. 약 1초 간격으로
제공되는 온도·전력·클록·메모리 지표를 조회하며 N/A와 조회 오류를 별도로 기록한다.

`--timeout-seconds`로 실행 시간을 제한하고 Ctrl+C로 중단할 수 있다. 현재 C++ 도구는 종료 시
결과를 출력하므로 강제 중단 시 패턴 결과가 없을 수 있다. 실행기는 받은 로그와 중단 원인을
보존한다. 실행 시간은 프로세스 전체 구간이며 커널 시간이나 메모리 대역폭이 아니다.
[실행·스키마·상태·한계](docs/EXPERIMENTS.md)에 측정 범위를 정리했다.

```bash
python3 -m unittest discover -s tests/runner -v
```

실행기의 10개 검사는 합성 자식/조회 응답을 사용한다. 실제 GPU에서는 정상·주입·시간 초과·
GPU 비가시 상태의 네 경로도 확인했다. 4 MiB의 64회 반복은 실행기 동작 확인이며
대용량·장시간 안정성이나 성능 개선을 입증하는 실험은 아니다.

## 사용자 지정 패턴과 실험 프리셋 — 2026-09-27

패턴 정의는 `patterns/`, 크기·반복·주입 등의 실험 조건은 `profiles/`에 저장한다.
각 사용자 지정 상수로 전체 영역을 채우고 GPU 검사와 CPU 전체 대조를 수행한다.

```bash
python3 scripts/run_experiment.py --profile profiles/custom-smoke.json
python3 scripts/run_experiment.py --profile profiles/custom-smoke.json --no-inject
```

첫 명령은 의도한 주입 FAIL/종료 1, 두 번째는 정상 PASS/종료 0이다. CLI 값이 프리셋보다
우선하며 원본 파일을 수정하지 않는다. 결과에는 원본 사본과 최종 설정/패턴 목록을 함께 저장한다.
[JSON 형식·경로·우선순위·재현 방법](docs/INPUTS.md)에 정리했다. GUI에서도 같은 파일을 편집하고 저장할 수 있다. [화면 사용법](docs/GUI.md)을 참고한다.

기존 실행기 10개에 설정 검사 7개를 더한 Python 17개와 실제 프리셋→GPU 통합 검사 5개가 있다.

```bash
python3 -m unittest discover -s tests/runner -v
python3 tests/cli/test_profiles.py
```

## 동일 검사 조건의 성능 비교 — 2026-09-27

CPU 스냅샷 버퍼를 패턴마다 새로 할당하는 대신 실행 동안 재사용했다.
GPU 커널·전체 데이터 복사·CPU 전체 대조·오류 판정·출력은 유지했다.

| 조건 | 기존 중앙값 | 변경 중앙값 | 전체 시간 감소 |
|---|---:|---:|---:|
| 128 MiB, 네 패턴 × 4회 | 3.736초 | 2.208초 | 40.9% |
| 256 MiB, 네 패턴 × 4회 | 7.272초 | 4.135초 | 43.1% |

각 조건/버전 10회, 준비 실행 제외, AB/BA 교대, 모든 표본 보존. 모든 성능 실행의 결과를
독립 CLI 검사 함수로 확인했다. CUDA 초기화·CPU 작업 등을 포함한 프로세스 전체 시간이며
GPU 커널 속도나 메모리 대역폭 개선 수치가 아니다.
[변경 코드·조건·원시 표본·그래프](docs/PERFORMANCE.md)에 해석 범위와 재현 명령을 정리했다.

## PyTorch 장치 오류 실습 — 2026-09-27

작은 `Linear → ReLU` GPU 추론에서 CPU/GPU 장치 불일치와 `.to()` 반환값 누락을 재현했다.
입력 전달을 수정한 뒤 출력 1,024개를 CPU float64 기준과 허용 오차 내에서 대조한다.

```bash
build/torch-env/bin/python experiments/pytorch/device_lab.py --case device-mismatch
build/torch-env/bin/python experiments/pytorch/device_lab.py --case fixed
build/torch-env/bin/python tests/pytorch/check_device_lab.py
```

첫 명령은 의도한 ERROR·종료 2다. 자동 검사는 CPU 대조 함수 4개와 실제 실행 경로 4개를 확인한다.
[원인·수정 코드·수치 기준·환경 구성](docs/PYTORCH.md)에 설명했다. 기존 메모리 검증과 별도 실습이며
AI 학습·성능 개선이나 하드웨어 결함 검증을 수행했다는 의미는 아니다.

## GPU 자원과 중간 실패

`DeviceBuffer<T>`는 생성 시 할당하고 소멸 시 해제를 시도한다. 복사·이동을 금지해
하나의 GPU 포인터를 여러 객체가 해제하는 일을 방지한다. CUDA_CHECK는 즉시 종료 대신
예외를 전달하며, 검사 경계에서 결과의 ERROR로 변환한다.

소멸자는 예외를 던지지 않는다. 해제 호출의 오류는 별도 상태에 남기고 모든 버퍼의
해제를 시도한 뒤 결과에 반영한다. 최초 실행 오류와 해제 중 오류가 함께 발생하면
둘 다 보존한다. cudaFree가 이전 비동기 실행의 오류를 반환할 수도 있으므로 이를
특정 메모리 해제 결함으로 단정하지 않는다.

중간 실패를 직접 관찰하는 테스트:

```bash
./build/cuda/runtime_tests sync_failure
```

첫 패턴은 실제 GPU에서 완료하고, 두 번째 동기화 호출은 실제 완료 대기 이후 테스트가
실패 반환값으로 바꾼다. 결과에 첫 패턴과 `completed_patterns=1`이 남으며 마지막
`sync_failure: PASS`는 예상한 실패 처리와 자원 해제를 확인했다는 뜻이다.
테스트 프로세스의 종료 코드는 0이며 검증 결과 상태는 ERROR다.

이 테스트의 호출 실패는 제어된 반환값 주입이다. 실제 GPU 장애·OOM 재현이 아니며,
해제 실패를 모사할 때도 실제 메모리는 먼저 해제해 테스트 자체의 누수를 막는다.
정상 해제·부분 할당 실패·동기화 실패·해제 오류·후속 실행·크기 경계를 검사한다.

## 보존한 학습 예제

사용자가 직접 커널과 CPU 대조 코드를 단계적으로 구현했다. 현재 배열은 1,025개 원소이며
5 blocks × 256 threads 중 255 threads는 쓰기·검사를 건너뛴다.
패턴은 `00000000`, `ffffffff`, `aaaaaaaa`, `55555555` 순서로 검사한다.

```bash
source cuda-env.sh
mkdir -p build
nvcc -std=c++17 -arch=sm_86 -lineinfo examples/first_kernel.cu -o build/first_kernel
./build/first_kernel
./build/first_kernel --inject
```

- 기본 실행: 네 패턴 모두 CPU·GPU 오류 0건, `reference_check=PASS`, 종료 코드 0.
- `--inject`: 첫 패턴에서 index 0, 512, 1024에 각각 XOR mask 1, 3, 1 적용.
  오류는 세 원소이며 CPU·GPU가 모두 검출한다. 다음 패턴부터는 카운터를 초기화하고
  데이터를 다시 써서 정상 통과한다. 첫 패턴의 실패를 유지하여 전체 종료 코드는 1이다.
- 현재 `max_records=3`. GPU 기록 순서는 스레드 실행 순서에 따라 달라질 수 있다.
  오류 총개수와 기록 개수를 분리하며 한도를 초과하면 `truncated=true`로 표시한다.
- CPU 대조는 GPU 오류 개수, 기록의 위치·기댓값·실제값, 중복 기록을 확인한다.
  대조 실패 시 `reference_check=ERROR`, 전체 종료 코드 2.
- 잘못된 옵션: 사용법을 출력하고 종료 코드 2.
- 사용자가 `max_records=2`의 기록 제한과 다음 패턴의 초기화를 직접 확인했다.
  CPU로 복사한 GPU 기록을 일부러 변조한 대조 실패 테스트도 수행했고,
  종료 코드 2를 확인한 뒤 임시 변조 코드를 제거했다.
- Compute Sanitizer의 환경 실패는 아래 기록과 같이 미해결이며 검증 통과로 취급하지 않는다.

## 학습 예제의 자동 회귀 테스트

테스트를 통해 재현한 문제와 수정 근거를 남긴다. 현재 자동 검사는 세 가지 CLI 경우이며,
새 모듈의 단위 검사와 후속 GPU 통합·성능 비교 계획은 [테스트 전략](docs/TESTING.md)에 정리했다.
학습 예제 자체의 성능은 비교하지 않았다. 모듈화한 도구의 성능 측정은 [성능 실험](docs/PERFORMANCE.md)에 있다.

```bash
source cuda-env.sh
python3 scripts/test_first_kernel.py
```

스크립트는 현재 소스를 재빌드한 뒤 일반 실행, 오류 주입 실행, 잘못된 옵션의 세 경우를
실제 GPU 환경에서 확인한다. 종료 코드뿐 아니라 네 패턴의 순서, CPU·GPU 오류 개수,
오류 기록 내용과 중복·누락, 초기화, 대조 결과, 최종 상태를 검사한다.
오류 주입 프로그램의 종료 코드 1은 테스트의 예상 결과이므로 테스트 자체는 PASS다.

현재 예제의 `count=1025`, `max_records=3` 및 주입 위치를 기준으로 한 테스트다.
배열 크기나 기록 한도를 바꾸면 테스트 조건도 확장해야 한다. 한도 초과와 기록 변조에
대한 앞선 수동 검사는 이 자동 테스트의 세 경우에 포함되지 않는다.

`results/*-regression/`에 빌드·실행 명령, 원시 stdout/stderr, 종료 코드, 소스와 테스트
사본, 소스·실행 파일 SHA256 및 판정 결과를 저장한다.
이전 index 쓰기 예제의 기록은 `results/*-injection-cli/`에 보존되어 있다.

## 개발 이력과 커밋

2026-09-20까지 작업한 내용을 환경 구성, 검증 기능, 자동 테스트·기록으로 나누어
커밋했다. 이 시점 이전의 개별 실습마다 커밋을 남긴 것은 아니며, 당시 저장한
실행 로그와 소스 사본은 [실행 기록](results/README.md)에서 확인할 수 있다.

이후에는 기능 변경 → 관련 테스트 → 결과 확인 → 커밋 순서로 진행한다.
커밋 제목은 변경 내용을, 본문은 해결하려는 문제·구현 이유·검증 결과를 설명한다.
배열 크기 옵션, 작은 배열의 오류 주입 중복 제거, 기록 한도 테스트 확장 등을
각각 완성된 변경 단위로 남긴다.

새 실행 로그는 기본적으로 Git에서 제외한다. 의미 있는 단계의 기록만 선택해
`git add -f results/<실행 폴더>`로 포함한다. 실행 파일과 CUDA Toolkit은 커밋하지 않는다.

## 첫 실행 — 2026-09-20

- WSL2, Ubuntu 22.04.5, RTX 3060 12 GiB, Windows driver 591.86.
- CUDA 12.8.1 배포의 NVCC 12.8.93, GCC 11.4.0.
- NVIDIA 공식 NVCC·cudart·CCCL·Compute Sanitizer 구성요소를 사용자 경로에 준비.
- 각 다운로드의 SHA256을 공식 manifest와 대조. 구성과 출처는
  `~/.local/opt/cuda-12.8.1-minimal/installation.json`에 기록.
- 이 구성은 필요한 구성요소만 모은 것이며 전체 Toolkit 설치가 아니다.
- 설치 위치: `~/.local/opt/cuda-12.8.1-minimal`.

```bash
cd /home/meoru/skhynix-apply-2026-9-software/gpu-memory-validator
python3 scripts/setup_cuda.py
source cuda-env.sh
mkdir -p build
nvcc -std=c++17 -arch=sm_86 -lineinfo examples/first_kernel.cu -o build/first_kernel
./build/first_kernel
```

실제 실행 결과(종료 코드 0):

```text
gpu=NVIDIA GeForce RTX 3060 count=1000 bytes=4000 blocks=4 threads_per_block=256
first=0 last=999 mismatches=0 status=PASS
```

GPU에서 1,000개의 32-bit 원소에 각 index를 기록한 뒤 CPU로 복사해 전부 대조했다.
4개 block × 256개 thread 중 배열 밖 24개 thread는 경계 조건으로 쓰기를 건너뛴다.
이 결과는 작은 프로그램의 실행 확인이며 GPU 전체 메모리 무결성이나 HBM 검증 결과가 아니다.

첫 빌드는 `lib`/`lib64` 경로 차이로 실패했다. 사용자 설치 경로 안에 `lib64 -> lib`
링크를 추가한 후 재빌드·실행에 성공했다. 실패와 성공 로그 모두 `results/`에 보존했다.
각 기록의 `run.json`에는 명령·종료 코드·UTC 시각·소스 SHA256이 들어 있다.

## Compute Sanitizer — 미검증

```bash
source cuda-env.sh
compute-sanitizer --tool memcheck --error-exitcode 2 ./build/first_kernel
```

2026-09-20 실행에서 `Failed to initialize WDDM debugger interface` 및
`Device not supported`를 보고하며 종료 코드 2로 실패했다.
도구는 Windows에서 `EnableDebuggerInterface.bat`를 관리자 권한으로 실행하라고 안내했다.
Windows 설정은 변경하지 않았다. 프로그램 자체 PASS와 Sanitizer 검증 통과를 구분한다.
현재 정확성 근거는 CPU 전체 원소 대조이며, Sanitizer는 환경 설정 후 다시 실행해야 한다.

## 다음 학습

1. 제출 버전의 대표 실행과 전체 테스트 근거 확인.
2. 포트폴리오 PDF 제작과 지원서 마무리.

## 공식 자료

- [CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [CUDA 12.8.1 구성요소 배포 안내](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-installation-guide-linux/index.html#tarball-and-zip-archive-deliverables)
- [공식 배포 manifest](https://developer.download.nvidia.com/compute/cuda/redist/redistrib_12.8.1.json)
- [CUDA Runtime API: cudaFree](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-runtime-api/group__CUDART__MEMORY.html)
