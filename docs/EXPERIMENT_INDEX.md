# RF 실험 진행 목차

2026-11-13 기준. 과거 결과, 이번 추가 경량화, 앞으로 할 검증을 구분한다.

## 완료한 작업

| 단계 | 내용 | 근거 자료 |
|---|---|---|
| CICIoT2023 초기 RF·경량화 | 38특징·10패킷, 기준 RF와 특징·트리·깊이 비교, 기기 subset·LOAO | [기존 전체 결과](RESULTS_ALL.md) |
| 기존 결과 재현 | 242개 평가 행 및 혼동행렬·구조·성능 지표 대조 | [재현 방법](RF_REPRODUCTION.md), [전체 표](../results/reproduction_20261025/tables_by_experiment/ALL_TABLES.md) |
| 클래스 균형 비교 | 동일 100만 학습 행, 기존 비율과 50:50, 3설정×3seed×2구성 | [균형 실험 보고서](../results/ciciot2023_balanced_rf/REPORT.md) |
| CICIDS2017 기준선 | PCAPNG 라벨 매칭 및 기존 38특징·10패킷 RF | [설계](CICIDS2017_RF.md), [결과](../results/cicids2017_ddos_benign/REPORT.md) |
| CICIDS2017 기존 window·공식 flow 비교 | 서로 다른 표본·특징·분할에서 설정 탐색, 검증 선택, 테스트 | [설계](CICIDS2017_COMPARISON.md), [결과](../results/cicids2017_comparison/REPORT.md) |
| 이번 RF 추가 경량화 | 27설정 탐색, seed 3회 검증, 최종 15모델 테스트, 별도 속도 측정 | [상세 진행 보고서](../results/ciciot2023_rf_further/REPORT.md), [Word](../results/reports/RF_추가경량화_진행보고.docx) |
| Edge-IIoTset PCAP RF 기준선 | 정상10·DDoS4 PCAP, 기존38특징·10패킷, 고정100트리 RF 및 MLP 공통 표본 저장 | [설계·실행](EDGE_IIOTSET_RF.md), [결과](../results/edge_iiotset_rf/REPORT.md) |

팀원 MLP 실험은 [공통 특징·분할 사용 안내서](EDGE_IIOTSET_MLP_GUIDE.md)에서 시작한다. 데이터는 별도 공유 ZIP으로 전달하며 GitHub에는 코드·안내·지표·해시 목록만 포함한다.

기존 전체 결과와 재현 표의 속도는 당시 실행 환경의 값이다. 최신 추가 경량화의 절대 속도와 섞어 비교하지 않는다. 모델 크기는 비압축 직렬화 MB이며 RAM과 다르다.

## 이번 실험에서 내릴 수 있는 결론

처음에는 구체적인 배포 수치를 정하지 않고 성능·비용 관계를 탐색했다. 기존 10트리 16.73 MB, 깊이 제한 후보 9.91 MB와 그 성능 손실을 참고해 15 MB를 1차 목표, 10 MB를 도전 목표로 정했다. F1 감소 0.005, 정상 오탐·DDoS 미탐 증가 각각 0.001은 산업 표준이 아니라 이전 탐색 결과와 클래스별 추가 오류량을 참고한 잠정 연구 허용치다.

- 검증에서 사전 선택한 **10트리·깊이 20·리프 1**: 평균 9.382292 MB. 최종 테스트에서 세 seed 모두 미탐 증가 한도를 초과해 C1 대체 성공으로 결론 내리지 않았다.
- 함께 평가한 **10트리·깊이 24·리프 1**: 평균 10.002185 MB, 범위 9.902185~10.140105 MB. 세 seed 모두 성능 조건·15 MB·속도 목표를 통과했다. 10 MB 도전 목표는 2/3회다.
- 깊이 24는 **현재 실험에서 성능 기준을 만족한 유망한 후속 검증 후보**다. 테스트를 확인한 뒤 사전 선택을 바꾼 독립 검증 완료 모델로 주장하지 않는다.
- 기존 테스트는 과거에도 관찰했다. 이번 결과를 새로운 환경의 독립적인 일반화 보장으로 해석하지 않는다.

