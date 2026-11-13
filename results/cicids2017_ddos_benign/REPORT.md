# CICIDS2017 BENIGN / DDoS RF

GitHub에는 코드·설정·지표·검증 JSON·추출 메타데이터(`extraction_metadata/`)를 포함한다. 원본/가공 데이터, 모델 바이너리, 복구 parquet와 실행 로그는 로컬에만 보관한다. 아래 해당 경로들은 로컬 검증 산출물을 가리킨다. 기준선 실험만 완료했으며 sweep·LOAO는 이번 범위에 포함되지 않는다.

Full five-day PCAPNG extraction. Other attacks, unmatched, ambiguous and mixed windows excluded.

38 features; non-overlapping 10-packet windows; 70/30 time split, grouping=source-label; training cap 1,000,000; 100 trees; balanced; seed 42.

- Train rows: 1,000,000
- Test rows: 1,519,689
- Accuracy: 0.99949332
- F1 macro: 0.98118677
- DDoS precision: 0.94133840
- DDoS recall: 0.98490416
- DDoS F1: 0.96262862
- Train seconds: 75.52
- Inference us/sample: 3.781
- Model MB (uncompressed estimate): 16.62

- Wall minutes since initial extraction start: 67.55

Label matching uses time intervals reflecting CSV timestamp precision. This does not guarantee exact packet ground truth. Flows may cross the time split boundary.

If grouping=source-label, the strict per-file split lacked a class and was replaced with chronological splitting within each file and label. This is not a common chronological holdout; see strict_time_label_audit.csv for the unmodified split.

See label_audit.csv, data JSON sidecars, tables/, models/ and run.log for details.

## 데이터와 최종 확인

- 전체 보존 윈도우: **5,065,637개** (BENIGN 5,032,072 / DDoS 33,565).
- 실제 학습 표본: BENIGN 993,457 / DDoS 6,543. 파일·라벨별 시간순 70%에서 seed 42로 최대 100만 행을 선택했다.
- 테스트: BENIGN 1,509,620 / DDoS 10,069. DDoS를 다른 공격과 합치지 않았다.
- 금요일 파일 전체의 원래 70/30 분할은 학습 DDoS가 0개였다. 따라서 파일·라벨별 시간순 분할을 적용했다. 하나의 공통 시각 경계에 대한 미래 예측 평가로 해석하지 않는다.

| 실제 / 예측 | BENIGN | DDoS |
|---|---:|---:|
| BENIGN | 1,509,002 | 618 |
| DDoS | 152 | 9,917 |

각 10패킷의 매칭 후보가 동일한 BENIGN 또는 DDoS 라벨인 윈도우만 평가했다. 원본 라벨의 초/분 단위 시각 정밀도와 혼합·충돌 윈도우 제외로 인한 표본 선택의 한계가 있다. 전체 원본 패킷에 대한 성능이나 다른 데이터셋과 동일 조건의 성능을 뜻하지 않는다.

화요일은 진행률 JSON 교체 시 Windows PermissionError로 중단되어, 정상 종료된 762,869행 parquet 접두부와 20,000 accepted packet 경계를 검증한 뒤 나머지 구간부터 복구했다. 최종 데이터의 첫 762,869행이 기존 접두부와 정확히 일치함을 실제 데이터로 확인했다. 이후에는 진행률 갱신 실패가 추출을 중단시키지 않도록 수정했다.

- [일자별 데이터 요약](dataset_summary.csv)
- [실제 분할의 라벨 분포](label_audit.csv), [원래 날짜별 분할](strict_time_label_audit.csv)
- [저장 모델·혼동행렬·실제 복구 데이터 검증](validation.json)
- [복구 체크포인트](tuesday_recovery_checkpoint.json), 보존된 접두부 `recovery/Tuesday-prefix.parquet`

저장한 모델을 다시 로드해 38개 입력·100개 트리·정상/공격 두 클래스·balanced·seed 42를 확인했다. 테스트 행 수와 혼동행렬 합계가 일치했다. 경계·라벨 제외·시간 분할·전체/복구 추출의 일치·진행률 잠금 실패를 포함한 단위/통합 테스트 5개가 통과했다.
