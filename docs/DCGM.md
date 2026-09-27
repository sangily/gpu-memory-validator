# DCGM 실습과 검증 범위

## 실행 결과

RTX 3060 / WSL2 Ubuntu 22.04 / Windows 드라이버 591.86에서 NVIDIA DCGM 4.6.1을 실행했다.
버전을 고정한 NVIDIA Ubuntu 패키지를 프로젝트의 build 디렉터리에 풀고 사용자 권한으로
host engine을 실행했다. 시스템 드라이버·서비스는 변경하지 않았다.

| 단계 | 실제 관측 |
|---|---|
| `dcgmi discovery -l` | RTX 3060 한 대 검색 성공 |
| `dcgmi dmon` | 온도 49°C, 전력 약 37.7~38.2 W, GPU 사용률 16~18% 수집; 3개 표본 |
| `dcgmi diag -r 1 -i 0 -j` | Deployment/software **Fail**, error_id=20, 프로세스 종료 226 |
| 환경 확인 | `/dev/dxg` 존재, `/dev/nvidia*` 없음; 비관리자 실행 경고 |
| 고급 메모리·PCIe·부하 진단 | 실행하지 않음. PASS로 간주하지 않음 |

진단 메시지는 NVML이 보고한 GPU 수와 `/dev` 장치 수가 다르다는 내용이다.
관측한 장치 노드 구성상 WSL의 장치 노출 방식과 관련된 환경 검사 실패로 해석한다.
권한·드라이버 기능 제한도 별도로 존재하므로, 이를 GPU 메모리 불량으로 단정하지 않는다.
온도·전력 수집 성공도 진단 통과를 의미하지 않는다.

[원시 명령·종료 코드](../results/20260927T125551.327375Z-dcgm/dcgm_lab.json),
[진단 JSON](../results/20260927T125551.327375Z-dcgm/diag-level1.stdout.txt),
[지표](../results/20260927T125551.327375Z-dcgm/telemetry.stdout.txt)를 보존했다.

## 재현

저장소 루트에서 실행한다. `setup.py`는 고정된 NVIDIA 패키지 두 개(총 약 410 MB)를
다운로드하고 SHA256을 확인해 `build/dcgm-4.6.1/root`에 푼다. 시스템 패키지 설치가 아니다.
manifest는 `experiments/dcgm/packages.json`이며, Linux x86_64 / CUDA 13 드라이버용이다.
현재 Windows 드라이버가 표시한 지원 버전은 CUDA 13.1이고, 프로젝트 컴파일러 12.8과는 구분한다.

```bash
source cuda-env.sh
python3 experiments/dcgm/setup.py
python3 experiments/dcgm/probe.py
```

이미 준비된 환경에서는 setup을 생략한다. probe는 전용 Unix socket으로 foreground host engine을
실행하고 장치 검색·지표 수집·Level 1 진단 후 종료한다. 원시 출력, 환경, 패키지·실행 파일 해시,
엔진 로그와 명령을 새 결과 폴더에 저장한다. 진단 실패 시 probe 종료 코드는 2다.
`capture_status=CAPTURED`는 로그 수집 완료이며 GPU 정상 판정이 아니다.

실제로 전달한 핵심 명령은 다음과 같다. `<socket>`은 probe가 만든 전용 경로다.

```bash
dcgmi discovery --host unix://<socket> -l
dcgmi dmon --host unix://<socket> -i 0 -e 150,155,203,204 -c 3 -d 1000
dcgmi diag --host unix://<socket> -r 1 -i 0 -j -t 30
```

## 자체 도구와의 비교

