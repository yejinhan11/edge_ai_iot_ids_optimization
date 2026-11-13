# D드라이브 프로젝트 이전 검증

프로젝트: `D:\한예진\dev\edge_ai_iot_ids_optimization`

- 기존 프로젝트 파일 290개, 약 35.08GB: C·D SHA-256 모두 일치.
- CICIDS2017 PCAP 5개: 제공된 MD5 모두 일치. 라벨 ZIP의 전체 항목 CRC 정상.
- 새 `.venv`: Python 3.11, 고정된 25개 패키지 버전 일치, pip 의존성 검사 통과.
- 가공 데이터 20,990,150행 확인. 결과 CSV 99개와 노트북 5개 읽기 통과.
- PCAP/PCAPNG 21개 헤더 및 첫 패킷 읽기 통과. 소규모 RF 학습·예측 통과.
- 복사된 가상환경은 `.venv_before_restore`로 보존했다.

이제 앱에서 D드라이브 프로젝트 폴더를 다시 열고 `.venv\Scripts\python.exe`를 Python 인터프리터로 선택하면 된다.
가상환경 활성화 없이도 프로젝트 루트에서 아래처럼 실행할 수 있다.

```powershell
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"
```

CICIDS2017 파일은 확장자가 `.pcap`이지만 내부 형식은 PCAPNG이다. 새 데이터셋용 추출기 구성 시 PCAPNG 읽기를 지원해야 한다.
기존 RF 전체 재학습을 다시 반복한 검증은 아니며, 복사 무결성과 새 환경의 실행 가능 여부를 확인했다.
