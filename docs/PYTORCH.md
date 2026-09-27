# PyTorch 장치 불일치 재현과 CPU 기준 대조

CUDA에서 다룬 메모리 위치·전송·완료 대기·결과 대조를 PyTorch 추론에 적용하는 작은 실습이다.
`Linear(32, 16) → ReLU` 모델에 `[64, 32]` 입력을 넣어 1,024개 출력 값을 계산한다.
학습이나 모델 품질 평가는 수행하지 않는다. 고정 seed로 만든 입력과 가중치를 사용한다.

## 실행

현재 작업 공간에는 `build/torch-env`에 별도 Python 환경을 준비했다.
저장소 루트에서 실행한다. 의도한 오류 사례는 종료 코드 2이므로 명령을 `&&`로 연결하지 않는다.

```bash
build/torch-env/bin/python experiments/pytorch/device_lab.py --case device-mismatch
echo "exit_code=$?"
build/torch-env/bin/python experiments/pytorch/device_lab.py --case ignored-transfer
echo "exit_code=$?"
build/torch-env/bin/python experiments/pytorch/device_lab.py --case fixed
echo "exit_code=$?"
```

| 사례 | 모델 / 입력 위치 | 예상 결과 |
|---|---|---|
| device-mismatch | cuda:0 / cpu | forward에서 RuntimeError, ERROR·종료 2 |
| ignored-transfer | cuda:0 / cpu | 반환값을 버려 입력이 CPU에 남음, ERROR·종료 2 |
| fixed | cuda:0 / cuda:0 | 완료 대기 후 CPU 기준 대조, PASS·종료 0 |

`run_dir`에 버전·환경·장치 위치·실패 단계·원문 예외·소스 사본과 SHA256을 저장한다.
대조 불일치는 FAIL·종료 1, 실행/환경 오류는 ERROR·종료 2로 구분한다.
CUDA 장치가 없으면 오류로 종료하며 CPU 실행으로 조용히 바꾸지 않는다.
PyTorch 결과는 별도 스키마로 저장하고 현재 메모리 검증 GUI 목록에는 포함하지 않는다.

## 핵심 코드와 원인

```python
gpu_model = copy.deepcopy(cpu_model).to('cuda:0')

# 오류: 전송된 텐서를 받지 않아 원래 cpu_inputs를 계속 사용한다.
cpu_inputs.to('cuda:0')
output = gpu_model(cpu_inputs)

# 수정: 반환된 GPU 텐서를 연산에 사용한다.
inputs = cpu_inputs.to('cuda:0')
output = gpu_model(inputs)
torch.cuda.synchronize()
```

