# PyTorch–CUDA 메모리 배치 디버깅

PyTorch의 ReLU를 직접 작성한 CUDA 연산으로 교체하고, 텐서 배치를 무시할 때 발생하는
수치 오류를 재현·수정한다. 의도적으로 만든 결함이며 고객 장애나 PyTorch 결함이 아니다.
드라이버·학습·프레임워크 내부 전체를 수정한 경험으로 표현하지 않는다.

## 문제와 수정

shape는 논리적인 모양이고 stride는 다음 행·열로 이동하는 저장소 간격이다.
예를 들어 [3,4] 텐서를 전치하면 shape [4,3], stride [1,4]가 된다.
주소는 `row * stride[0] + column * stride[1]`이다. view의 data_ptr에는 storage_offset이
이미 반영되므로 다시 더하지 않는다.

| 전략 | 처리 | 의미 |
|---|---|---|
| flat-bug | 모든 입력을 연속 배열로 가정 | 의도적 결함; 저장소 밖 읽기는 거부 |
| strided | 실제 stride로 주소 계산 | 복사 없이 비연속·zero-stride view 지원 |
| contiguous-copy | 연속 버퍼로 변환 후 계산 | 비연속 입력의 추가 복사 비용 |

flat-bug는 연속 입력에서는 통과하지만 전치·슬라이스에서 오답을 낸다. 저장소 경계 안에서도
논리적으로 잘못된 주소를 읽을 수 있으므로 정상 종료는 정확성의 증거가 아니다.
커널은 device guard를 사용하고 PyTorch의 **현재 stream**으로 제출한다. 연산 안에서 전체
device 동기화는 하지 않는다. 실행 오류, dtype/rank/학습 입력 거부는 C++ 경계에서 처리한다.

## 실행

[기존 PyTorch 환경](PYTORCH.md)을 준비한 저장소 루트에서 실행한다. 첫 호출은 확장을 빌드한다.
로더는 CUDAToolkit_ROOT를 CUDA_HOME으로 사용하고 현재 GPU에 맞춰 빌드한다.

```bash
source cuda-env.sh
python3 -m pip --python build/torch-env/bin/python install -r experiments/pytorch/requirements-layout.txt
# 의도적 오답: FAIL / 종료 1
build/torch-env/bin/python experiments/pytorch/layout_lab.py --layout transpose --strategy flat-bug
# 두 수정: PASS / 종료 0
build/torch-env/bin/python experiments/pytorch/layout_lab.py --layout transpose --strategy strided
build/torch-env/bin/python experiments/pytorch/layout_lab.py --layout slice --strategy contiguous-copy
# 실제 GPU 검사와 측정
build/torch-env/bin/python tests/pytorch/test_layout.py
build/torch-env/bin/python experiments/pytorch/layout_lab.py --benchmark
```

CUDA float32 2차원 추론만 지원한다. autograd·torch.compile·다중 GPU는 미검증이다.
지원 조건 밖 입력은 ERROR이며 CPU fallback은 없다. 별도 layout-lab/layout-regression 폴더에
소스·입력 조건·확장 해시·빌드 명령·결과를 보존한다. 기존 메모리 GUI와는 별도 스키마다.

## 실제 결과

RTX 3060 / WSL2 / PyTorch 2.10.0+cu128 / CUDA Toolkit 12.8에서 확인했다.

- 17×19 전치 입력: flat-bug는 323개 중 **279개 불일치**, 수정 구현은 불일치 0.
- 실제 GPU 검사 **74개**: 5개 배치×6개 크기×두 수정, 의도적 결함 대조, 작은 신경망 연결,
  별도 stream 생산자·소비자, 잘못된 입력 거부.
- CPU 기준은 논리적 view에 ReLU를 적용하며 CUDA 주소 공식을 공유하지 않는다. 유한값을 정확히 대조한다.
- Linear→전치→사용자 CUDA ReLU는 GPU 중간 결과의 CPU ReLU와 정확히 대조한다. 별도로 전체
  CPU float32 워크로드와 atol=1e-5, rtol=1e-4로 대조해 행렬 연산 반올림과 배치 오류를 구분한다.
- stream 검사는 지연된 입력 생성 뒤 커널과 다른 stream의 소비자를 연결한다.
  torch.cuda._sleep은 테스트에서만 사용하는 내부 지연 함수다.

[검사 증거](../results/20260927T143507.557698Z-layout-regression/run.json),
[결함 사례](../results/20260927T143523.883373Z-layout-lab/run.json).

## 두 수정 방식의 비용

1024×1025 입력, 방식별 warm-up 5회 후 각 20회, 실행 순서 교대. CUDA event로 호출 앞뒤를
측정하며 모든 출력은 측정 밖에서 CPU와 대조했다.

| 배치 | strided 중앙값 | contiguous-copy 중앙값 | PyTorch ReLU 중앙값 |
|---|---:|---:|---:|
| 연속 | 0.256 ms | 0.249 ms | 0.285 ms |
| 전치 | 0.266 ms | 0.418 ms | 0.254 ms |
| 슬라이스 | 0.269 ms | 0.351 ms | 0.273 ms |

이 조건에서는 비연속 입력을 복사한 방식의 추가 비용이 관측됐다. 복사와 호스트 제출로 인한
stream 대기까지 포함하는 구간이며 순수 커널 시간이 아니다. 공유 GPU/WSL·단일 크기 결과로
PyTorch보다 빠른 커널이라고 일반화하지 않는다. stride 지원과 효율적인 메모리 접근은 별개다.
전치 입력의 인접 thread는 떨어진 주소를 읽을 수 있으며 크기·접근 방식별 프로파일링이 더 필요하다.
[전체 표본·소스·빌드·해시](../results/20260927T143527.181130Z-layout-lab/run.json).

## 소스와 근거

- experiments/pytorch/relu_layout.cu: 커널·입력 계약·device/stream·dispatcher 등록.
- experiments/pytorch/layout_ops.py: 빌드·로드·Python 호출.
- experiments/pytorch/layout_lab.py: 입력·CPU 대조·측정·증거 보존.
- tests/pytorch/test_layout.py: 커널·신경망·stream 검사.

[사용자 CUDA 연산](https://docs.pytorch.org/tutorials/advanced/cpp_custom_ops.html),
[stride](https://docs.pytorch.org/docs/2.10/generated/torch.Tensor.stride.html),
[stream 의미](https://docs.pytorch.org/docs/2.10/notes/cuda.html#cuda-streams).
설치된 2.10 헤더와 실제 빌드·실행을 기준으로 하며 최신 튜토리얼 버전과 구분한다.
