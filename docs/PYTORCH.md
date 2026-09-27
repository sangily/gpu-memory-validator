# PyTorch 장치 오류 실습

작은 GPU 추론에서 CPU/GPU 장치 불일치를 재현하고, 입력 전달을 수정한 뒤 CPU 기준과 대조한다.
소스는 [device_lab.py](../experiments/pytorch/device_lab.py)다. 학습과 모델 품질 평가는 수행하지 않는다.

## 계산 모델

`Linear(32, 16) → ReLU`에 `[64, 32]` 입력을 넣어 `[64, 16]`, 총 1,024개 출력을 계산한다.
Linear는 입력 32개에 가중치를 곱해 합하고 편향을 더한다. ReLU는 음수를 0으로 바꾼다.

```text
X [64,32] @ W.T [32,16] + b [16] → Z [64,16] → max(0, Z)
```

가중치 512개와 편향 16개는 무작위 초기값이다. 고정 seed로 입력·파라미터를 만들고 동일한 원본을
CPU/GPU에 사용한다. `.eval()`과 `torch.inference_mode()`로 추론을 실행한다.
[Linear](https://docs.pytorch.org/docs/2.10/generated/torch.nn.Linear.html) ·
[ReLU](https://docs.pytorch.org/docs/2.10/generated/torch.nn.ReLU.html)

## 환경 설치

Python 3.11 환경에 PyTorch 2.10.0+cu128과 NumPy 2.3.5를 설치한다.
이미 `build/torch-env`가 준비되어 있으면 실행 단계부터 진행한다.

```bash
python3.11 -m venv build/torch-env
build/torch-env/bin/python -m pip install -r experiments/pytorch/requirements.txt
```

ensurepip가 없는 환경에서는 `--python`을 지원하는 외부 pip를 사용할 수 있다.

```bash
python3.11 -m venv --without-pip build/torch-env
python3 -m pip --python build/torch-env/bin/python install -r experiments/pytorch/requirements.txt
```

## 실행과 기대 결과

저장소 루트에서 각 명령을 실행한다. 오류 사례는 의도적으로 종료 코드 2를 반환한다.

```bash
build/torch-env/bin/python experiments/pytorch/device_lab.py --case device-mismatch
build/torch-env/bin/python experiments/pytorch/device_lab.py --case ignored-transfer
build/torch-env/bin/python experiments/pytorch/device_lab.py --case fixed
build/torch-env/bin/python tests/pytorch/check_device_lab.py
```

| 사례 | 동작 | 프로그램 결과 |
|---|---|---|
| device-mismatch | GPU 모델에 CPU 입력 전달 | forward에서 ERROR·종료 2 |
| ignored-transfer | Tensor.to 반환값을 버리고 CPU 입력 전달 | forward에서 ERROR·종료 2 |
| fixed | 반환된 GPU 입력으로 실행·CPU 기준 대조 | PASS·종료 0 |

```python
# 오류: GPU로 복사한 결과를 사용하지 않음
cpu_inputs.to('cuda:0')
output = gpu_model(cpu_inputs)

# 수정
inputs = cpu_inputs.to('cuda:0')
output = gpu_model(inputs)
torch.cuda.synchronize()
```

장치를 바꾸는 `Tensor.to()`는 변환한 텐서를 반환하고 원본을 옮기지 않는다.
반면 `Module.to()`는 모델을 제자리에서 변경하므로 CPU 기준 모델은 deepcopy로 보존한다.
동기화는 완료 대기이며 정확성은 이후 수치 대조로 확인한다.
[Tensor.to](https://docs.pytorch.org/docs/2.10/generated/torch.Tensor.to.html) ·
[Module.to](https://docs.pytorch.org/docs/2.10/generated/torch.nn.Module.html#torch.nn.Module.to) ·
[CUDA 비동기 실행](https://docs.pytorch.org/docs/2.10/notes/cuda.html#asynchronous-execution)

## 수치 기준과 검증 결과

GPU는 float32·TF32 비활성, CPU는 동일한 float32 입력/파라미터를 float64로 변환해 계산한다.
출력 shape와 유한값을 먼저 확인하고 전체 원소를 다음 기준으로 비교한다.

```text
|actual - reference| <= 0.00001 + 0.0001 × |reference|
```

절대 오차 `atol=1e-5`와 상대 오차 `rtol=1e-4`를 합친 기준이다. 기준값이 0이면 0.00001,
1이면 0.00011까지 허용한다. NaN과 무한대는 거부한다.
GPU 출력을 float64로 바꾸는 것은 비교 dtype을 맞추는 것이며 기존 반올림을 제거하지 않는다.
[assert_close](https://docs.pytorch.org/docs/2.10/testing.html#torch.testing.assert_close)

RTX 3060에서 출력 1,024개를 대조했고 최대 절대 오차는 약 `1.61e-7`이었다.
CPU 검사 4개와 실제 실행 경로 4개가 통과했다. GPU 비가시 상태는 CPU로 대체하지 않고 ERROR로 처리한다.
[검증 기록](../results/20260927T102414.578693Z-pytorch-validation/run.json)에 소스·환경·패키지 버전·원시 예외를 보존했다.

CPU/GPU가 같은 PyTorch 모델 정의를 사용하므로 수식 자체의 공통 오류까지 검출하는 독립 구현은 아니다.
허용 오차는 이 작은 연산의 기준이며 모든 AI 모델이나 하드웨어 검증의 규격이 아니다.
PyTorch 기록은 별도 스키마로 저장하며 메모리 검증 GUI 목록에는 포함하지 않는다.