`Tensor.to()`는 변환한 텐서를 반환한다. 장치나 dtype이 달라져 복사가 필요한 경우
원래 텐서의 장치를 바꾸지 않는다. 이미 장치와 dtype이 같으면 기존 텐서를 반환할 수도 있다.
[Tensor.to 공식 문서](https://docs.pytorch.org/docs/2.10/generated/torch.Tensor.to.html)

반면 `Module.to()`는 모델의 파라미터와 버퍼를 제자리에서 옮긴다. CPU 기준 모델을 유지하려고
먼저 `deepcopy`한 뒤 GPU로 옮겼다. 같은 `.to()`라는 이름만 보고 동작을 동일하게 가정하지 않는다.
[Module.to 공식 문서](https://docs.pytorch.org/docs/2.10/generated/torch.nn.Module.html#torch.nn.Module.to)

`torch.cuda.synchronize()`는 완료 대기를 뜻하며 출력의 정확성을 입증하지 않는다.
완료 후 별도의 수치 대조가 필요하다. 여기서는 동기화 이후 CPU로 출력을 복사한다.
일반적인 CPU 복사에서도 필요한 동기화가 수행되지만 실습에서는 완료 경계를 명시했다.
[CUDA 비동기 실행](https://docs.pytorch.org/docs/2.10/notes/cuda.html#asynchronous-execution)

## 수치 검증

동일한 float32 입력·가중치를 float64로 변환한 CPU 모델을 기준으로 사용한다.
GPU 연산은 float32이며 TF32를 비활성화한다. shape와 유한값 여부를 먼저 검사한 뒤
두 결과를 CPU float64로 맞춰 전 원소를 비교한다. GPU 결과를 float64로 바꾸는 것은
이미 발생한 반올림을 없애지 않는다. 비교 연산의 dtype을 맞추기 위한 것이다.

비교 기준은 실험 전에 정한 `rtol=1e-4`, `atol=1e-5`다.

```text
|actual - reference| <= atol + rtol * |reference|
```

이 기준은 이 작은 float32 추론 실습의 허용 오차이며 모든 모델에 대한 보장이 아니다.
정수 비트 패턴 검사와 달리 부동소수점 연산 결과는 비트 단위 일치를 요구하지 않는다.
NaN과 무한대는 양쪽이 같더라도 이 실습에서는 실패로 처리한다.
[assert_close 공식 문서](https://docs.pytorch.org/docs/2.10/testing.html#torch.testing.assert_close)

CPU와 GPU의 실행 경로·정밀도를 달리했지만 양쪽 모두 PyTorch 모델 정의를 사용한다.
따라서 모델 수식 자체의 공통 오류까지 검출하는 완전히 독립적인 구현은 아니다.
RTX 3060 GDDR6에서의 작은 추론 확인이며 HBM·하드웨어 결함 검증이나 AI 성능 개선 결과로 표현하지 않는다.

## 자동 검사

```bash
build/torch-env/bin/python tests/pytorch/check_device_lab.py
```

먼저 CPU에서 대조 함수의 네 조건을 확인한다: 작은 반올림 허용, 큰 값 변조 거부,
NaN/무한대 거부, broadcast 가능한 shape 불일치 거부.
이후 실제 프로세스로 장치 불일치·반환값 누락·수정·GPU 비가시 상태를 실행한다.
앞의 두 사례는 GPU 모델을 실제로 생성해 오류를 재현한다. GPU 비가시 검사는
해당 자식 프로세스에만 `CUDA_VISIBLE_DEVICES`를 빈 값으로 지정한다.

예상한 ERROR를 재현하면 **테스트는 PASS**지만 **실습 프로그램 결과는 ERROR**로 보존한다.
반환 코드뿐 아니라 실패 단계·CPU/GPU 위치·예외 종류와 내용도 확인한다.
소스, 원시 stdout/stderr, 각 실행의 결과 및 패키지 버전을 함께 보존한다.

## 환경 재구성

Python 3.11용 CUDA 12.8 PyTorch 2.10.0 wheel을 사용한다. 프로젝트의 C++ 빌드 환경과
별도 가상환경이다. 새로운 환경에서는 다음과 같이 설치한다.

```bash
python3.11 -m venv build/torch-env
build/torch-env/bin/python -m pip install -r experiments/pytorch/requirements.txt
```

이 WSL의 `/usr/bin/python3.11`에는 ensurepip가 없어 다른 Python의 pip로 설치했다.
같은 환경에서는 아래 방법을 쓸 수 있다. 바깥 Python의 pip는 `--python`을 지원해야 한다.

```bash
/usr/bin/python3.11 -m venv --without-pip build/torch-env
python3 -m pip --python build/torch-env/bin/python install -r experiments/pytorch/requirements.txt
```

전이 의존성의 실제 설치 버전은 각 `run.json`의 `packages`에 기록한다.

## 저장한 실행 결과 — 2026-09-27

기존 시스템 Python 3.11.0rc1, PyTorch 2.10.0+cu128, RTX 3060에서 CPU 검사 4개와 실제 실행 경로 4개를 통과했다.
수정한 실행의 최대 절대 오차는 `1.6072100483821572e-07`이며 1,024개 출력이 모두 기준을 만족했다.
두 오류 사례는 모델 `cuda:0`, 입력 `cpu`, 실패 단계 `forward`를 기록했다.

[전체 판정·개별 결과 경로](../results/20260927T102414.578693Z-pytorch-validation/run.json) ·
[수정 사례 출력](../results/20260927T102414.578693Z-pytorch-validation/fixed/stdout.txt) ·
[장치 불일치 원문](../results/20260927T102414.578693Z-pytorch-validation/device-mismatch/stderr.txt)

설치 초기에는 NumPy가 없어 PyTorch 초기화 경고가 발생했다. NumPy 2.3.5를 명시 의존성에
추가한 뒤 전체 실습 검사를 다시 통과했다. 최종 정상 사례의 stderr는 비어 있다.
실제 설치 패키지 목록은 `requirements-resolved.txt`, 다운로드 URL과 배포 SHA256은
`dependency-downloads.json`에 남겼다. 의존성 설치 파일과 실행 바이너리는 Git에 포함하지 않는다.
