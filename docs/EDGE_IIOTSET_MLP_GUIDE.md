# 팀원용: Edge-IIoTset MLP 실험 시작하기

## 무엇을 비교하는가

RF와 같은 PCAP에서 만든 **38특징·10패킷 윈도우**, 같은 라벨·학습 표본·테스트로 MLP를 새로 학습한다. 제작자가 제공한 ML/DNN CSV를 따로 사용하는 실험이 아니다. 아래 특징표를 받으면 PCAP 다운로드와 특징 추출은 다시 할 필요가 없다.

정상 PCAP 10개, DDoS HTTP·ICMP·TCP SYN·UDP PCAP 4개를 처리했다. 라벨은 정상 수집 파일=0, DDoS 수집 파일=1인 **파일/시나리오 라벨**이다. 공격 파일의 개별 패킷이 전부 악성임을 독립적으로 확인한 정답은 아니다. 같은 캡처 내부 평가이므로 새 환경 일반화를 입증하지 않는다.

[RF 상세 결과](../results/edge_iiotset_rf/REPORT.md) · [추출·분할 설계](EDGE_IIOTSET_RF.md)

## 1. 코드와 데이터 받기

GitHub에는 코드·사용 안내·실험 지표·특징 순서와 해시 목록이 있다. **학습용 배열과 모델은 GitHub에 포함하지 않는다. 저장소만 clone하면 아래 npy 파일은 없다.**

저장소를 clone하거나 기존 저장소에서 pull한 뒤, 예진에게 `edge_iiotset_mlp_handoff.zip`을 별도로 받아 압축을 푼다. ZIP 안의 `edge_iiotset` 폴더를 프로젝트의 `data/processed/` 아래에 놓는다.

```text
edge_ai_iot_ids_optimization/
├─ docs/EDGE_IIOTSET_MLP_GUIDE.md
├─ results/edge_iiotset_rf/       RF 결과와 공유 설정
└─ data/processed/edge_iiotset/
   ├─ X.float32.npy              (1,935,894, 38), float32
   ├─ y.int8.npy                 (1,935,894,), 정상0 / DDoS시나리오1
   ├─ test_indices.npy           공통 테스트 580,761행
   ├─ rf_train_seed42.npy        RF와 같은 최종 학습 1,000,000행
   ├─ rf_fit_seed42.npy          위 학습 표본 안의 MLP 조정용 fit
   ├─ rf_validation_seed42.npy   위 학습 표본 안의 MLP 조정용 validation
   ├─ ...seed43.npy, ...seed44.npy
   ├─ sample_manifest.parquet    행별 출처·분할 정보, 모델 입력 아님
   ├─ MLP_HANDOFF.json           특징 38개 순서와 파일명
   └─ PACKAGE_MANIFEST.json      파일별 크기·SHA-256
```

ZIP은 학습·검증·테스트 인덱스 전체와 seed 3개를 포함한다. `train_indices.npy`는 전체 앞70% 학습 풀 1,355,133행이고, `rf_train_seed42.npy`는 RF가 실제 쓴 100만 행이다. **공정한 학습 예산 비교에는 rf_train을 사용한다.** `fit_indices.npy`·`validation_indices.npy`는 전체 풀의 내부 분할이며, RF 표본 안의 분할인 `rf_fit`·`rf_validation`과 구분한다.

공개 [파일 해시 목록](../results/edge_iiotset_rf/MLP_PACKAGE_MANIFEST.json)과 전달받은 파일을 대조할 수 있다. 경로는 예진 PC의 절대 경로로 바꿀 필요 없이 프로젝트 루트 기준으로 사용한다.

## 2. 배열 읽기

프로젝트 루트에서 아래 코드를 실행한다. 저장소 `requirements.txt`의 numpy·scikit-learn 등을 설치하고, MLP 프레임워크는 팀원이 사용하는 환경에 맞춰 별도로 준비한다.

