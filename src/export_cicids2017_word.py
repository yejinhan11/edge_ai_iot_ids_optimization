"""Build a concise Korean Word report from completed RF results (no training)."""
import csv
import os
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/reports'
OUT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'data/tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE = ROOT / 'results/cicids2017_comparison'
with (BASE / 'summary.csv').open(encoding='utf-8-sig', newline='') as f:
    rows = list(csv.DictReader(f))
lookup = {(r['arm'], r['candidate']): r for r in rows}
plt.rcParams.update({'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
                     'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False})
fig, axes = plt.subplots(1, 2, figsize=(8.2, 2.15), layout='constrained')
for ax, arm, candidates, title in [
    (axes[0], 'legacy_windows', ['baseline', 'validation_selected', 'C1'], '기존 10패킷 방식'),
    (axes[1], 'native_flows', ['baseline', 'validation_selected', 'validation_lightweight'], '공식 flow 방식')]:
    data = [lookup[arm, c] for c in candidates]
    vals = [float(r['infer_us']) for r in data]
    ax.barh(range(3), vals, color=['#9baabc', '#3b78a5', '#15958b'], height=.53)
    ax.set_yticks(range(3), ['기준선', '검증 선택', '경량 후보'])
    ax.invert_yaxis()
    ax.set_xlim(0, 6.5)
    ax.set_xticks([0, 2, 4, 6])
    ax.set_xlabel('RF 추론 시간 (µs/표본, 작을수록 빠름)', fontsize=8)
    ax.set_title(title, fontweight='bold', fontsize=10)
    ax.xaxis.grid(True, alpha=.16)
    ax.set_axisbelow(True)
    for i, (r, v) in enumerate(zip(data, vals)):
        ax.text(v+.1, i, f"{v:.3f}\nF1m {float(r['f1_macro_mean']):.6f}",
                va='center', fontsize=7.5)
chart = OUT / 'cicids2017_rf_summary.png'
fig.savefig(chart, dpi=220, facecolor='white')
plt.close(fig)

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
def run(text, bold=False, size=None, color=None):
    props = '<w:b/>' if bold else ''
    if size: props += f'<w:sz w:val="{size}"/>'
    if color: props += f'<w:color w:val="{color}"/>'
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(str(text))}</w:t></w:r>'
def para(text='', style=None, bold=False, size=None, color=None):
    prop = f'<w:pStyle w:val="{style}"/>' if style else ''
    return f'<w:p><w:pPr>{prop}</w:pPr>{run(text,bold,size,color)}</w:p>'
def table(headers, data, widths):
    grid = ''.join(f'<w:gridCol w:w="{v}"/>' for v in widths)
    result = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/>'
              '<w:tblBorders><w:bottom w:val="single" w:sz="4" w:color="CBD5E1"/>'
              '<w:insideH w:val="single" w:sz="4" w:color="E2E8F0"/></w:tblBorders>'
              '<w:tblCellMar><w:top w:w="65" w:type="dxa"/><w:bottom w:w="65" w:type="dxa"/>'
              '<w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>'
              f'</w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
    for i, row in enumerate([headers]+data):
        result.append('<w:tr><w:trPr><w:cantSplit/>'+('<w:tblHeader/>' if i==0 else '')+'</w:trPr>')
        for j, value in enumerate(row):
            fill = '16324F' if i == 0 else ('F1F5F9' if i%2 else 'FFFFFF')
            result.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[j]}" w:type="dxa"/>'
                          f'<w:shd w:fill="{fill}"/><w:vAlign w:val="center"/></w:tcPr>'
                          '<w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/>'
                          '<w:jc w:val="'+('left' if j==0 else 'center')+'"/></w:pPr>'
                          +run(value, i==0, 17, 'FFFFFF' if i==0 else '243447')+'</w:p></w:tc>')
        result.append('</w:tr>')
    return ''.join(result)+'</w:tbl>'

