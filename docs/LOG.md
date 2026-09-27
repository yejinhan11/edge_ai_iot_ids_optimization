# 진행 로그 (docs/LOG.md)

새 항목은 위에 추가. 날짜 · 한 일 · 결과 · 결정 · 다음 할 일.

---

## 2026-09-26 — 오디오 subset, 논문 비교, 경량화 계획

### 한 일
- `has_audio` 태그 추가(`build_dataset.py`, `devices.AUDIO_MACS`), parquet 재구축. 오디오 윈도우 16.5M (DDoS 수신의 대부분).
- RF 재실행: `v1`(전체 학습, 5개 subset 평가), `v1_audio`(오디오 윈도우만 학습).

### 결과 (같은 실행 안에서 측정, results/tables/rf_v1.csv, rf_v1_audio.csv)
| 실험 | 학습 | 테스트 | Acc | F1(macro) | Recall | 추론 µs/샘플 | 모델 MB |
|---|---|---|---:|---:|---:|---:|---:|
| A | 전체 | 전체 (6.30M) | 0.9920 | 0.9621 | 0.992 | 5.9 | 95 |
| B | 전체 | 카메라 (1.57M) | 0.9713 | 0.9578 | 0.965 | 8.8 | 95 |
| B' | 전체 | 오디오 (4.04M) | 0.9935 | 0.9519 | 0.994 | 5.4 | 95 |
| C | 카메라 | 카메라 | 0.9718 | 0.9585 | 0.966 | 19.6 | 649 |
| C' | 오디오 | 오디오 | 0.9934 | 0.9511 | 0.993 | 4.2 | 51 |
| C'→카메라 | 오디오 | 카메라 | 0.9676 | 0.9526 | 0.961 | 6.8 | 51 |
- 오디오 subset은 DDoS 비율이 96.8%라 Accuracy는 높지만 F1(macro)는 카메라보다 낮음(Benign 오디오 윈도우가 적어 Benign 쪽 F1이 약함).
- 오디오만으로 학습한 모델도 카메라 테스트에서 0.968로 큰 손실 없음 → DDoS 패턴은 기기 종류에 크게 의존하지 않음.
- 추론속도 절대값은 실행 시점 PC 부하에 따라 ±50% 변동. 비교는 같은 실행 안의 값끼리만.

### 논문 vs 우리 결과 (직접 비교 불가, 보고서용 정리)
- 논문 RF 2-class: Acc 0.9968 / F1 0.9653 / Recall 0.9652. 우리 A: Acc 0.9920 / F1m 0.9621 / Recall 0.9919.
- 차이 요인: (1) 논문은 공격 33종 전부 vs Benign, 우리는 DDoS만 (2) 데이터 548 GB vs 첫 2 GB 청크 (3) 논문은 섞은 뒤 80/20 무작위 분할, 우리는 파일별 시간순 70/30 (4) 46 feature·윈도우 100/10 vs 38 feature·윈도우 10 (5) Benign 비율 2.4% vs 5.2% (6) 우리 Benign은 같은 캡처의 연속 4청크.

### 다음 할 일: 경량화 실험 (`src/sweep_rf.py`, 약 1~1.5시간)
1. feature 선택: 중요도 상위 5/10/15/20/38 (트리 100, 깊이 무제한).
2. 트리 수: 10/20/50/100 (feature는 1에서 선택).
3. 깊이: max_depth 8/12/16/무제한, min_samples_leaf 1/10/100.
4. 최종 후보 2~3개를 전체·카메라·오디오 subset + LOAO(SYN, SlowLoris)로 재검증, 기준선과 표.
- 판단 기준은 Accuracy가 아니라 F1(macro)·Recall. 산출: `results/tables/sweep_*.csv`, 산점도(정확도 vs 추론속도, vs 모델 크기).

---

## 2026-09-25 — 로컬 전환, 전체 추출, 1차 RF 결과

### 한 일
- Colab에서 로컬(Windows 11, Python 3.11, 24 GB RAM, 8 코어)로 이전. `data/ src/ tools/ notebooks/ results/` 구조로 재구성, `.venv` 생성, git 초기화 → `github.com/yejinhan11/edge_ai_iot_ids_optimization`.
- `config/devices.csv` 작성: 논문 Table 1의 MAC 보유 기기 70개 + 게이트웨이 후보 1개. 논문 전체 110행은 `config/devices_paper_table1.csv`.
- 공식 추출기 고속화: `Feature_extraction_fast.py` (rdpcap 제거 + 윈도우 집계 벡터화). 샘플 3개에서 원본과 출력 완전 일치, 5~6배 빠름. tcpdump 대신 `split_pcap.py`로 2만 패킷(10의 배수) 단위 분할.
- Benign 청크 3개(`BenignTraffic1~3.pcap`) 추가 다운로드 → Benign이 파일 4개, 약 110만 윈도우.
- 16개 PCAP 전부 추출 완료: 20,990,344 윈도우, CSV 7.7 GB. flood 2 GB 파일당 25~65분, Benign 30~65분.
- `build_dataset.py` → `data/processed/dataset_v1.parquet` 20,990,150행 (Benign 1,097,877 / DDoS 19,892,273), feature 38.
- RF 실험 4개 실행 (100 트리, 학습 100만 행, class_weight=balanced).

