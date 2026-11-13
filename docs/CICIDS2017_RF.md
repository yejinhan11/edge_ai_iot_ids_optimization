# CICIDS2017 RF

기존 `src/train_rf.py`와 `Feature_extraction_fast.py`를 재사용한다. CSV의 CICFlowMeter 특징으로 학습하지 않고 PCAPNG에서 기존 CICIoT2023 특징을 다시 계산한다.

- 특징: `build_dataset.FEATURES`의 동일한 38개, 순서 유지, float32. LLC 제외.
- 윈도우: 캡처 순서대로 IPv4/ARP 10패킷, 비중첩. flow별로 재그룹하지 않는다. 미매칭 패킷도 윈도우 구성에는 포함하고, 라벨이 확정되지 않은 윈도우를 나중에 제외한다.
- 추출 청크: 기존 기본값과 같은 accepted packet 20,000개. 청크별 추출기 상태 초기화와 첫 IAT 처리도 기존과 동일하다. 청크 크기를 바꾸면 IAT 경계값 등이 달라질 수 있다.
- 정제: 짧은 윈도우 제외, IAT > 100,000초 제외, Rate 최대 10,000,000, Std/Variance 결측 0. 비유한 특징은 오류로 중단한다.
- RF: 이번 완료 실험은 파일·라벨별 보존 윈도우 시간순 70/30, 학습 최대 1,000,000행 무작위 선택, 100 trees, 깊이 무제한, min_samples_leaf=1, balanced, seed=42, n_jobs=-1. 기존 기본값인 파일 전체 기준 분할과의 차이는 아래에 기록했다.
- 정상 BENIGN=0, DDoS=1만 사용한다. DoS·PortScan·Bot 등 다른 공격이 포함된 윈도우는 제외하며 정상으로 바꾸지 않는다.
- CICIoT2023의 Camera/Audio MAC 목록은 적용하지 않는다. 호환용 subset 열은 False이며 `all`만 평가한다.

## 라벨 매칭 정책

ZIP 안의 당일 CSV 전체를 읽는다(목·금은 여러 CSV). Source/Destination IP·port와 protocol을 정규화해 양방향 5-tuple을 만든다. flow 시작 시각과 duration(마이크로초)을 함께 사용해 다른 시각에 재사용된 tuple을 구분한다.

날짜는 day-first다. CSV 현지 시각은 UTC-3으로 변환하고, AM/PM이 없는 00–07시는 캡처 업무시간에 맞춰 12시간을 더한다. 초가 없는 값은 60초, 초가 있는 값은 1초의 시작시각 불확실성을 갖는 것으로 보고 `[표시 시각, 표시 시각 + 정밀도 + duration]`을 후보 구간으로 사용한다. 이는 보수적인 후보 매칭이며 패킷 단위 정답 복원을 보장하지 않는다. 분 단위 CSV로 짧은 연결을 정확히 구분하는 데는 한계가 있다.

후보들이 서로 다른 라벨을 주면 ambiguous, 없으면 unmatched다. ARP·TCP/UDP 이외·IP fragment는 라벨 미확정으로 처리한다. 음수/비유한 duration 행은 제외 건수를 기록한다. 완전한 10패킷 모두 BENIGN 또는 모두 DDoS에 매칭된 윈도우만 저장한다. 다른 공격은 매칭 후보에 남겨 충돌을 검출한 뒤 윈도우 단계에서 제외한다. 미매칭이나 다른 공격을 BENIGN으로 채우지 않는다.

