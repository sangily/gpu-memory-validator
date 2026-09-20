# gpu-memory-validator

CUDA 기반 GPU 메모리 검증 학습 프로젝트. 네 가지 고정 패턴의 쓰기·검증 커널,
별도 XOR 오류 주입, GPU 오류 카운터와 최대 K건의 상세 기록을 구현했다.
작은 배열의 CPU 전체 검사 결과로 GPU 오류 개수와 기록을 대조한다.

최종 범위와 책임별 분리안은 [프로젝트 정의와 구조 설계](docs/PROJECT.md)에 정리했다.
현재 CPU 대조 로직을 CUDA에 의존하지 않는 `src/reference.cpp`로 분리했다.
새 실행 파일은 `src/validator.cu`에서 이를 호출한다. CLI·GPU 자원·출력 분리는 후속 작업이다.
기존 `examples/first_kernel.cu`는 학습 기준 버전으로 보존한다.

## 새 실행 파일 빌드와 테스트

CPU 단위 테스트는 CUDA Toolkit이나 GPU 없이 실행할 수 있다.

```bash
cmake -S . -B build/cpu -DGMV_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpu
ctest --test-dir build/cpu --output-on-failure
```

현재 15개 테스트가 정상 패턴, 순서가 다른 기록, 잘림·기록 생략, 한 원소,
잘못된 개수·값·위치, 중복·누락·초과 기록, 호출 간 상태 독립성을 확인한다.
사례별 코드는 [CPU 대조 테스트](tests/unit/test_reference.cpp)에 있다.

실제 GPU 실행 파일과 CLI 회귀 검사는 다음과 같이 실행한다.

```bash
source cuda-env.sh
cmake -S . -B build/cuda -DGMV_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build/cuda
python3 tests/cli/test_validator.py
./build/cuda/gpu_memory_validator --inject
```

CLI 회귀 검사 세 경우는 기존 예제의 검사 함수를 그대로 사용하며 정상 0, 주입 1,
잘못된 옵션 2를 기대한다. 마지막 직접 주입 실행의 종료 코드 1은 의도한 데이터 FAIL이다.
CUDA 아키텍처 기본값은 실측 장비인 RTX 3060의 86이며 다른 장비는 CMake 설정으로 변경한다.

`check_reference()`는 GPU 오류 개수와 원본 데이터를 독립 대조하고, 기록 수가
`min(실제 오류 수, 기록 한도)`인지도 확인한다. 기록이 잘리면 어떤 오류 부분집합이든
유효하지만 중복·잘못된 값은 허용하지 않는다. CPU 상세 기록도 한도로 제한하고
전체 CPU 오류 수는 모든 원소를 검사해 계산한다.

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
현재 프로젝트의 성능 개선 수치는 아직 측정하지 않았다.

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

1. 분리한 CPU 대조 함수와 테스트를 설명하고, CLI·GPU 실행·출력의 책임 분리 계속 진행.
2. GPU 자원 수명과 오류 전달 정리.
3. 배열 크기와 기록 한도를 인자로 받아 경계 조건 테스트 확장.
4. 반복 실행·실험 기록과 큰 배열의 선택적 CPU 대조 구성.

## 공식 자료

- [CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [CUDA 12.8.1 구성요소 배포 안내](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-installation-guide-linux/index.html#tarball-and-zip-archive-deliverables)
- [공식 배포 manifest](https://developer.download.nvidia.com/compute/cuda/redist/redistrib_12.8.1.json)