상세 수치·오차·판정·혼동행렬과 발표 질의응답은 최신 보고서에 있다. MLP와 같은 압축률을 강제하지 않으며, 이번 작업은 RF 구조 제어이고 MLP 양자화 실험은 아니다.

## 앞으로 할 일과 하지 않는 범위

미사용 CICIoT2023 캡처는 다운로드·평가하지 않는다. 이후 사용자가 확보한 Edge-IIoTset PCAP은 별도 새 데이터셋 RF 기준선 목적으로 처리했다. 이는 기존 깊이24 경량화 설정의 추가 검증이 아니며 100트리 기준선 실험이다. 정상/공격 수집 파일 라벨을 사용하는 한계와 중복 감사는 전용 보고서에 기록했다.

경량화 설정의 후속 검증을 진행한다면, 확보된 CICIDS2017에서 **10트리·깊이 24·리프 1** 설정을 고정한 뒤 100트리·C1과 같은 표본·분할에서 새로 학습·비교할 수 있다. 현재 저장된 CICIDS2017 결과는 과거 후보 탐색 결과이고 이 고정 설정의 후속 검증 완료를 뜻하지 않는다. 다른 데이터로 새로 학습하면 설정의 적용 가능성을 확인하는 것이며, 기존 CICIoT2023 모델을 그대로 적용하는 데이터셋 간 직접 일반화와 다르다.

다른 데이터에서는 노드 수와 크기가 달라질 수 있으므로 절대 MB와 해당 데이터의 기준 모델 대비 개선율을 함께 평가한다. 실제 엣지 배포 비용은 대상 장치에서 별도 측정해야 한다.

## 재현과 산출물

새 데이터 다운로드 없이 이번 **표·그림·Word 보고서만 재생성**:

```powershell
.\.venv\Scripts\python.exe src/report_ciciot2023_rf_further.py
.\.venv\Scripts\python.exe src/export_rf_progress_word.py
```

전체 추가 실험 재실행은 기존 `data/processed/dataset_v1_parts/` 및 균형 실험이 만든 `data/processed/ciciot2023_balanced_rf/features.float32`, `results/ciciot2023_balanced_rf/protocol.json`이 필요하다. 캐시가 없는 PC에서는 먼저 `src/run_ciciot2023_balanced_rf.py`를 실행해야 하며 이 단계는 균형 실험도 다시 수행한다. 새 PCAP은 필요하지 않다.

```powershell
.\.venv\Scripts\python.exe -u src/run_ciciot2023_rf_further.py
.\.venv\Scripts\python.exe -u src/verify_ciciot2023_rf_further.py
.\.venv\Scripts\python.exe src/report_ciciot2023_rf_further.py
.\.venv\Scripts\python.exe src/export_rf_progress_word.py
```

완료한 실행은 `runs.csv`에서 재개한다. 코드 해시가 달라지면 기존 체크포인트 재사용을 중단하므로 기존 결과를 덮어쓰기 위해 해시만 변경하지 않는다. 재학습보다 지표·표·그림 재생성을 먼저 권한다.

| 파일 | 용도 |
|---|---|
| `runs.csv` | 검증·테스트 52회 실행 지표 |
| `comparisons.csv` | seed별 기준 대비 차이 및 조건 판정 |
| `summary.csv` | 평균·표준편차 |
| `selection.json` | 테스트 전에 고정한 후보 선택 |
| `protocol.json` | 절차·분할·환경·학습 코드 해시 |
| `validation.json` | 과거 결과 대조, 지표 재계산, 모델 재로딩·별도 속도 측정 기록 |
| `benchmark_repeats.csv` | 별도 프로세스의 7회 속도 원자료 |
| `*.png`, `*.pdf` | 검증 탐색 및 최종 성능·비용 그래프 |

GitHub에는 코드·문서·지표·그림·보고서와 검증 기록을 올린다. 새 원본/가공 데이터, 모델 joblib, 특징 캐시, 가상환경, 실행 로그·PID는 올리지 않는다. 이미 과거에 추적한 데이터는 이번에 제거하거나 새로 추가하지 않는다. 저장 모델 15개와 학습 인덱스는 로컬 `data/processed/ciciot2023_rf_further/`에 보존한다.