원본 라벨 시간 문제 참고: [CICFlowMeter issue #173](https://github.com/ahlashkari/CICFlowMeter/issues/173). 해당 이슈는 사용자의 관찰이며, 시간 변환 정책은 로컬 데이터의 매칭률로 검증해야 한다.

## 실행

프로젝트 루트 PowerShell에서 실행한다. 전체 추출은 수 시간~하루 이상 걸릴 수 있다. 아래 첫 명령은 전체 5개 캡처를 처리하며, 파일별 JSON에 flow 라벨 수, 패킷 매칭/미매칭/충돌 수, 윈도우 제외 사유, 저장 라벨 분포와 시간이 남는다. 새 출력 디렉터리를 사용한다. 기존 출력은 자동 덮어쓰지 않는다.

```powershell
.\.venv\Scripts\python.exe -u src/run_cicids2017_rf.py
```

위 실행기는 금요일부터 전체 5개 파일을 추출한 뒤 라벨/특징 감사를 수행하고 기존 RF를 학습한다. 데이터는 `data/processed/cicids2017_ddos_benign`, 결과는 `results/cicids2017_ddos_benign`이다. 일자별 JSON, 진행률 `*.progress.json`, 단계 `status.json`, 분포 `label_audit.csv`, 최종 `REPORT.md`, 모델과 결과 CSV를 남긴다. 동일 코드·설정으로 완료된 일자는 재실행 시 건너뛰고, 실패한 일자는 처음부터 처리한다.

추출 후 JSON의 일자별·클래스별 분포와 매칭률을 검토한다. 앞부분만 추출한 smoke 결과에는 공격이 없을 수 있으므로 전체 실험에 사용하지 않는다. 두 클래스가 학습·테스트 양쪽에 있어야 학습기가 실행된다. 파일 내 공격 발생 시각에 따라 시간 분할에서 일부 공격이 테스트에만 존재할 수 있다.

```powershell
.\.venv\Scripts\python.exe src/train_rf.py --data data/processed/cicids2017_ddos_benign --tag cicids2017_ddos_benign --time-group source-label --out-dir results/cicids2017_ddos_benign/tables --model-dir results/cicids2017_ddos_benign/models
```

학습기는 디렉터리의 parquet만 읽고 JSON은 제외한다. 결과는 기존과 같은 정확도·precision·recall·F1·macro F1·혼동행렬·추론 비용·모델 크기·특징 중요도다. 원래 캡처 내 row_in_file을 유지하므로 제외된 윈도우 사이의 간격도 시간 분할에 반영된다. 분할 기준은 기존 코드와 동일하게 파일별 마지막 보존 row를 사용한다. flow가 분할 경계를 넘을 수 있어 flow 독립 평가를 의미하지 않는다.

검증 명령:

```powershell
.\.venv\Scripts\python.exe src/test_cicids2017.py
.\.venv\Scripts\python.exe src/prepare_cicids2017.py --max-packets 20000 --out-dir results/cicids2017_smoke_new/data
```

`--only Monday Friday`로 일자를 선택할 수 있다. `--max-packets`는 원본에서 읽은 패킷 수 상한이다. 부분 실행에는 전체 데이터와 다른 디렉터리를 사용한다. 전체 추출·최종 RF 결과는 smoke 검증 결과와 구별한다.

전체 실행에서는 38특징 결과에 사용되지 않는 flow duration/bytes 통계의 반복 계산을 생략한다. 기존 호출의 기본 동작은 유지한다. 실제 5개 캡처에서 각 2,000패킷을 기존/생략 모드로 처리해 모든 CSV 값이 정확히 일치함을 확인했다(`results/cicids2017_ddos_benign/backend_equivalence.json`). 기존 청크 경계와 특징 수식은 같다.

## 혼합 라벨 파일의 분할

기존 CICIoT2023 PCAP는 파일당 라벨 하나여서 파일별 시간순 70/30에서 두 클래스 모두 학습에 들어갔다. CICIDS2017은 금요일 후반에만 DDoS가 있어 날짜 전체를 70/30으로 자르면 학습에 DDoS가 없을 수 있다. 실행기는 원래 분할의 라벨 분포를 `strict_time_label_audit.csv`에 남기고, 한 클래스가 빠지는 경우에만 `--time-group source-label`을 사용한다.

`source-label`은 각 원본 파일·라벨 안에서 보존 윈도우를 row_in_file 시간순으로 정렬해 앞 70%를 학습, 나머지를 테스트로 삼는다. 랜덤 섞기는 하지 않지만, 클래스마다 경계 시각이 달라 하나의 공통 시각 경계에 대한 미래 예측 평가는 아니다. 사용한 설정은 모델 JSON·결과 CSV의 `time_group`과 최종 보고서에 기록한다. 기본 `train_rf.py`의 `--time-group source`는 기존 분할 그대로다.

실행기는 기본 3개 일자를 동시에 추출한다(`--workers`로 변경). 파일별 패킷·청크·윈도우 순서는 유지한다.

## Windows 진행률 파일과 청크 복구

진행률 JSON 교체가 Windows 파일 잠금으로 실패하더라도 특징 추출은 계속하도록 처리했다. 실행 단계 JSON은 잠금이 풀리도록 짧게 재시도한다. 진행률 갱신을 막는 PermissionError를 주입한 테스트에서도 전체 특징 결과가 같음을 확인했다.

`--resume` 또는 실행기의 `--resume-partial`은 footer가 정상인 `.parquet.part`와 진행률 스냅샷의 저장 행 수가 일치하고, 정확히 20,000 accepted packet 경계인 경우에만 이어서 처리한다. PCAPNG 헤더를 읽은 뒤 저장된 raw byte 위치로 이동하고, 보존된 parquet를 복사한 다음 다음 청크부터 이어 쓴다. 합성 데이터에서 중간 복구와 처음부터 추출한 전체 행·특징·라벨·시각이 정확히 일치했다.

이번 화요일 복구는 762,869개 보존 행, accepted packet 7,960,000개, raw byte offset 8,877,229,980에서 시작했다. 증거는 `results/cicids2017_ddos_benign/tuesday_recovery_checkpoint.json`이다. 나머지 4일의 원래 데이터는 재추출하지 않았다. 수식·라벨 정책이 동일하고 진행률/복구 처리만 바뀐 이전 코드 해시를 명시적으로 허용해 재개했다.

```powershell
.\.venv\Scripts\python.exe -u src/run_cicids2017_rf.py --resume-partial --compatible-preparer-sha256 b7d93e5ac37ae8f2a3705a8cc55edfdc6c0bd2551f3d53e317ebd468934a8846
```
