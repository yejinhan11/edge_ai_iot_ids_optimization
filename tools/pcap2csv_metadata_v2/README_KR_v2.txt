CICIoT2023 pcap2csv metadata v2

수정 사항
1) 최신 Colab/Scapy에서 scapy 이름 및 layer import 문제 방지
2) Scapy Bluetooth/Zigbee 검사 실패가 Ethernet DDoS 추출을 중단하지 않도록 보호
3) 첫 검증 기본 workers=1
4) 빈 split CSV 안전 처리
5) 내부 오류 traceback을 그대로 출력

RF 입력에는 기존 39개 feature만 사용하고,
추가 MAC 관련 열은 subset 선택용 metadata로만 사용합니다.
