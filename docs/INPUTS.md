# 입력 설정

## CLI 옵션

C++ 실행 파일은 직접 인자를 받고, Python 실행기는 JSON 설정을 검증해 C++ 인자로 전달한다.
`count`는 32비트 원소 수이며 할당 바이트 수는 `count × 4`다.

| 설정 | 기본값 | 범위·의미 |
|---|---|---|
| `--count N` | 1025 | 1~4,294,967,295; 실제 할당 가능 여부는 장비에 따름 |
| `--max-records K` | 3 | 0~4,294,967,295; 패턴별 상세 한도, 0은 개수만 기록 |
| `--iterations N` | 1 | 1~10000; 전체 패턴 목록의 반복 횟수 |
| `--inject` | 비활성 | 첫 반복의 첫 패턴에 오류 주입 |
| C++ `--patterns HEX,...` | 00000000,ffffffff,aaaaaaaa,55555555 | 1~64개 상수 |
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

각 상수로 **전체 영역을 채워 검사한 뒤** 다음 상수로 넘어간다. 배열의 각 원소에 서로 다른 값을
순서대로 배치하는 형식이 아니다. 순서와 중복 값을 유지하며 중복 값도 별도 검사 회차다.

값은 1~8자리 16진수 문자열이고 `0x`/`0X` 접두사를 허용한다. 실행 시 소문자 8자리로 정규화한다.
JSON 정수·부호·공백·32비트 범위 밖 값은 거부한다. 임의 바이너리 배열과 index/seed 생성 규칙은 지원하지 않는다.

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
