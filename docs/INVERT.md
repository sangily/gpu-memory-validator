# 검사 사이의 메모리 반전

`access_mode=invert`는 같은 값을 읽기만 반복하는 범위를 보완한다.
한 번 채운 데이터에 대해 `검사 → 비트 반전 → 검사 → 비트 반전 → …` 순서로 동작한다.
매번 새 정답을 덮어쓰는 대신 현재 저장된 word를 반전하므로 각 비트의 0↔1 전환을 다룬다.

## 기대값과 오류 보존

| GPU 검사 회차 | 기대값 |
|---|---|
| 1, 3, 5, … | 원래 패턴 값 |
| 2, 4, 6, … | 원래 패턴 값의 32비트 반전 |

상수·index·seeded에 모두 적용하며 seeded의 경우 seed 자체가 아니라 계산된 word를 반전한다.
CPU 기준 구현에도 기대값의 반전 여부를 전달한다. `snapshot_inverted`가 저장된 데이터의 단계를 표시한다.

각 검사가 끝나면 별도 커널이 최초 실패 회차를 고정한다. 이후 반전과 읽기 검사는 모두 건너뛰어
첫 오류의 데이터를 보존한다. 마지막 예정 회차가 아니라 **실제로 멈춘 회차**의 기대값으로 CPU가 대조한다.
예를 들어 5회 예정 중 2회차에서 실패하면 CPU는 반전된 기대값을 사용해야 한다.
다음 패턴은 새로 채우고 시작하지만 앞선 FAIL은 전체 결과에 남는다.

같은 stream의 실행 순서를 사용한다. 모든 스레드가 오류 개수를 보고한 뒤 실패를 확정하므로
검사 도중 다른 thread의 오류 보고를 생략하지 않는다. [기존 반복 모드](LOAD.md)와 같은 CPU 체크포인트를 사용한다.

## 실행

저장소 루트에서 최신 버전을 빌드한 뒤 실행한다.

```bash
source cuda-env.sh
cmake --build build/cuda -j 4
python3 scripts/run_experiment.py --profile profiles/invert-smoke.json
python3 scripts/run_experiment.py --profile profiles/invert-smoke.json --inject
python3 scripts/run_experiment.py --profile profiles/invert-256mib.json
python3 scripts/run_experiment.py --profile profiles/invert-256mib.json --inject
python3 tests/cli/test_invert.py
```

정상은 PASS/종료 0, 주입은 FAIL/종료 1이다. 작은 프리셋은 4회차에서 오류 3건과 최대 상세 2건을 남긴다.
큰 프리셋은 16회차에서 오류를 주입한다. 직접 실행은 `--access-mode invert --gpu-passes N`이며 N≥2가 필요하다.
기존 프리셋과 기본값은 read다. GUI의 실험 프리셋에서도 검사 동작을 선택할 수 있다.

## 검증 범위

- 실제 GPU 회귀 146개와 CPU/런타임 46개를 통과했다. [원시 검사 기록](../results/20260927T144247.102175Z-invert-regression/run.json).
- CPU 기준: 고정된 반전 정답, 반전 단계의 오류 기록, 잘못된 단계로 대조했을 때 거부.
- 실제 GPU: 상수/index/seeded, count 1/2/257, 기록 한도 0/2, 회차 5/6,
  정상 및 첫·중간·마지막 주입, 복수 패턴과 반복 사이 초기화·최종 FAIL 보존.
- 프리셋→실행기→GPU→CPU의 정상/주입 경로와 GUI 저장.
- 기존 read 모드와 자원 해제·중단·시간 초과 검사는 함께 회귀 확인한다.

## 큰 배열 실험

코드 `3e9ddd5`의 깨끗한 작업 트리에서 128/256 MiB 각각 정상·16회차 주입을 실행했다.
모든 실행은 두 seed×4회 반복×32 GPU 검사이며 CPU 전체 대조는 8회다.
정상은 총 256회 검사와 248회 반전을 완료했다. 주입은 첫 묶음이 16회차에서 멈추고
오류 3건과 반전된 스냅샷을 보존했으며, 나머지 묶음은 정상 완료했다. 최종 결과는 FAIL이다.

| 검사 영역 | 정상 실행 | 주입 실행 |
|---|---|---|
| 128 MiB | PASS, 2.684초 | 예상 FAIL, 2.089초 |
| 256 MiB | PASS, 3.894초 | 예상 FAIL, 3.807초 |

시간은 실행기 관측 전체 시간이며 처리량 비교가 아니다. 실패 후 작업을 건너뛰므로
정상·주입을 같은 작업량의 성능 표본으로 비교하지 않는다. 네 건 모두 독립 로그 검사에 통과했다.
[조건·원시 로그·지표·해시](../results/20260927T144637.446263Z-invert-matrix/matrix.json).
재현 명령은 `python3 tests/cli/test_invert_matrix.py`다. 수 초의 기능 검증이며 장시간 부하 실험은
[별도 read 모드 결과](LOAD.md)와 구분한다.

이 구현은 병렬 배열의 비트 반전 검사이며 DCGM의 moving-inversions 알고리즘을 복제하거나
동등성을 확인한 것이 아니다. 주소 방향 순회, block move, retention, ECC/XID, 물리적 결함 검증은
포함하지 않는다. XOR 주입은 검출 경로 검사다. [DCGM memtest](https://docs.nvidia.com/datacenter/dcgm/latest/reference/diagnostics/plugins/memtest.html).