### 결과 (results/tables/rf_comparison.csv)
| 실험 | 학습 | 테스트 | Acc | F1(macro) | Recall | 추론 µs/샘플 | 모델 MB |
|---|---|---|---:|---:|---:|---:|---:|
| A `v1` | 전체 | 전체 (6.30M) | 0.9920 | 0.9621 | 0.992 | 9.6 | 95 |
| B `v1` | 전체 | 카메라 (1.57M) | 0.9713 | 0.9578 | 0.965 | 12.4 | 95 |
| C `v1_cam` | 카메라 | 카메라 (1.57M) | 0.9718 | 0.9585 | 0.966 | 19.6 | 649 |
| LOAO SYN | SYN 제외 | SYN 전체 | 0.9981 | 0.9951 | 0.999 | 6.4 | 104 |
| LOAO SlowLoris | SlowLoris 제외 | SlowLoris 전체 | 0.8092 | 0.7820 | 0.549 | 14.7 | 44 |

- 카메라 전용 학습(C)은 전체 학습(B)과 정확도가 같고 모델만 7배 커짐 → 카메라 전용 모델은 경량화 근거가 안 됨.
- 처음 보는 flood(SYN)는 잡지만 저속 공격(SlowLoris)은 recall 0.55 → 모델이 대량 트래픽 패턴에 의존.
- Echo Dot 1 subset은 time split 테스트에 51k행뿐(공격 대상이 캡처 후반에 바뀜), recall 0.75. 보고 시 주의.
- Colab 1차 결과(전체 0.97 / 카메라 0.87)와 다른 이유: 공식 feature 사용, 카메라 정의 변경, 파일당 앞 200만 패킷 제한 제거.

### 기기 종류 조사 (results/tables/paper_device_category_counts.csv, data_device_category_counts.csv)
- 논문 Table 1 기기 수: Power Outlet 20, Camera 19, Sensor 19(모두 Zigbee/Z-Wave, MAC 없음), Home Automation 16, Lighting 12, Audio 8, Hub 6, RPi 10.
- 우리 PCAP에서 MAC으로 식별된 기기 수: **Camera 17 (1위)**, Power Outlet 14, Audio 8, Home Automation 8, Lighting 7, Hub 6. 센서류는 PCAP에 안 나타남.
- Benign 윈도우의 71.7%가 카메라 트래픽(Arlo Q 하나가 57%). DDoS 수신 트래픽은 Audio(Echo Dot 1)가 압도적.
- 결론: "카메라 = 데이터에서 가장 많이 관측된 기기 종류이자 정상 트래픽의 대부분" → 카메라 subset 선정 근거.

### 결정
- 특징 추출은 공식 39-feature + MAC metadata 방식으로 확정, 윈도우 10패킷 통일.
- PCAP은 현재 2 GB 청크로 진행(원본 548 GB 불가), 보고서에 명시.
- git commit/push는 사용자가 직접.

### 미해결 / 주의
- 미등록 MAC `24:05:88:30:6F:89`(Benign 52k 윈도우), `56:4F:8A:E1:F3:2D`, `EE:06:3B:B8:D1:DF`: 논문 표에 없음. 정체 확인 필요.
- 게이트웨이 후보 `3C:18:A0:41:C3:A0`는 추정.
- 논문 본문(105대)과 Table 1(110행) 불일치.

### 다음 할 일
1. 경량화 실험: feature 중요도 상위 k개(10/15/20), 트리 수(20/50/100), max_depth(10/20) 조합으로 A·B 재측정 → 정확도 vs 추론속도·모델 크기 곡선.
2. (선택) 카메라 subset 정의를 `victim_category == Camera`(대표 기기 기준)로도 계산해 `has_camera`와 비교.
3. 보고서용 그림: 카테고리별 기기 수·트래픽, RF 결과 막대그래프, feature 중요도.

---

## ~2026-09-24 — Colab 단계 (요약)
- 12개 DDoS PCAP EDA: MAC별 송수신 통계 (`data/interim/device_summary/`), 카테고리별 통신량 (`pcap_summary.csv`, `mac_counts.csv`).
- 공격자 = Raspberry Pi 7대(DC:A6:32:*, E4:5F:01:*), 최다 피해 = Echo Dot 1 / Echo Spot / Nest Mini(Audio), 카메라 중 최다 피해 = AMCREST.
- 자체 numpy feature로 RF 1차 실험 (`data/legacy/`): 전체 0.97, 카메라 0.87. Benign 파일 1개·파일당 200만 패킷 제한으로 신뢰도 낮음.
- 공식 추출기 + MAC metadata v2로 SYN_Flood 1개 추출 (Colab 3시간).
- 노트북 원본은 `notebooks/`에 보관.
