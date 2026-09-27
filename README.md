# Edge-AI IoT IDS optimization (CICIoT2023 DDoS)

전자공학종합설계 프로젝트. CICIoT2023 PCAP에서 공식 39-feature를 추출해 Random Forest로 DDoS를 탐지하고,
**전체 / Camera / 트래픽 최다 기기(Echo Dot 1) / AMCREST 카메라** subset 간 정확도·F1·추론속도·모델 크기·메모리를 비교한다.

## 데이터 (data/, git 제외)

| 경로 | 내용 |
|---|---|
| `data/raw/pcap/` | CICIoT2023 PCAP 16개 (DDoS 12 + BenignTraffic 0~3, Benign 4개는 같은 16시간 캡처의 연속 청크) |
| `data/interim/device_summary/` | Colab EDA 산출물: MAC별 송수신 통계 (`all_devices_summary.csv` 등) |
| `data/interim/features_meta/` | 파일당 `*_meta.csv`(39 feature + 12 metadata 컬럼) + `*_meta.json` 사이드카 |
| `data/processed/dataset_v1.parquet` | 병합·정제·라벨·기기 태그가 붙은 학습 데이터 |
| `data/legacy/` | 1차 실험(자체 numpy feature) 캐시와 결과. 참고용 |

**중요 – PCAP 잘림.** 13개 중 11개 파일 크기가 정확히 2,048,000,0xx bytes로, 원본이 `tcpdump -C 2048`로
분할된 것 중 **첫 번째 청크만** 보유한 상태다. 논문(Table 3)의 행 수와 비교하면 flood류는 원본의 약 5~10%다.
따라서 이 저장소의 모든 결과는 "각 공격 캡처의 앞 약 2 GB 구간"에 대한 것이다.

| PCAP | 로컬 패킷 수 | 논문 CSV 행 수 (×100 패킷/행) | 로컬 비율(대략) |
|---|---:|---:|---:|
| DDoS-SYN_Flood | 26,597,011 | 4,059,190 | 6.5 % |
| DDoS-ICMP_Flood | 26,793,240 | 7,200,504 | 3.7 % |
| DDoS-HTTP_Flood (온전) | 2,881,005 | 28,790 | 100 % |
| DDoS-SlowLoris (온전) | 2,351,454 | 23,426 | 100 % |

## 기기 정보 (config/devices.csv)

논문 Table 1(Neto et al., Sensors 2023)의 MAC 보유 기기 70개 + 게이트웨이 후보 1개.
- `role=attacker`: 논문이 Attackers로 분류한 Raspberry Pi 7대. 나머지 RPi 3대는 논문상 victim이지만 HTTP_Flood에서
  공격 트래픽을 송신하므로 subset 태깅에서는 10대 모두 비피해 기기로 취급한다.
- `3C:18:A0:41:C3:A0`(gateway_candidate)는 논문에 없고 EDA에서 추정한 게이트웨이다 (`verified=False`).

## 파이프라인 (src/)

```
.venv\Scripts\activate
python src/eda_devices.py                        # 저장된 EDA CSV -> results/tables/eda_*.csv (pcap 재스캔 없음)
python src/extract_features.py --workers 6       # pcap -> data/interim/features_meta/*_meta.csv (재개 가능)
python src/build_dataset.py                      # -> data/processed/dataset_v1.parquet
python src/train_rf.py --tag v1                  # -> results/tables/rf_v1.csv
python src/train_rf.py --tag loao_syn --split loao --holdout DDoS-SYN_Flood
```

### 특징 추출 (`extract_features.py`)
- `tools/pcap2csv_metadata_v2/Feature_extraction_fast.py` = 공식 CICIoT2023 pcap2csv 추출기에서
  (1) `rdpcap()` 전체 로드 제거, (2) 10패킷 윈도우 집계를 groupby로 벡터화한 것. 세 샘플 pcap에서 원본과 출력이
  수치·문자열 모두 완전히 일치함을 확인했고 5~6배 빠르다.
- tcpdump 대신 `split_pcap.py`가 **채택 패킷(IPv4/ARP) 2만 개** 단위, 10패킷 경계에 맞춰 분할한다 → 청크 경계에서
  깨지는 윈도우가 없다.