parts = [para('CICIDS2017 RF 실험 결과', 'Title'),
         para('정상·DDoS 이진분류 | 기존 10패킷 방식과 공식 flow 방식 비교', 'Subtitle'),
         para('1. 실험 목적과 데이터', 'Heading1'),
         para('기존 CICIoT2023의 38특징·10패킷 방식을 CICIDS2017에 적용한 결과와, CICIDS2017 공식 flow 특징으로 학습한 결과를 비교했다. 두 방식의 성능과 RF 경량화 가능성을 확인하며, 기기별 학습·평가는 제외했다.'),
         para('정상(BENIGN=0)과 DDoS(1)만 사용했다. DoS·PortScan·Bot 등 다른 공격을 DDoS로 합치지 않았다. 아래 결과는 모두 CICIDS2017 데이터로 학습·평가한 값이다.'),
         table(['구분', '기존 10패킷 방식', '공식 flow 방식'], [
             ['입력·특징', 'PCAPNG / 비중첩 10패킷\n38개 특징 및 부분집합', '공식 CICFlowMeter CSV / flow\n수치 후보 77개 → 상수 제외 67개'],
             ['정제 기준', '10패킷 모두 같은 정상/DDoS 라벨\n누락·모호·혼합·다른 공격 제외', '식별자·IP·port·시각 입력 제외\n잘못된 duration·특징 중복·충돌 제외'],
             ['최종 데이터', '5,065,637개 윈도우\n정상 5,032,072 / DDoS 33,565', '1,991,221개 flow\n정상 1,863,208 / DDoS 128,013'],
         ], [1700, 3280, 3280]),
         para('2. 데이터 분할과 학습 방법', 'Heading1'),
         para('금요일 후반에 DDoS가 몰려 있어 파일 전체를 앞 70%·뒤 30%로 나누면 학습 DDoS가 0개였다. 기존 방식은 파일·라벨별 시간순 70/30으로 조정했다. flow 방식은 같은 날짜의 양방향 5-tuple(통신 양끝의 IP·port와 프로토콜) 전체를 한 그룹으로 묶어 분할 간 연결 중복을 줄였다.'),
         para('두 방식 모두 바깥 학습 풀 약 70%의 앞 80%를 fit, 나머지를 검증에 사용했다(전체 기준 약 56/14/30). 다음은 사용 가능한 풀의 개수이며, 정상 / DDoS 순서다.', size=18),
         table(['방식', 'fit', '검증', '테스트'], [
             ['기존 10패킷', '2,817,964 / 18,797', '704,488 / 4,699', '1,509,620 / 10,069'],
             ['공식 flow', '1,044,682 / 70,418', '261,190 / 17,572', '557,336 / 40,023'],
         ], [1500, 2250, 2250, 2260]),
         para('특징·설정 선택은 fit/검증에서만 수행했다. flow 1차 탐색은 최대 30만 행, 상위 후보 재검증과 최종 학습은 최대 100만 행을 사용했다. 최종 모델은 설정을 고정한 뒤 바깥 학습 풀에서 다시 학습하고 테스트 전체를 평가했다. 결측 중앙값과 상수 특징도 학습 구간에서만 결정했다.', size=18),
         para('3. RF 탐색 범위와 선택 이유', 'Heading1'),
         para('기존 방식은 특징 5/10/15/20/38개, 트리 10/20/50/100개를 포함한 33개 설정을 탐색했다. flow 방식은 특징 5/10/15/20/30/전체, 트리 20/50/100/200개를 포함한 43개 설정을 탐색했다. 두 방식 모두 깊이 8/12/16/무제한과 최소 리프 표본 1/10/100의 지정 조합을 확인했으며, 전체 조합 탐색은 아니다.'),
         para('불균형 데이터에서 정상과 공격을 함께 평가하기 위해 macro F1을 우선했다. 검증 최고 모델과 별도로, 검증 macro F1 손실 0.001 이내에서 작은 flow 경량 모델을 선택했다. 검증 선택 모델은 seed 42/43/44로 반복했고, 나머지 모델은 seed 42로 평가했다.', size=18),
         '<w:p><w:r><w:br w:type="page"/></w:r></w:p>',
         para('4. 주요 결과', 'Heading1'),
         para('F1m은 정상·DDoS F1의 평균이다. 정밀도와 재현율은 DDoS 기준이며, 검증 선택 모델은 seed 3회 평균이다. 모델 크기는 비압축 추정치다.', size=18)]
labels = {'baseline':'기준선', 'validation_selected':'검증 선택', 'validation_lightweight':'경량',
          'C1':'C1', 'C2':'C2', 'C3':'C3', 'C4':'C4'}
data=[]
for arm in ['legacy_windows','native_flows']:
    for r in rows:
        if r['arm'] != arm: continue
        data.append([('10패킷 ' if arm=='legacy_windows' else 'flow ')+labels[r['candidate']],
                     f"{r['features']}/{r['trees']}", f"{float(r['f1_macro_mean']):.6f}",
                     f"{float(r['precision_mean']):.6f}", f"{float(r['recall_mean']):.6f}",
                     f"{float(r['model_mb']):.2f}", f"{float(r['infer_us']):.3f}"])
parts += [table(['방식·모델','특징/트리','F1m','정밀도','재현율','MB','µs/표본'],data,[1800,1000,1150,1150,1150,850,1160]),
          para('C1=38특징·20트리, C2=38·10, C3=15·20, C4=38·20·깊이16. 그 외 최종 모델은 깊이 무제한이며 최소 리프 표본은 모두 1이다. C1–C4는 기존 방식의 추가 경량 후보다.', size=17)]
