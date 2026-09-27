# 사용자 패턴과 실험 프리셋

2026-09-27. JSON 패턴 정의를 실제 CUDA fill/verify 및 CPU 전체 대조에 전달한다.
CLI와 GUI가 같은 검증 함수를 사용하도록 `scripts/experiment_config.py`에 입력 처리를 분리했다.
[로컬 GUI](GUI.md)에서 패턴/프리셋을 편집하고 저장할 수 있다. 실행은 CLI로 수행한다.

## 패턴 정의

`patterns/custom-constants.json`:

```json
{
  "schema_version": 1,
  "name": "Custom constants",
  "description": "각 상수로 전체 할당 영역을 채워 검사",
  "values": ["12345678", "87654321", "00ff00ff", "ff00ff00"]
}
```

values는 배열 원소를 순서대로 채우는 데이터가 아니다. 첫 패스는 모든 원소를 12345678로,
다음 패스는 모든 원소를 87654321로 채우는 식으로 목록을 순회한다.
각 패턴 뒤에 GPU 검사·전체 복사·CPU 독립 대조를 수행한다.

- 1~64개 상수, 각 값은 1~8자리 16진수 문자열. 선택적으로 `0x`/`0X` 접두사를 사용한다.
- 실행 시 소문자 8자리로 정규화한다. 정수 JSON 값과 부호/공백/32-bit 범위 초과는 거부한다.
- 순서와 중복 값을 보존한다. 같은 값을 두 번 검사하는 것도 별도 패스다.
- 주입은 첫 반복의 첫 번째 패스에만 적용한다. 값이 같다는 이유로 두 번째 패스에 다시 주입하지 않는다.
- schema_version은 정수 1, name은 비어 있지 않은 120자 이하 문자열, description은 선택 문자열이다.

이는 상수 패턴 목록 지원이다. 임의 바이너리 배열 업로드나 index/seed 기반 생성은 아직 지원하지 않는다.

## 실험 프리셋

`profiles/custom-smoke.json`:

```json
{
  "schema_version": 1,
  "name": "Custom pattern smoke test",
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

pattern_file은 **프리셋 파일의 디렉터리 기준**으로 해석한다. 현재 터미널 디렉터리에 좌우되지 않는다.
프리셋의 schema_version, name, pattern_file은 필수이며 나머지 실행 설정은 생략하면 기존 기본값을 사용한다.
count는 바이트 수가 아닌 32-bit 원소 수다. true/false와 정수를 엄격하게 구분하고,
알 수 없는 필드·중복 JSON 키·잘못된 타입·지원 범위 밖 값·64 KiB 초과 파일은 실행 전에 거부한다.

기본값: count=1025, max_records=3, iterations=1, injection_enabled=false,
timeout_seconds=60, sample_interval=1, telemetry_enabled=true.
값 범위는 validator의 기존 count/K/iterations 범위를 따르며 시간 값은 유한한 양수다.

## 실행과 우선순위

```bash
source cuda-env.sh
python3 scripts/run_experiment.py --profile profiles/custom-smoke.json
```

패턴 4개 × 반복 2회 = 완료 패턴 8개다. 첫 패스에서 오류 3건/상세 2건을 검출하고,
뒤의 패스는 정상이다. 실험은 `FAIL / COMPLETED`, 종료 코드는 1이다.

우선순위는 **기본값 → 프리셋 → 명시한 CLI 옵션**이다. 프리셋의 주입 설정을 끄려면:

```bash
python3 scripts/run_experiment.py --profile profiles/custom-smoke.json --no-inject
```

이때 프리셋 원본은 변경하지 않는다. 패턴 파일만 바꾸거나 단독으로 사용할 수도 있다.
CLI에 직접 입력한 파일 경로는 현재 터미널 디렉터리 기준이다.

```bash
python3 scripts/run_experiment.py --profile profiles/custom-smoke.json \
  --pattern-file patterns/default.json --iterations 3 --no-telemetry
python3 scripts/run_experiment.py --pattern-file patterns/custom-constants.json --count 257
python3 scripts/run_experiment.py --profile profiles/128mib-normal.json
```

C++ 실행 파일은 JSON을 직접 읽지 않는다. Python이 정의를 검증하고 정규화한 값을 넘긴다.
C++ CLI에서도 입력을 다시 확인하므로 Python을 우회한 잘못된 값은 거부한다.

```bash
./build/cuda/gpu_memory_validator --count 257 --iterations 2 \
  --patterns 12345678,87654321 --inject
```

C++의 --patterns는 쉼표로 구분한 16진수 목록이다. 미지정 시 기존 네 패턴을 그대로 사용한다.
Python 실행기에서는 --pattern-file을 사용한다.

## 과거 실행을 보존하는 방법

결과 폴더에는 기존 run.json/stdout/stderr/telemetry/source 외에 다음을 저장한다.

| 파일/필드 | 의미 |
|---|---|
| `resolved_config.json` | CLI 덮어쓰기까지 반영한 실제 설정과 정규화한 패턴 목록 |
| `inputs/profile.json` | 실행 전 읽은 프리셋 원문, 프리셋 사용 시에만 생성 |
| `inputs/patterns.json` | 실행 전 읽은 패턴 원문, 파일 사용 시에만 생성 |
| `run.json.input_files` | 입력 원본 경로, 저장 사본 경로, 읽은 원문의 SHA256 |
| `run.json.config.patterns` | 실제 엔진에 넘긴 패턴 목록 |

파일은 한 번 읽은 내용으로 검증·해석·사본 저장한다. 그 사이 원본이 바뀌어도 다른 내용을 다시
읽어 기록하지 않는다. 과거 실험 조회에는 원본 경로가 아닌 결과 폴더의 사본을 사용한다.
완료 판단은 고정된 숫자 4 대신 **요청한 패턴 수 × 반복 횟수**를 사용한다.

## 검증 증거

- CPU 28개: 기존 25개 + 패턴 파싱/잘못된 값/목록 상한 3개.
- 런타임/버퍼 10개: 직접 API에 빈 목록/상한 초과를 전달하는 경우도 기존 설정 검사에 추가.
- 직접 CLI 34개: 기존 26개 + 사용자 상수/중복 상수/단일 상수의 정상·주입, 빈 목록/overflow.
- Python 17개: 기존 실행기 10개 + 스키마/타입/범위/경로/우선순위/사본 보존 등의 설정 7개.
- 프리셋 통합 5개: 다른 cwd에서 실제 GPU 실행, 정상 덮어쓰기, 중복·단일 패턴, 잘못된 파일 거부.

```bash
ctest --test-dir build/cpu --output-on-failure
ctest --test-dir build/cuda -L gpu --output-on-failure
python3 -m unittest discover -s tests/runner -v
python3 tests/cli/test_validator.py
python3 tests/cli/test_profiles.py
```

합성 실행기 테스트와 실제 GPU 통합 테스트를 구분한다. 테스트 결과와 소스 사본은 results 목록에 있다.
