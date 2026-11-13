# CICIDS2017의 두 RF 방식 비교

BENIGN=0 / DDoS=1만 사용한다. 다른 공격을 DDoS로 바꾸지 않는다. 기존 방식은 CICIoT2023에 최적이라고 확정된 방법이 아니라 기존 실험의 38개 특징 정의·10패킷 윈도우다. 이번 작업은 그 방식을 대조군으로 검증하면서 CICIDS2017 공식 flow 통계의 후보 특징과 RF 설정을 탐색한다.

## 서로 다른 두 표본

| arm | RF 입력 표본 | 특징 후보 | 데이터 |
|---|---|---|---|
| legacy_windows | 비중첩 10패킷 윈도우 | 기존 38개 특징과 그 부분집합 | 기존 PCAPNG 추출 데이터 5,065,637행 |
| native_flows | CICFlowMeter의 양방향 flow | 식별자 제외 수치 77개, fit 상수 10개 제외 후 67개와 그 부분집합 | 공식 ZIP에서 정제 후 1,991,221행 |

native는 공식 GeneratedLabelledFlows ZIP에서 통계를 읽는다. 기존 38개 특징 추출기로 native 특징을 계산하지 않는다. 시각 변환 함수만 기존 코드와 공유한다. [UNB 공식 설명](https://www.unb.ca/cic/datasets/ids-2017.html)은 CICFlowMeter로 추출한 80개 이상의 flow 특징과 원본 패킷을 함께 제공한다고 설명한다.

native의 RF 입력에서 Flow ID, Source/Destination IP, Source/Destination Port, Timestamp, Label, 중복 헤더 `Fwd Header Length.1`을 제외한다. 숫자 Protocol은 후보에 남긴다. 다른 공격·누락 라벨·유효하지 않은 duration을 제외하고, 수치 특징이 동일한 중복은 최초 기록만 남긴다. 동일 특징에 정상/공격 라벨이 충돌하면 제외한다. 원래 Source IP/port는 연결 그룹을 만드는 메타데이터에만 사용하며 RF에 입력하지 않는다.

두 arm은 표본 단위·라벨·정제·분할이 다르다. flow 점수가 높다고 그 차이가 전부 특징 선택의 효과라는 뜻은 아니다. 순수한 조건 비교는 legacy_windows 안의 baseline, C1–C4, 검증 선택 모델 사이에서 수행한다.

## 학습·검증·테스트

- 기존 window 방식의 바깥 70/30 분할은 이전 실험과 같다. 각 파일·라벨의 보존 윈도우를 시간순으로 두고 앞 70%를 학습 풀, 뒤 30%를 테스트로 둔다. 이미 과거에 관찰한 테스트 구간을 고정해 재사용한다.
- 학습 풀의 앞 80%를 fit, 뒤 20%를 validation으로 둔다. 전체 기준 대략 56/14/30이다. 특징 순위와 설정을 고를 때 test 지표는 사용하지 않는다.
- native는 같은 날짜의 양방향 5-tuple 전체를 한 그룹으로 묶는다. 그 안의 정상/공격 flow도 같은 분할에 둔다. 그룹 첫 시각 기준으로 날짜·그룹 라벨 안에서 시간순 분할한다. 그룹 전체를 유지하므로 개별 flow의 시각은 경계를 넘을 수 있으며 엄격한 공통 시각 미래 예측 평가는 아니다. 실제 분포는 partition_audit.csv에 남긴다.
- 결측·무한대의 중앙값은 fit 구간에서만 추정한다. 상수 제거도 fit 구간에서만 결정한다. 최종 재학습에서는 선택한 특징을 유지하고 학습 풀에서 최대 100만 행을 추출해 중앙값과 RF를 다시 학습한다.
- 선택 모델은 동일 테스트 분할에서 seed 42/43/44를 반복한다. 이는 학습 난수·표본 선택의 변동이며 새로운 공격 종류나 새 데이터에 대한 평가가 아니다.

## 탐색 범위와 선택 기준

legacy는 원래 경량화와 같은 축을 사용한다: 특징 수 5/10/15/20/38, 트리 10/20/50/100, 깊이 8/12/16/무제한, min_samples_leaf 1/10/100. 모두의 전체 곱이 아니라 기존 단계별 조합을 사용한다. 기본 38특징 RF의 validation macro F1과 DDoS recall이 모두 0.90 이상일 때만 전체 sweep을 진행한다. 이 0.90은 불필요한 반복을 피하기 위한 실행 기준이며 방법의 보편적 적합성을 증명하는 기준이 아니다.

native는 MDI와 validation permutation importance 순위의 상위 5/10/15/20/30/전체 특징을 후보로 둔다. 트리 20/50/100/200, 깊이 8/12/16/무제한, min_samples_leaf 1/10/100, balanced/None/balanced_subsample의 지정 조합 43개를 탐색한다. 먼저 최대 30만 fit 행으로 탐색하고 상위 3개와 baseline을 최대 100만 fit 행으로 재검증한다.

검증 macro F1이 가장 높은 후보를 선택하고, 동점이면 DDoS recall, 적은 특징 수·트리 수를 순서대로 고려한다. 별도 경량 후보는 검증 macro F1 손실 0.001 이내에서 작은 구성을 찾고 최대 100만 fit 행에서 다시 검증한다. 설정을 JSON으로 고정한 뒤 테스트한다. **이번 탐색 범위의 검증 선택이며 전역 최적해를 보장하지 않는다.** 검증 최고 모델이 테스트에서도 항상 최고인 것은 아니며, 테스트를 본 뒤 선택을 바꾸지 않는다.

## LOAO

Leave One Attack Out의 약자다. 예를 들어 CICIoT2023에서 SYN Flood를 학습에서 빼고 다른 DDoS 공격들로 학습한 뒤 SYN Flood를 탐지하는지 확인한다. 처음 보는 공격 유형에 대한 일반화 평가다.

현재 CICIDS2017의 DDoS 범위에는 `DDoS` 라벨 한 종류만 있다. 이를 빼면 정상만 남아서 두 클래스를 학습하는 RF LOAO가 성립하지 않는다. 따라서 이번 LOAO는 **적용 불가**로 기록한다. DoS를 DDoS로 합치거나 시간 구간을 임의 공격 유형으로 바꾸지 않는다.

## 실행과 산출물

```powershell
.\.venv\Scripts\python.exe src/test_cicids2017_comparison.py
.\.venv\Scripts\python.exe -u src/prepare_cicids2017_flows.py
.\.venv\Scripts\python.exe -u src/compare_cicids2017_rf.py
.\.venv\Scripts\python.exe -u src/finalize_cicids2017_comparison.py
```

비교 결과는 `results/cicids2017_comparison/REPORT.md`, `comparison.csv`, `summary.csv`, `figures/`이다. arm별 validation_search.csv / validation_refinement.csv / final_test.csv / selection.json / protocol.json / partition_audit.csv가 상세 기록이다. native 정제 기록은 native_preparation.json에 남긴다. 기존 기준선 결과는 덮어쓰지 않는다.

동일 입력·동일 설정에 대해서는 완료된 탐색과 최종 평가를 재사용한다. 입력이나 프로토콜을 변경하면 이전 결과와 섞지 말고 새 결과 디렉터리를 사용해야 한다.

모델 joblib은 model·medians·features·selected_columns를 가진 묶음이다. 예측 시 동일한 열 순서·결측 처리·선택 열을 적용해야 한다. 모델 추론 비용은 RF.predict만 측정하며 패킷 수집·특징 추출·flow 종료 대기는 포함하지 않는다. edge 실시간 탐지에 어느 방식이 적합한지는 이 지연도 별도로 판단해야 한다.