- 윈도우 크기는 모든 파일 **10패킷**으로 통일 (논문 공식 CSV는 DDoS 100 / Benign 10으로 달라 윈도우 크기 자체가
  라벨을 누설할 수 있음).
- metadata 컬럼(`primary_src_mac`, `primary_dst_mac`, `all_macs` 등)은 subset 선택에만 쓰고 RF 입력에 넣지 않는다.
- 실측(6 workers, 청크 2만 패킷): flood 2 GB 파일 25~65분, Fragmentation/SlowLoris 2~6분, Benign 2 GB 30~65분
  (정상 트래픽은 flow가 다양해 공식 추출기 내부 처리량이 많다). 16개 파일 합계 20,990,344 윈도우, CSV 7.7 GB.
- 청크를 크게 잡으면(10만 패킷) 패킷당 처리 시간이 급증하므로 2만 패킷을 기본값으로 둔다.

### 데이터셋 (`build_dataset.py`)
- 정제: 10패킷 미만 윈도우 제거, `IAT > 1e5 s`(청크 첫 윈도우 아티팩트) 제거, `Rate=inf` → 1e7 상한, `Std/Variance` NaN → 0,
  `LLC` 컬럼 제거(원본 버그로 항상 1). 최종 **38 feature**.
- 기기 태그: `all_macs`에서 RPi·게이트웨이·브로드캐스트를 제외한 MAC을 피해 기기로 보고
  `has_camera`, `has_echo_dot1`, `has_amcrest`, `victim_device`, `victim_category` 생성.

### RF 실험 (`train_rf.py`)
- split `time`: 파일별 앞 70% 학습 / 뒤 30% 평가. split `loao`: 공격 한 종류를 통째로 hold-out.
- 평가 subset: all / camera / echo_dot1 / amcrest. 지표: Accuracy, Precision, Recall, F1, F1(macro), majority baseline,
  단일 스레드 추론 시간(µs/sample, samples/sec), 모델 크기(MB), 트리 노드 수, 피크 메모리.

## 다른 PC에서 이어서 작업하기

```
git clone git@github.com:yejinhan11/edge_ai_iot_ids_optimization.git   # 또는 https 주소
cd edge_ai_iot_ids_optimization
python -m venv .venv
.venv\Scriptsctivate            # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python src	rain_rf.py --tag check   # git에 포함된 data/processed/dataset_v1_parts/ 로 바로 실행됨
```

git에 **포함된** 데이터: `data/processed/dataset_v1_parts/`(학습 데이터, 6개 zstd parquet ≈ 220 MB),
`data/interim/device_summary/`, `data/interim/*.csv`, `data/interim/features_meta/*.json`(사이드카), `results/tables/`.
RF·경량화 실험은 이것만으로 충분하다.

git에 **없는** 데이터 (필요할 때만 Drive/외장디스크로 직접 복사):
| 경로 | 크기 | 언제 필요한가 |
|---|---|---|
| `data/interim/features_meta/*.csv` (16개) | 7.7 GB | `build_dataset.py`로 태그·정제 규칙을 바꿔 parquet를 다시 만들 때 |
| `data/raw/pcap/*.pcap` (16개) | 24 GB | `extract_features.py`로 feature 추출을 다시 할 때 |
| `results/models/*.joblib` | 50~650 MB | 학습된 모델을 재사용할 때 (다시 학습하면 됨) |
| `data/legacy/rf_cache/` | 350 MB | Colab 1차 실험 캐시, 불필요 |

SSH 키는 PC마다 새로 만들어 GitHub 계정(또는 저장소 Deploy key)에 등록해야 한다.

## 폴더

```
config/devices.csv     단일 MAC↔기기 테이블
src/                   파이프라인 스크립트
tools/                 공식 pcap2csv 추출기(원본 + metadata v2 + fast)
notebooks/             Colab 노트북 아카이브 (실행 결과 포함)
results/tables/        결과 CSV,  results/models/ 학습 모델(git 제외)
docs/references/       논문 PDF
```
