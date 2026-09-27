# 호스트 버퍼 재사용 성능 비교

GPU 검사·전체 데이터 복사·CPU 전체 대조를 유지하며 CPU 스냅샷 버퍼를 재사용했다.
측정 대상은 **프로세스 전체 시간**이며 GPU 커널 시간이나 메모리 대역폭이 아니다.

## 변경 내용

패턴마다 `std::vector<uint32_t> host_data(count)`를 생성하던 코드를 반복문 밖으로 옮겼다.
네 패턴 × 4회 반복에서 큰 호스트 버퍼의 할당·초기화가 16회에서 1회로 줄어든다.

```cpp
std::vector<std::uint32_t> host_data(count);
for (iteration ...) {
    for (pattern ...) {
        // GPU 처리 후 전체 버퍼를 복사하고 CPU에서 검사
        cudaMemcpy(host_data.data(), device_data.get(), bytes, cudaMemcpyDeviceToHost);
        check_reference(host_data, ...);
    }
}
```

위 코드는 설명용 축약이다. 실제 구현은 복사 성공을 확인한 후에만 대조하며 실패 시 ERROR로 처리한다.
GPU 커널·복사량·CPU 검사·출력과 다른 버퍼의 관리는 비교 버전 간 동일하다.

## 측정 조건

| 항목 | 조건 |
|---|---|
| 비교 코드 | 기준 `dbca56b`, 변경 `5336495` |
| 환경 | RTX 3060, WSL2, NVCC 12.8.93, GCC 11.4.0 |
| 빌드 | CMake Release, -O3 -DNDEBUG, CUDA architecture 86 |
| 검사 | 128/256 MiB, 기본 네 패턴 × 4회, K=3, CPU 전체 대조, 주입 없음 |
| 표본 | 각 크기/버전 준비 1회 제외, 본 측정 각 10회 |
| 실행 순서 | 기준→변경 / 변경→기준 교대, 각 표본은 새 프로세스 |
| 시간 범위 | 프로세스 시작~종료: CUDA 초기화·할당·복사·CPU 대조·출력·해제 포함 |

느린 표본도 제외하지 않았다. 각 실행의 CPU 시간과 minor page fault를 기록하고,
GPU 지표는 측정 구간 밖에서 각 쌍 전후에 조회했다. 측정 40회와 준비 4회 모두
독립 CLI 검사 함수로 패턴별 값·오류 수·기록·대조·완료 횟수·상태를 확인했다.

## 결과

| 할당 크기 | 기준 중앙값 | 변경 중앙값 | 시간 감소 | 기준 Q1–Q3 | 변경 Q1–Q3 |
|---|---:|---:|---:|---:|---:|
| 128 MiB | 3.736s | 2.208s | 40.9% | 3.702–3.783s | 2.187–2.223s |
| 256 MiB | 7.272s | 4.135s | 43.1% | 7.220–7.404s | 4.108–4.189s |

감소율은 `(기준 중앙값 − 변경 중앙값) / 기준 중앙값 × 100`이다.

![모든 측정 표본과 중앙값](../results/20260927T085149.505158Z-host-buffer-comparison/comparison.png)

minor page fault 중앙값은 128 MiB에서 549,652→58,116, 256 MiB에서 1,075,987.5→92,932로 감소했다.
이 관측은 반복 할당·초기화의 호스트 메모리 관리 비용을 줄였다는 해석을 뒷받침한다.
page fault는 OS 지표이며 GPU 메모리 불량 개수가 아니다. 구간별 프로파일링으로 원인을 세분화하지는 않았다.

[조건·원시 결과](../results/20260927T085149.505158Z-host-buffer-comparison/run.json) ·
[전체 표본 CSV](../results/20260927T085149.505158Z-host-buffer-comparison/samples.csv) ·
[그림 PDF](../results/20260927T085149.505158Z-host-buffer-comparison/comparison.pdf)

공유 GPU/WSL의 단일 PC 결과다. 주변 부하를 완전히 통제한 벤치마크나 장시간 안정성 시험은 아니다.

## 현재 버전과 기준 버전 비교

아래는 기준 소스/빌드가 없는 체크아웃에서 실행한다. 이미 기준 worktree가 있으면 생성 단계는 생략한다.
현재 버전과 비교한 결과는 위 두 고정 버전의 측정과 별도 실험으로 취급한다.

```bash
source cuda-env.sh
git worktree add --detach build/perf-baseline-source dbca56b
cmake -S build/perf-baseline-source -B build/perf-baseline \
  -DGMV_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=86
cmake --build build/perf-baseline -j 4
cmake -S . -B build/cuda \
  -DGMV_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=86
cmake --build build/cuda -j 4
python3 benchmarks/compare_host_buffer.py --samples 10 --iterations 4
```

실행기는 양쪽 소스·바이너리 해시·CMake cache·컴파일러 정보·원시 출력을 보존한다.
원래 비교의 코드와 조건은 저장된 결과의 소스 사본에서 확인할 수 있다.

## 그림 생성

그래프 패키지는 별도 환경에 설치하며 CUDA 검증 실행의 의존성이 아니다.

```bash
python3 -m venv build/plot-env
build/plot-env/bin/python -m pip install -r benchmarks/requirements-plot.txt
build/plot-env/bin/python benchmarks/plot_comparison.py \
  results/20260927T085149.505158Z-host-buffer-comparison/run.json
```