```python
from pathlib import Path
import json
import numpy as np
from sklearn.preprocessing import StandardScaler

root = Path('data/processed/edge_iiotset')
handoff = json.loads((root / 'MLP_HANDOFF.json').read_text(encoding='utf-8'))
X = np.load(root / 'X.float32.npy', mmap_mode='r')
y = np.load(root / 'y.int8.npy', mmap_mode='r')
fit_idx = np.load(root / 'rf_fit_seed42.npy')
val_idx = np.load(root / 'rf_validation_seed42.npy')
train_idx = np.load(root / 'rf_train_seed42.npy')
test_idx = np.load(root / 'test_indices.npy')

assert X.shape == (1_935_894, 38)
assert len(handoff['features']) == X.shape[1]
assert len(train_idx) == 1_000_000
assert len(test_idx) == 580_761

# Select the architecture/epochs using fit + validation only.
scaler = StandardScaler()
X_fit = scaler.fit_transform(X[fit_idx])
X_val = scaler.transform(X[val_idx])
y_fit, y_val = y[fit_idx], y[val_idx]
# Train and validate your MLP here. Keep test_idx unused at this stage.
```

RF는 별도 표준화를 사용하지 않아도 되지만 MLP는 학습 데이터로 맞춘 표준화를 사용할 수 있다. 같은 원본 특징 정보와 분할을 유지하되 모델에 맞는 전처리는 기록한다. 배열과 변환 복사본을 함께 메모리에 올리면 약 1 GB 이상 RAM이 필요할 수 있다.

## 3. 최종 비교

설정·epoch 등을 검증 구간에서 결정한 뒤 **전체 rf_train_seed42.npy로 스케일러와 최종 MLP를 새로 학습**한다. 검증 단계의 스케일러를 바꾸면서 기존 MLP 가중치를 그대로 사용하는 방식과 혼동하지 않는다.

```python
final_scaler = StandardScaler()
X_train = final_scaler.fit_transform(X[train_idx])
y_train = y[train_idx]
X_test = final_scaler.transform(X[test_idx])
y_test = y[test_idx]
# Refit the final MLP on X_train/y_train, then evaluate on X_test/y_test.
```

전체 `rf_train`의 일부만으로 최종 MLP를 학습한다면 RF와 학습 예산이 다르다는 것을 보고서에 명시한다. seed 43/44 반복도 대응 파일을 사용하고, MLP 프레임워크 자체의 난수도 따로 기록한다. RF seed와 MLP seed가 같아도 모델 내부 무작위성이 같다는 의미는 아니다.

양자화의 보정·설정 선택에는 학습/검증 표본을 사용한다. FP32와 양자화 모델은 같은 최종 테스트에서 비교하고, 테스트 점수를 보고 설정을 바꾼 경우 독립 최종 검증으로 주장하지 않는다.

## 4. RF와 함께 보고할 지표

정상=0, DDoS시나리오=1로 고정한다. Accuracy·Macro F1·클래스별 Precision/Recall, 정상 FPR=FP/(TN+FP), DDoS FNR=FN/(TP+FN), TN/FP/FN/TP를 저장한다.

RF 기준선의 seed 3회 평균은 Accuracy **99.9888%**, Macro F1 **0.999886**, FPR **0.0191%**, FNR **0.0008%**다. RF 표는 [runs.csv](../results/edge_iiotset_rf/runs.csv), 조건은 [protocol.json](../results/edge_iiotset_rf/protocol.json)에 있다. 이 수치를 MLP가 넘어야 하는 목표값으로 강제하지 않는다.

모델 크기는 단위·저장 형식·압축 여부를 밝힌다. RF의 8.464 MB는 비압축 joblib RF 객체 크기이며 RAM 사용량이 아니다. 추론 시간은 가능한 같은 장치·동일 테스트 표본 수·동일 배치 조건에서 측정한다. 모델 호출 시간과 패킷 대기·특징 추출을 포함한 전체 지연을 구분한다.

테스트의 약 30.1%는 전체 RF 학습 풀과 동일한 38특징 벡터를 갖는다. RF는 같은 특징을 실제 학습 표본에서 본 테스트 행을 제외한 민감도 분석도 저장했다. 이는 원시 패킷 중복 확정이나 새 환경 검증을 뜻하지 않는다. 비교 목적에 따라 동일한 보조 평가도 함께 제시한다.

## 예진이 공유 ZIP을 다시 만드는 방법

기존 로컬 특징표가 있는 PC에서 다음을 실행한다. 재추출·RF 재학습은 하지 않는다.

```powershell
.\.venv\Scripts\python.exe src/package_edge_iiotset_mlp.py
```

생성 위치는 `data/exports/edge_iiotset_mlp_handoff.zip`이다. 이 ZIP은 데이터이므로 Git에 추가하지 않고 별도 파일 공유 수단으로 전달한다. GitHub에 공개되는 것은 이 안내서와 특징 순서·파일 해시 목록이다.