parts += ['''<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>
<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0">
<wp:extent cx="5290000" cy="1387000"/><wp:docPr id="1" name="RF 추론 시간과 macro F1"/>
<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="0" name="summary.png"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="5290000" cy="1387000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>''',
          para('그림 1. 각 방식 내부의 RF 추론 비용 비교. 기존 방식의 경량 후보는 C1이다.', size=17, color='526477'),
          para('5. 결과 해석', 'Heading1'),
          para('공식 flow 경량 모델(20특징·20트리)은 기준선보다 RF 추론이 약 6.3배 빠르며, macro F1 감소는 약 0.000087(0.0087%p)이다. 이번 조건에서는 성능을 거의 유지하면서 RF 비용을 줄인 후보로 볼 수 있다. 기존 방식도 38특징·50트리로 줄이면 macro F1을 거의 유지하며 추론이 약 1.9배 빨라졌다.'),
          para('검증 최고인 flow 10특징·100트리 모델은 테스트에서 67특징 기준선보다 macro F1이 낮았다. 검증 순위가 테스트 순위를 보장하지 않으며, 테스트 점수를 보고 선택을 바꾸지 않았다. 따라서 “가능한 최선”이 아니라 이번 탐색·분할 조건에서 확인한 결과로 해석한다.'),
          para('6. 평가 범위와 한계', 'Heading1'),
          para('두 방식은 표본 단위·라벨 품질·정제·분할이 다르므로, flow의 높은 점수가 특징 변경만의 효과라고 볼 수 없다. 기존 방식의 패킷 라벨은 flow 시각·연결 매칭에 근거하며, 두 분할 모두 하나의 공통 시각으로 분리한 엄격한 미래 예측 평가는 아니다. 기존 방식은 이전에 확인한 테스트 구간을 재사용했다.'),
          para('추론 시간은 RF.predict만 측정해 패킷 수집·특징 추출·flow 종료 대기와 실제 edge 장치 지연은 포함하지 않는다. 현재 DDoS 라벨은 한 종류이므로 공격 한 종류를 빼고 학습하는 LOAO는 적용할 수 없다. 기기별 실험은 현재 연구 범위에서 제외했다.'),
          para('자료 기준: UNB/CIC의 CICIDS2017 공식 데이터 및 완료된 RF 실험 집계. 새 학습 없이 기존 결과를 정리함.', size=16, color='526477')]

styles = f'''<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Malgun Gothic" w:hAnsi="Malgun Gothic" w:eastAsia="맑은 고딕"/><w:sz w:val="18"/><w:color w:val="243447"/><w:lang w:val="ko-KR" w:eastAsia="ko-KR"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="70" w:line="250" w:lineRule="auto"/><w:widowControl/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:spacing w:after="100"/><w:keepNext/></w:pPr><w:rPr><w:b/><w:sz w:val="34"/><w:color w:val="16324F"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:pPr><w:spacing w:after="180"/><w:keepNext/></w:pPr><w:rPr><w:sz w:val="19"/><w:color w:val="526477"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:keepNext/><w:spacing w:before="150" w:after="75"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="23"/><w:color w:val="16324F"/></w:rPr></w:style></w:styles>'''
footer=f'<w:ftr xmlns:w="{W}"><w:p><w:pPr><w:jc w:val="center"/></w:pPr>{run("CICIDS2017 · RF 실험 요약  |  ",size=16,color="526477")}<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>'
sect='<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="720" w:right="1000" w:bottom="720" w:left="1000" w:header="350" w:footer="350"/></w:sectPr>'
document=f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>'+''.join(parts)+sect+'</w:body></w:document>'
relbase='http://schemas.openxmlformats.org/package/2006/relationships'
content='''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>'''
rels=f'<Relationships xmlns="{relbase}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/></Relationships>'
docrels=f'<Relationships xmlns="{relbase}"><Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/><Relationship Id="rIdImage" Type="{R}/image" Target="media/summary.png"/><Relationship Id="rIdFooter" Type="{R}/footer" Target="footer1.xml"/></Relationships>'
output=OUT/'CICIDS2017_RF_실험결과_요약.docx'
with ZipFile(output,'w',ZIP_DEFLATED) as z:
    for name,value in {'[Content_Types].xml':content, '_rels/.rels':rels, 'word/document.xml':document,
                       'word/styles.xml':styles,'word/footer1.xml':footer,'word/_rels/document.xml.rels':docrels}.items():
        z.writestr(name,'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'+value)
    z.write(chart,'word/media/summary.png')
from xml.etree import ElementTree as ET
with ZipFile(output) as z:
    for name in z.namelist():
        if name.endswith(('.xml','.rels')): ET.fromstring(z.read(name))
    assert b'TargetMode="External"' not in z.read('word/_rels/document.xml.rels')
print(output)
print('Validated XML parts; tables and chart embedded; no external links.')