NVIDIA 문서는 GeForce의 기본 진단 지원을 Level 1로 안내한다. 상위 진단은 제품별 지원을
확인해야 하며, 공식 지원 환경에는 bare metal과 full GPU passthrough VM이 기재되어 있다.
현재 WSL 실행 결과로 데이터센터 GPU나 HBM의 진단 가능 여부를 일반화하지 않는다.
[공식 설치·지원 범위](https://docs.nvidia.com/datacenter/dcgm/latest/installation.html)

| 진단 관점 | DCGM 문서의 범위 | 이 프로젝트 |
|---|---|---|
| 배포 환경 | 라이브러리·장치 접근 등의 검사 | DCGM 실습에서 환경 실패 원인 기록; 자체 도구는 CUDA 호출 오류 보고 |
| 메모리 데이터·위치 | memtest의 주소·다양한 데이터 패턴 | 상수 + index + seeded 패턴, CPU 전체 대조 |
| 검출 결과 신뢰성 | 진단 상태·오류 코드·경고 | XOR 주입, 전체 오류 수·K개 기록·잘림·독립 대조 |
| 동작 중 지표 | 지원되는 온도·전력·사용률 등 | DCGM 지표 실습; 일반 실행기는 nvidia-smi 지표 저장 |
| 이동·반전·유지 검사 | block move, moving inversions, bit fade 등 | 병렬 비트 반전·재검사 추가; 방향 순회·이동·유지 검사는 미구현 |
| 부하·연산·전송 | 메모리/GEMM/PCIe/NVLink/전력 시험 | 256 MiB 반복 읽기 약 10분, PyTorch 사용자 CUDA 연산; GEMM·전송·전력 스트레스 미구현 |
| ECC·XID·물리 원인 | 지원 HW/드라이버의 오류 지표 | 수집·판정 미구현, 물리 주소·HBM 결함 분석 미검증 |

[DCGM Diagnostics](https://docs.nvidia.com/datacenter/dcgm/latest/learn/modules/dcgm-diagnostics.html),
[Memtest 패턴](https://docs.nvidia.com/datacenter/dcgm/latest/reference/diagnostics/plugins/memtest.html)을
범위 비교의 기준으로 삼았다. 자체 구현은 DCGM 알고리즘의 복제나 동등성 검증이 아니다.

## 추가한 위치·seed 패턴

값 반전과 실패 시점의 데이터 보존은 [읽기·반전 검사](INVERT.md),
AI 워크로드의 메모리 배치·stream 검사는 [PyTorch–CUDA 실습](LAYOUT.md)에 정리했다.

같은 상수만 채운 배열에서는 두 위치의 값을 바꾸어도 변화가 없다. `index`는 위치에 따라
기대값이 달라져 이 구분을 보완한다. `seeded`는 위치·seed를 32비트 정수로 섞어 서로 다른
비트 조합을 재현 가능하게 만든다. 정확한 식과 실행 방법은 [입력 설정](INPUTS.md)에 있다.

GPU fill/verify는 같은 device 함수를 사용하지만 CPU는 별도 함수로 전체 스냅샷을 대조한다.
고정 정답, 값 교환, 상수로 잘못 채운 버퍼, CPU/GPU 오류 기록 불일치를 검사한다.
값 교환 검사는 합성 CPU 데이터 검사이며 물리 주소선 고장을 재현한 것은 아니다.
실제 GPU에서는 세 모드의 정상·XOR 주입·작은 배열·tail·기록 제한·반복 109개를 확인했다.
128/256 MiB에서는 index/seeded 각각 정상·주입 8개 실험을 수행했다. 각 실험은 두 값×4회 반복이며
CPU 전체 대조를 유지했다. 정상은 PASS, 주입은 오류 3건을 검출하고 최종 FAIL을 유지했다.
[조건별 결과](../results/20260927T125846.124407Z-spatial-matrix/matrix.json)의 한 실행은 약 1.6~3.2초다.
이 기록은 큰 배열 반복의 정확성 증거이며 장시간 부하 시험 결과가 아니다.

별도로 GPU 반복 읽기와 CPU 체크포인트를 분리해 256 MiB에서 609.94초 실행했다.
GPU 검사 409,600회·CPU 대조 400회가 PASS였고, 별도 512회차 오류 주입도 검출했다.
GPU 지표 수집은 581회 중 579회 성공, 2회 조회 시간 초과로 PARTIAL이다.
정확한 조건·그래프·한계는 [반복 읽기 실험](LOAD.md)에 있다. DCGM 고급 진단 통과를 대신하지 않는다.

할당한 영역만 검사하며 전체 VRAM을 검사하지 않는다. RTX 3060은 GDDR6 장비다.
CPU 전체 복사·대조가 포함되므로 반복 실행 시간을 GPU 포화 부하 시간이나 메모리 대역폭으로
표현하지 않는다. Compute Sanitizer는 기존 WDDM 초기화 문제로 미검증이다.
