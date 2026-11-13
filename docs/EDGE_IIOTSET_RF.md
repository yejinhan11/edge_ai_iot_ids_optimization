# Edge-IIoTset PCAP RF 기준선

## 목적

정상 10개 및 DDoS HTTP·ICMP·TCP SYN·UDP PCAP 4개에서 기존 38특징·비중첩 10패킷 방식의 100트리 RF 기준선을 학습한다. 이번 범위는 새 데이터셋의 기준 RF이며 추가 경량화·양자화·MLP 학습은 포함하지 않는다.

## 라벨 범위

입력 위치는 `data/raw/edge_iiotset/Normal traffic/`와 `Attack traffic/`이다. [원 논문](https://doi.org/10.1109/ACCESS.2022.3165809)의 정상/공격별 파일 구성을 근거로 파일·시나리오 라벨을 사용한다. 현재 PCAP만 확보되어 패킷별 정답 매칭은 수행하지 않는다. 따라서 공격 파일의 배경 정상 패킷을 별도로 식별했다거나 순수 악성 패킷만 평가했다고 주장하지 않는다. 연구 결과는 정상/DDoS 수집 시나리오 윈도우 분류로 해석한다.

## 처리

1. 파일 SHA-256과 코드 해시를 기록한다. 모든 파일 샘플에서 기존 추출기와 불필요한 계산을 생략한 방식의 출력 일치를 확인한다.
2. IPv4/ARP 채택 패킷 20,000개씩 청크를 나누고, 기존 10패킷 윈도우·38특징을 추출한다. LLC 제외, 짧은 윈도우·큰 IAT 아티팩트 제외, Rate 상한·Std/Variance 보정은 기존 정책과 같다.
3. 각 파일의 추출 순서 앞 70%는 학습 풀, 뒤 30%는 테스트다. 같은 캡처 내부 분할이며 연결 분리나 새로운 환경 일반화가 아니다. 파일명·주소·라벨·원시 시간은 입력에서 제외한다.
4. 최대 100만 학습 행, RF 100트리, 깊이 무제한, 최소 리프 1, class_weight=balanced를 seed 42/43/44로 평가한다. 클래스 수를 50:50으로 재표집하지 않는다.
5. 정확히 동일한 특징이 학습과 테스트에 나타나는지 감사하고, 실제 학습 표본과 동일 특징인 테스트를 제외한 민감도 분석도 함께 저장한다. 주 평가의 시간순 표본은 유지한다.
6. MLP용 특징 배열·라벨·동일 테스트 분할·RF 학습 표본 인덱스를 로컬에 저장한다. MLP 정규화는 학습 데이터로만 맞춰야 한다.

## 실행

```powershell
.\.venv\Scripts\python.exe -u src/prepare_edge_iiotset.py
.\.venv\Scripts\python.exe -u src/run_edge_iiotset_rf.py
.\.venv\Scripts\python.exe src/report_edge_iiotset_rf.py
```

특징 추출은 청크 및 파일 단위로 재개된다. 코드·입력이 달라지면 오래된 체크포인트를 조용히 재사용하지 않고 중단한다. 진행 상황은 `results/edge_iiotset_rf/status.json`, 실패 사유는 `failure.json`에 기록한다.

## 산출물

- 지표·설정·라벨 한계·그래프: `results/edge_iiotset_rf/REPORT.md`.
- 파일별 추출량: `extraction_summary.csv`, `extraction_metadata/*.json`.
- 원 추출기 대조: `backend_equivalence.json`.
- 분할·RF 설정: `protocol.json`, `partition_audit.csv`.
- 중복·라벨 충돌: `leakage_audit.json`, `sensitivity_seed*.csv`.
- seed별 전체 지표와 혼동행렬: `runs.csv`, 파일별 오류율: `per_source_seed*.csv`.
- 모델·특징표·인덱스: `data/processed/edge_iiotset/`(Git 제외).
- 팀원 전달 안내: `data/processed/edge_iiotset/MLP_HANDOFF.json`.

## MLP에서 같은 표본 불러오기

**팀원에게 전달할 문서:** [MLP 시작 안내서](EDGE_IIOTSET_MLP_GUIDE.md). GitHub에는 데이터 배열이 없으므로 별도 공유 ZIP을 받은 뒤 아래 코드를 실행한다. ZIP 생성·전달 경로와 최종 재학습·정규화 방법은 해당 안내서에 설명했다.

```python
from pathlib import Path
import numpy as np

root = Path('data/processed/edge_iiotset')
X = np.load(root / 'X.float32.npy', mmap_mode='r')
y = np.load(root / 'y.int8.npy', mmap_mode='r')
train_idx = np.load(root / 'rf_train_seed42.npy')
test_idx = np.load(root / 'test_indices.npy')
X_train, y_train = X[train_idx], y[train_idx]
X_test, y_test = X[test_idx], y[test_idx]
```

RF가 실제 사용한 100만 행 예산 안에서 MLP의 epoch·설정을 검증하려면 `rf_fit_seed42.npy`와 `rf_validation_seed42.npy`를 사용한다. 결정 후 전체 `rf_train_seed42.npy`로 재학습하면 최종 RF와 같은 학습 표본으로 비교할 수 있다. 스케일러는 해당 단계의 학습 표본에서만 fit한다. `test_indices.npy`의 정답을 이용해 설정이나 양자화 수준을 고르지 않는다.

과거 CICIoT2023 결과는 첫 청크 중심 PCAP 부분집합이며, 이번 Edge-IIoTset은 확보한 14개 PCAP 전체를 처리한다. 원 논문 CSV의 특징·표본 단위와도 다르므로 외부 논문의 점수 및 과거 실행의 절대 추론 시간을 직접 우열 비교하지 않는다.
