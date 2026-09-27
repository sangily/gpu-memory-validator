# 입력 설정

## CLI 옵션

C++ 실행 파일은 직접 인자를 받고, Python 실행기는 JSON 설정을 검증해 C++ 인자로 전달한다.
`count`는 32비트 원소 수이며 할당 바이트 수는 `count × 4`다.

| 설정 | 기본값 | 범위·의미 |
|---|---|---|
| `--count N` | 1025 | 1~4,294,967,295; 실제 할당 가능 여부는 장비에 따름 |
| `--max-records K` | 3 | 0~4,294,967,295; 패턴별 상세 한도, 0은 개수만 기록 |
| `--iterations N` | 1 | 1~10000; 전체 패턴 목록의 반복 횟수 |
| `--gpu-passes N` | 1 | 1~4096; 한 번 채운 데이터를 GPU에서 N회 검사 후 CPU 전체 대조 |
| `--access-mode MODE` | read | read / invert; invert는 검사 사이 비트 반전, gpu-passes≥2 필요 |
| `--inject-pass N` | 1 | 1~gpu-passes; 첫 반복·첫 패턴에서 오류를 넣을 GPU 검사 회차 |
| `--inject` | 비활성 | 지정 회차에 오류 주입 |
| C++ `--patterns HEX,...` | 00000000,ffffffff,aaaaaaaa,55555555 | 1~64개 값; 모드별 상수·XOR 값·seed |
| C++ `--pattern-mode MODE` | constant | constant / index / seeded |
| Python `--pattern-file PATH` | 없음 | 패턴 JSON |
| Python `--profile PATH` | 없음 | 실험 프리셋 JSON |

Python은 `--no-inject`도 지원한다. 음수·overflow·잘못된 숫자·중복 옵션 등은 C++ 입력 단계에서 거부한다.
실행기의 시간 제한·모니터링 옵션은 [실험 실행](EXPERIMENTS.md)에 있다.

```bash
./build/cuda/gpu_memory_validator --count 257 --iterations 2 \
  --patterns 12345678,87654321 --inject
python3 scripts/run_experiment.py --pattern-file patterns/custom-constants.json --count 257
```

## 패턴 JSON

`patterns/`에 저장한다. 최소 정의는 다음과 같다.

```json
{
  "schema_version": 1,
  "name": "Custom constants",
  "values": ["12345678", "87654321", "00ff00ff", "ff00ff00"]
}
```

`mode`는 선택 항목이며 생략하면 기존과 같은 `constant`다. 각 `values` 항목마다 전체 영역을 검사한다.
목록의 순서와 중복을 유지한다. 배열에 목록 값을 차례로 배치하는 방식은 아니다.

| mode | 위치 i의 기대값 | values의 의미 |
|---|---|---|
| constant | value | 전체 영역에 쓰는 상수 |
| index | uint32(i) XOR value | 위치 패턴의 XOR 값; 0과 ffffffff로 정방향/반전 검사 |
| seeded | mix32(uint32(i) XOR value) | 재현 가능한 seed |

`mix32`는 32비트 unsigned 연산으로 `x ^= x >> 16; x *= 0x7feb352d; x ^= x >> 15;
x *= 0x846ca68b; x ^= x >> 16`을 수행한다. 곱셈은 2^32로 나눈 나머지다.
암호학적 난수나 물리 주소가 아니다. 같은 seed·index는 실행 순서와 무관하게 같은 값을 만든다.
반복 회차마다 seed를 자동 변경하지 않으며, 다른 seed는 values에 추가한다.

```bash
./build/cuda/gpu_memory_validator --pattern-mode index --patterns 0,ffffffff --count 257
python3 scripts/run_experiment.py --profile profiles/seeded-128mib.json --inject
```

GUI의 패턴 방식 선택으로 세 모드를 저장할 수 있고, 실행 결과에도 mode를 기록한다.

값은 1~8자리 16진수 문자열이고 `0x`/`0X` 접두사를 허용한다. 실행 시 소문자 8자리로 정규화한다.
JSON 정수·부호·공백·32비트 범위 밖 값은 거부한다. 임의 바이너리 배열이나 사용자 작성 실행 코드는 입력으로 받지 않는다.

## 프리셋 JSON

`profiles/`에 저장한다. 다음은 주입을 활성화한 프리셋 예시다.

```json
{
  "schema_version": 1,
  "name": "Injected smoke test",
  "pattern_file": "../patterns/custom-constants.json",
  "count": 257,
  "max_records": 2,
  "iterations": 2,
  "injection_enabled": true,
  "timeout_seconds": 60,
  "sample_interval": 1,
  "telemetry_enabled": true
}
```

`schema_version`, `name`, `pattern_file`은 필수다. 생략한 실행 조건은 기본값을 사용한다.
시간 제한 60초, 조회 간격 1초, 지표 수집 활성화가 기본이며 시간 값은 유한한 양수여야 한다.
두 JSON 형식 모두 이름은 공백이 아닌 120자 이하, 선택 설명 `description`은 4096자 이하다.
잘못된 타입·알 수 없는 필드·중복 키·64 KiB 초과 파일은 거부한다.

## 경로와 덮어쓰기

우선순위는 **기본값 → 프리셋 → 명시한 CLI 옵션**이다. CLI 덮어쓰기는 원본을 수정하지 않는다.
프리셋 안의 `pattern_file`은 프리셋의 디렉터리 기준이며, CLI 경로는 현재 디렉터리 기준이다.

```bash
python3 scripts/run_experiment.py --profile profiles/custom-smoke.json --inject
python3 scripts/run_experiment.py --profile profiles/custom-smoke.json --no-inject
python3 scripts/run_experiment.py --profile profiles/128mib-normal.json
```

기본 custom-smoke의 패턴·크기·반복을 유지하면 첫 명령은 오류 3건·상세 2건,
완료 패턴 8개와 FAIL·종료 1을 낸다. 두 번째는 PASS·종료 0이다.
주입 여부는 예제 명령에서 명시하므로 프리셋의 해당 값을 편집해도 결과 의도가 유지된다.
실행 당시 원본과 최종 설정은 [결과 폴더](EXPERIMENTS.md#저장-파일)에 보존한다.

## GPU 반복 검사

`gpu_passes=1`은 매 검사마다 CPU 전체 대조하는 기존 방식이다. 2 이상이면 GPU에서 읽기 검사를
묶어서 실행한 뒤 CPU가 전체 스냅샷을 대조한다(`reference_mode=checkpoint_full`).
프리셋 JSON에도 `gpu_passes`, `inject_pass`를 저장할 수 있다. 기존 파일은 둘 다 1이다.

```bash
python3 scripts/run_experiment.py --profile profiles/load-smoke.json --inject
```

위 프리셋은 7회 중 4회차에 주입한다. 첫 실패 회차와 오류 3건을 보존하고 CPU가 대조한다.
남은 GPU 검사 회차는 건너뛰며 다음 패턴·반복이 정상이어도 최종 FAIL을 유지한다.
상세 구조와 부하 실험 해석은 [지속 읽기 부하](LOAD.md)를 참고한다.

## 검사 동작

`--access-mode read|invert`와 프리셋의 `access_mode`를 지원한다. 기본값과 기존 파일은 read다.
invert는 GPU 검사 사이에 모든 비트를 반전하며 gpu_passes≥2가 필요하다. CPU 기대값도 해당
회차에 맞춰 반전한다. 동작·실패 보존·예시는 [읽기·반전 검사](INVERT.md)를 참고한다.
