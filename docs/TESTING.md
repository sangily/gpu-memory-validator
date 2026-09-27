# 테스트와 검증 범위

CPU에서 판단할 수 있는 로직, 실제 GPU 동작, 실행기·화면 흐름을 나누어 검사한다.
정상 종료만 보지 않고 오류 수·기록 내용·상태·종료 코드·원시 로그를 함께 확인한다.

## 검사 계층

PyTorch 사용자 CUDA 연산의 배치·경계·stream·추론·입력 계약 74개는
`build/torch-env/bin/python tests/pytorch/test_layout.py`로 실행한다. [조건과 근거](LAYOUT.md).

아래 개수는 [보존한 실행 증거](../results/README.md)의 통과 결과다. 각 기록의 소스 사본과 해시로 대상 버전을 확인한다.

| 계층 | 개수 | 주요 검사 |
|---|---:|---|
| CPU 단위 | 32 | CLI 입력·범위·상태 우선순위, CPU 대조의 값·개수·중복·누락 |
| 런타임/버퍼 | 12 | 자원 정리, 부분 할당·동기화·해제 오류, 반복 중 실패, 버퍼 경계 |
| 실제 GPU CLI | 109 | 작은 배열·tail 경계, K 제한, 반복 초기화, 세 패턴 모드, 주입·잘못된 입력 |
| Python 실행기/설정 | 18 | 종료 계약·중단·timeout·지표 가용성, 스키마·경로·덮어쓰기·입력 사본 |
| 프리셋→GPU 통합 | 9 | 상대 경로, 설정 덮어쓰기, 단일/중복 패턴, 잘못된 입력 |
| GPU 반복 모드 | 51 | 정상/첫·중간·마지막 주입, K=0/2, 상태 유지, 실제 timeout·중단 |
| 큰 배열 위치·seed | 8 | 128/256 MiB, 정상/주입, 2패턴×4회 전체 대조 |
| GUI 서버 / 브라우저 | 6 / 9 | 저장·충돌·조회, 실제 화면 조작·초기 로딩·반응형 배치 |
| PyTorch CPU / 실행 경로 | 4 / 4 | 수치 비교 함수, 장치 오류·수정·GPU 비가시 상태 |

## CPU·GPU·실행기

저장소 루트에서 실행한다. CPU 단위 검사는 CUDA 없이 빌드할 수 있다.

```bash
cmake -S . -B build/cpu -DGMV_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpu
ctest --test-dir build/cpu --output-on-failure
python3 -m unittest discover -s tests/runner -v
```

실제 GPU 검사는 [CUDA 빌드](../README.md#빌드와-첫-실행) 후 실행한다.

```bash
source cuda-env.sh
ctest --test-dir build/cuda -L gpu --output-on-failure
python3 tests/cli/test_validator.py
python3 tests/cli/test_profiles.py
python3 tests/cli/test_load.py
# 큰 배열 반복 정확성 검사; 성능 임계값이나 GPU 포화 부하 시험은 아님
python3 tests/cli/test_spatial_matrix.py
```

프리셋 통합 검사는 저장소 기본 프리셋의 크기·값·반복 조건을 전제로 한다. 주입 여부는 테스트가
명시적으로 설정한다. 다른 조건을 GUI에서 편집하면 테스트 기대값과 달라질 수 있으므로 입력을 구분한다.

## GUI

서버 검사는 추가 패키지 없이 수행한다. 브라우저 검사용 Playwright는 GUI 실행 자체의 의존성이 아니다.

```bash
python3 -m unittest discover -s tests/gui -v
python3 -m venv build/ui-env
build/ui-env/bin/python -m pip install -r tests/gui/requirements-browser.txt
build/ui-env/bin/python -m playwright install chromium
build/ui-env/bin/python tests/gui/browser_smoke.py
```

브라우저 검사는 실제 저장된 128 MiB 결과를 복사해 조회하고 임시 디렉터리에서만 설정을 편집한다.
잘못된 입력·외부 파일 변경 충돌·초기 로딩·명령 복사·작은 화면·브라우저 오류를 확인한다.

## PyTorch

[전용 환경](PYTORCH.md#환경-설치)을 준비한 뒤 실행한다.

```bash
build/torch-env/bin/python tests/pytorch/check_device_lab.py
```

CPU 검사에서는 작은 오차 허용, 값 변조·NaN/무한대·shape 불일치 거부를 확인한다.
실제 실행에서는 장치 불일치·Tensor.to 반환값 누락·수정·GPU 비가시 상태를 확인한다.

## 결과를 판단하는 기준

- 오류 주입 프로그램의 FAIL·종료 1을 예상대로 검출하면 테스트는 PASS다. 프로그램 상태를 바꾸지는 않는다.
- K가 부족하면 GPU 기록이 실제 오류 집합의 중복 없는 부분집합인지 확인한다. 순서는 요구하지 않는다.
- CPU 단위 검사는 커널 실행을 대신하지 않는다. 런타임/버퍼 12개에도 host 전용 경계 검사가 포함된다.
- 런타임 오류는 지정 호출의 반환값을 바꾸어 재현한다. 실제 할당·커널·복사·해제를 사용하지만
  물리 OOM이나 치명적 GPU 장애 복구를 입증하지 않는다.
- 실행기 검사는 합성 자식 프로세스와 지표 응답도 사용한다. 별도 실제 GPU 실행 증거와 구분한다.
- 성능은 [별도 실험](PERFORMANCE.md)으로 평가한다. 공유 GPU의 시간 변동을 기능 테스트의 고정 임계값으로 삼지 않는다.

Compute Sanitizer는 WDDM 초기화 문제로 미검증이다. CPU 대조와 경계 테스트가 메모리 접근 검사 도구를
대체하지는 않는다. 부하 실험은 [실측 조건과 한계](LOAD.md) 범위에서 해석한다. 자동 CI/GPU 실행 환경은 제공하지 않는다.
