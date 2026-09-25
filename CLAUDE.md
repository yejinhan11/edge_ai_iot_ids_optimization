# CLAUDE.md — 이 저장소에서 작업할 때의 규칙

## 프로젝트
전자공학종합설계. CICIoT2023 PCAP → 공식 39-feature → Random Forest DDoS 탐지.
`전체 / Camera / 특정 기기` subset 간 정확도·F1·추론속도·모델 크기를 비교하고, 이후 feature 선택·경량화로 이어간다.
진행 기록과 계획은 `docs/LOG.md`, 데이터·파이프라인 설명은 `README.md`.

## 작업 규칙
- **git commit / push는 사용자가 직접 한다.** Claude는 변경 파일 목록과 실행할 git 명령만 알려준다.
- 답변과 문서는 한국어. 코드 주석·docstring은 영어.
- 사용자는 Python·네트워크 분석 경험이 많지 않다. 명령은 프로젝트 루트에서 순서대로 실행 가능하게 제시하고, 각 단계가 무엇을 만들고 얼마나 걸리는지 적는다.
- 데이터 해석 시 **확인된 사실(논문·데이터)과 추정을 구분**해서 쓴다.
- `data/`는 git 제외. 대용량 산출물은 `data/`, 표·결과는 `results/tables/`.
- 오래 걸리는 작업(추출·학습)은 파일 단위로 저장하고 사이드카(.json)로 재개 가능하게 한다. 코드가 바뀌면 사이드카의 `code_hash`가 달라져 경고가 뜬다.

## 고정된 설계 결정 (바꾸려면 사용자와 상의)
- feature 추출은 공식 CICIoT2023 pcap2csv 39개 (`tools/pcap2csv_metadata_v2/Feature_extraction_fast.py`, 원본과 출력 동일 검증됨). 최종 RF 입력은 `LLC` 제외 38개.
- 윈도우 = 연속 10패킷, 모든 파일 동일 (논문 CSV의 DDoS 100 / Benign 10 혼용은 사용하지 않음).
- MAC·기기 정보는 metadata 컬럼으로만 쓰고 RF feature에 넣지 않는다 (data leakage 방지).
- 피해 기기 판정: 윈도우 `all_macs`에서 Raspberry Pi 10대(NextGen 전체), 게이트웨이 후보 `3C:18:A0:41:C3:A0`, broadcast/multicast를 제외한 MAC.
  subset: `has_camera`, `has_echo_dot1`(1C:FE:2B:98:16:DD), `has_amcrest`(9C:8E:CD:1D:AB:9F).
- split: 파일별 시간순 70/30 (`time`) 기본, 처음 보는 공격 평가는 `loao`.
- 로컬 PCAP은 각 캡처의 **첫 2 GB 청크만** 보유 (HTTP_Flood, SlowLoris, BenignTraffic3 제외). 모든 결과에 이 사실을 명시한다.

## 단일 진실 소스
- 기기↔MAC: `config/devices.csv` (논문 Table 1 + 게이트웨이 후보). 논문 전체 목록(MAC 없는 기기 포함)은 `config/devices_paper_table1.csv`.
- 실행 순서: `src/extract_features.py` → `src/build_dataset.py` → `src/train_rf.py` → `src/compare_results.py`.
- 환경: `.venv` (Python 3.11), `requirements.txt`.
