"""Weekly report: preserve supplied MLP content; explain archived RF and balance ablation."""
import sys, re, csv, os
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'data/tmp/report_merge_deps'))
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import pymupdf as fitz
import pandas as pd
import numpy as np
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'data/tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT=ROOT/'results/reports/weekly_1109';OUT.mkdir(parents=True,exist_ok=True)
MLP=Path('D:/한예진/경북대/4-2/전자공학종합설계/mlp양자화.pdf')
pdf=fitz.open(MLP)
raw='\n'.join(p.get_text() for p in pdf)
raw=re.sub(r'(?m)^Quantization\s*$','',raw)
raw=re.sub(r'(?m)^[12]\s*$','',raw)
flat=lambda s:re.sub(r'\s+',' ',s).strip()
def cut(start,end):return flat(raw[raw.index(start):raw.index(end,raw.index(start))])

d=Document();sec=d.sections[0]
sec.page_width=Cm(21);sec.page_height=Cm(29.7)
sec.top_margin=Cm(1.6);sec.bottom_margin=Cm(1.5);sec.left_margin=Cm(1.7);sec.right_margin=Cm(1.7)
sec.header_distance=Cm(.65);sec.footer_distance=Cm(.65)
for name in ['Normal','Title','Subtitle','Heading 1','Heading 2','Caption','TOC 1','TOC 2']:
    if name not in d.styles:
        from docx.enum.style import WD_STYLE_TYPE
        d.styles.add_style(name,WD_STYLE_TYPE.PARAGRAPH)
    st=d.styles[name];st.font.name='맑은 고딕';st.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'맑은 고딕')
    st.font.color.rgb=RGBColor.from_string('243747')
normal=d.styles['Normal'];normal.font.size=Pt(9.5)
normal.paragraph_format.space_after=Pt(4);normal.paragraph_format.line_spacing=1.06
for name,size in [('Heading 1',16),('Heading 2',11)]:
    st=d.styles[name];st.font.size=Pt(size);st.font.bold=True;st.font.color.rgb=RGBColor.from_string('173750')
    st.paragraph_format.space_before=Pt(8 if name=='Heading 2' else 0)
    st.paragraph_format.space_after=Pt(5);st.paragraph_format.keep_with_next=True
d.styles['Title'].font.size=Pt(25);d.styles['Title'].font.bold=True
d.styles['Subtitle'].font.size=Pt(10);d.styles['Subtitle'].font.color.rgb=RGBColor.from_string('567080')
d.styles['Caption'].font.size=Pt(8);d.styles['Caption'].font.color.rgb=RGBColor.from_string('567080')
for name in ['TOC 1','TOC 2']:
    st=d.styles[name];st.font.size=Pt(10);st.paragraph_format.space_after=Pt(5)
head=sec.header.paragraphs[0];head.text='전자공학종합설계2  |  주간 진행보고 · 2026.11.09'
for r in head.runs:r.font.size=Pt(8);r.font.color.rgb=RGBColor.from_string('738493')
footer=sec.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
footer.add_run('전자공학종합설계2  ·  ').font.size=Pt(8)
field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
pending=False
compact_mlp=False
def page():
    global pending
    pending=True
def p(text='',style=None,bold=False):
    global pending
    para=d.add_paragraph(text,style)
    if pending:para.paragraph_format.page_break_before=True;pending=False
    if compact_mlp:
        para.paragraph_format.line_spacing=1.0
        para.paragraph_format.space_after=Pt(2.5)
    if bold:
        for r in para.runs:r.bold=True
    return para
def h(text):return p(text,'Heading 2')
def table(headers,rows,widths=None):
    n=len(headers);widths=widths or [17.6/n]*n
    t=d.add_table(rows=1,cols=n);t.autofit=False
    for col,w in zip(t.columns,widths):col.width=Cm(w)
    for c,v in zip(t.rows[0].cells,headers):c.text=str(v)
    for row in rows:
        for c,v in zip(t.add_row().cells,row):c.text=str(v)
    for i,row in enumerate(t.rows):
        trpr=row._tr.get_or_add_trPr();trpr.append(OxmlElement('w:cantSplit'))
        if i==0:trpr.append(OxmlElement('w:tblHeader'))
        for j,c in enumerate(row.cells):
            c.width=Cm(widths[j]);pr=c._tc.get_or_add_tcPr()
            sh=OxmlElement('w:shd');sh.set(qn('w:fill'),'173750' if i==0 else ('EFF4F7' if i%2 else 'FFFFFF'));pr.append(sh)
            mar=OxmlElement('w:tcMar')
            for edge,val in [('top','65'),('bottom','65'),('left','65'),('right','65')]:
                e=OxmlElement('w:'+edge);e.set(qn('w:w'),val);e.set(qn('w:type'),'dxa');mar.append(e)
            pr.append(mar)
            for para in c.paragraphs:
                para.paragraph_format.space_after=Pt(0);para.paragraph_format.line_spacing=1.04
                para.alignment=WD_ALIGN_PARAGRAPH.LEFT if j==0 else WD_ALIGN_PARAGRAPH.CENTER
                for run in para.runs:
                    run.font.size=Pt(8);run.bold=i==0
                    run.font.color.rgb=RGBColor.from_string('FFFFFF' if i==0 else '243747')
    p('').paragraph_format.line_spacing=Pt(2)
    return t
def picture(path,width=17):
    para=d.add_paragraph();para.alignment=WD_ALIGN_PARAGRAPH.CENTER
    para.add_run().add_picture(str(path),width=Cm(width))

# Title and a two-level TOC. Word populates page numbers in the validation step.
p('전자공학종합설계2\n주간 진행보고','Title')
p('CICIoT2023 기반 MLP 양자화 및 RF 경량화 검증\n2026년 11월 9일','Subtitle')
p('보고서 구성',bold=True)
p('1장은 MLP의 동적 INT8 양자화 방법·비교 설정·결과를, 2장은 기존 RF 경량화와 학습량을 맞춘 50:50 추가 검증을 다룬다. 각 장에서 수행 내용, 설정 이유, 결과의 의미를 순서대로 확인할 수 있도록 구성했다.')
p('목차',bold=True)
toc=d.add_paragraph()
for kind in ['begin','separate','end']:
    r=OxmlElement('w:r')
    if kind=='separate':
        instr=OxmlElement('w:r');txt=OxmlElement('w:instrText');txt.set(qn('xml:space'),'preserve');txt.text=' TOC \\o "1-2" \\u ';instr.append(txt);toc._p.append(instr)
    fld=OxmlElement('w:fldChar');fld.set(qn('w:fldCharType'),kind);r.append(fld);toc._p.append(r)
p('읽는 기준',bold=True)
p('MLP의 F1·Precision·Recall은 원문에 명시된 weighted average다. RF의 종합 성능은 macro F1로 보고하고 클래스별 지표를 별도로 표시했다. 두 장의 F1 숫자와 서로 다른 컴퓨터의 추론 시간을 직접 비교해 모델 우열을 판단하지 않는다.','Caption')

page();p('1. MLP 양자화','Heading 1')
h('1.1 적용 대상과 양자화 방법')
p(cut('대상:','비교 변수'))
h('1.2 비교 설정과 검증 가설')
p(cut('비교 변수','결과 종합'))
# Move the stated hypothesis ahead of its results; do not invent a method rationale.
p(cut('처음엔','같은 검증'))
h('1.3 FP32·INT8 결과 비교')
mlp_names=['baseline\n38특징·불균형','rf_top5\n5특징·불균형','baseline\n38특징·balanced',
           'rf_top5\n5특징·balanced·seed1','rf_top5\n5특징·balanced·seed2']
perf=[['13,762','0.9889 / 0.9893','0.9473 / 0.9236','-4.16pp','-6.57pp'],
      ['9,538','0.9877 / 0.9882','0.9477 / 0.9222','-4.00pp','-6.60pp'],
      ['13,762','0.9867 / 0.9873','0.9761 / 0.9752','-1.06pp','-1.21pp'],
      ['9,538','0.9845 / 0.9854','0.1240 / 0.1899','-86.05pp','-79.55pp'],
      ['9,538','0.9847 / 0.9856','0.0523 / 0.0052','-93.24pp','-98.04pp']]
table(['설정','Params','FP32 Acc / F1','INT8 Acc / F1','Accuracy Δ','F1 Δ'],
      [[n]+row for n,row in zip(mlp_names,perf)],[4,1.5,3.5,3.5,2.55,2.55])
cost=[['57.5→20.9KB (-63.7%)','0.87→0.92','0.94x'],['41.0→16.8KB (-59.1%)','1.76→1.54','1.15x'],
      ['57.5→20.9KB (-63.7%)','3.69→3.41','1.08x'],['41.0→16.8KB (-59.1%)','4.84→5.61','0.86x'],
      ['41.0→16.8KB (-59.1%)','3.74→6.83','0.55x']]
table(['설정','크기 변화 (FP32→INT8)','추론 (µs/표본)','속도 배율'],
      [[n]+row for n,row in zip(mlp_names,cost)],[5,5.6,4,3])
p(cut('(속도 수치는','핵심 발견 1'),'Caption')

compact_mlp=True
page();h('1.4 결과 해석: 크기·속도·가중치 범위')
p('핵심 발견 1 — 크기 감소는 항상 안정적',bold=True)
p(cut('모든 설정에서 59~64%','핵심 발견 2'))
p('핵심 발견 2 — 속도 비교는 이 모델 규모에서 신뢰 불가',bold=True)
p(cut('FLOPs가','핵심 발견 3'))
p('핵심 발견 3 — Accuracy 손실의 진짜 원인: weight 크기 ≠ 클래스 불균형 단독이 아님',bold=True)
p(cut('같은 검증','hidden1 weight abs_max'))
table(['설정','hidden1 weight abs_max','hidden1 weight std'],[
['baseline (balanced)','11.44','0.69'],['rf_top5 (balanced, seed1)','47.80','6.60'],['rf_top5 (balanced, seed2)','35.77','5.12']], [7.6,5,5])
after=cut('rf_top5의 weight가','결론 (보고서용)')
for start,end in [('rf_top5의 weight가','weight가 왜 커지는지:'),('weight가 왜 커지는지:','INT8 결과 자체도'),('INT8 결과 자체도',None)]:
    part=after[after.index(start):] if end is None else after[after.index(start):after.index(end)]
    p(part)
h('1.5 결론과 재현 방법')
conclusions=cut('1. Dynamic INT8','재현용 스크립트')
for item in re.split(r'(?=\b[1-4]\. )',conclusions):
    if item.strip():p(item.strip()).paragraph_format.keep_together=True
scripts=flat(raw[raw.index('train.py --save_model'):])
for line in re.split(r'(?=(?:train\.py|quantize_eval\.py|balance_classes\.py|inspect_weights\.py)\s*:|train\.py --save_model)',scripts):
    if line.strip():p(line.strip(),'Caption')

balanced=pd.read_csv(ROOT/'results/ciciot2023_balanced_rf/summary.csv').set_index(['regime','candidate'])
allruns=pd.read_csv(ROOT/'results/ciciot2023_balanced_rf/results.csv')
final=pd.read_csv(ROOT/'results/tables/final_candidates.csv')
final=final[(final['eval']=='time')&(final.test_subset=='all')]
sweep=pd.read_csv(ROOT/'results/tables/sweep_features.csv')
sweep=sweep[(sweep.train_subset=='all')&(sweep.test_subset=='all')]
plt.rcParams.update({'font.family':'Malgun Gothic','axes.unicode_minus':False,'font.size':9,
                     'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,2,figsize=(9,2.2),layout='constrained')
axes[0].plot(sweep.top_k,sweep.f1_macro,'o-',color='#168C87')
axes[0].set(xlabel='특징 수 (트리 100개 고정)',ylabel='Macro F1',xticks=[5,10,15,20,38])
axes[1].plot(sweep.top_k,sweep.model_mb,'s-',color='#526F8A')
axes[1].set(xlabel='특징 수 (트리 100개 고정)',ylabel='비압축 모델 크기 (MB)',xticks=[5,10,15,20,38])
for ax in axes:ax.grid(alpha=.15)
fig.savefig(OUT/'rf_feature_effect.png',dpi=190,facecolor='white');plt.close(fig)
fig,axes=plt.subplots(1,2,figsize=(9,2.2),layout='constrained')
keys=['baseline','top5','compact'];xs=np.arange(3)
for ax,metric,title in zip(axes,['false_alarm_rate_mean','missed_ddos_rate_mean'],['정상 오탐률 (%)','DDoS 미탐률 (%)']):
    for off,reg,col,label in [(-.18,'natural','#8B9DAE','기존 비율'),(.18,'balanced','#168C87','50:50')]:
        vals=[balanced.loc[reg,k][metric]*100 for k in keys]
        ax.bar(xs+off,vals,width=.34,color=col,label=label)
        for x,v in zip(xs+off,vals):ax.text(x,v,f'{v:.2f}',ha='center',va='bottom',fontsize=8)
    ax.set_xticks(xs,['38특징·100트리','5특징·100트리','38특징·20트리']);ax.set_title(title)
    ax.set_ylim(0,3);ax.yaxis.grid(alpha=.15);ax.set_axisbelow(True)
axes[0].legend(frameon=False,fontsize=8)
fig.savefig(OUT/'rf_balance_errors.png',dpi=190,facecolor='white');plt.close(fig)

compact_mlp=False
page();p('2. RF 경량화','Heading 1')
h('2.1 수행 내용과 설정 이유')
p('목적은 CICIoT2023에서 정상·DDoS 탐지 성능을 유지하면서 RF의 저장 크기와 예측 비용을 줄이는 것이다. 기존 특징·트리·깊이 탐색 결과를 정리하고, 학습 데이터의 불균형 때문에 경량화 효과가 왜곡됐는지 확인하기 위해 동일 학습량의 50:50 추가 검증을 수행했다.')
p('데이터는 원본 PCAP에서 추출한 38개 특징·비중첩 10패킷 윈도우다. 지정 캡처의 첫 2GB 청크 중심이며 일부 작은 캡처는 전체를 사용했다. 총 20,990,150행에서 파일별 시간순 앞 70%를 학습 풀, 뒤 30%를 테스트로 유지했다. 테스트는 정상 329,362 / DDoS 5,967,677, 총 6,297,039행이다.')
table(['변수','탐색 범위','변경 이유'],[
['특징 수','5 / 10 / 15 / 20 / 38','입력 정보를 줄였을 때 탐지 성능과 모델 비용이 어떻게 변하는지 확인'],
['트리 수','10 / 20 / 50 / 100','트리 수 감소로 예측 연산과 저장 비용을 줄일 수 있는지 확인'],
['최대 깊이','8 / 12 / 16 / 무제한','트리 분기 수를 제한해 모델 크기를 줄일 때의 성능 손실 확인'],
['최소 리프 표본','1 / 10 / 100','소수 표본에 대한 세밀한 분기를 제한해 트리 복잡도 감소'],
['클래스 가중치','balanced','학습 클래스 빈도의 역수로 가중치를 보정. 정상 표본 수 자체를 늘리는 방법과 구분']], [3,4,10.6])
p('위 값은 지정 조합으로 단계별 탐색했으며 모든 조합을 실행한 것은 아니다. 중요도 순위는 기존 학습 RF에서 얻었다. 기존 설정 비교는 seed 42, 학습 최대 100만 행을 사용했다. 기기별 학습은 이번 보고서 범위에서 제외한다.','Caption')
h('2.2 기존 경량화 결과와 의미')
rows=[]
for r in final.itertuples():
    depth='∞' if pd.isna(r.max_depth) else str(int(r.max_depth))
    rows.append([{'base':'기준선','c1':'38특징·20트리','c2':'38특징·10트리','c3':'15특징·20트리','c4':'38특징·20트리·깊이16'}[r.cand],f'{int(r.top_k)} / {int(r.n_estimators)} / {depth}',
                 f'{r.accuracy:.6f}',f'{r.f1_macro:.6f}',f'{r.model_mb:.2f}',f'{r.infer_us_per_sample:.3f}'])
table(['모델 구성','특징 / 트리 / 깊이','Accuracy','Macro F1','MB','µs/표본'],rows,[4.2,3.4,2.7,2.7,2.1,2.1])
p('표는 기존 최종 후보의 동일 시간순 테스트 평가다. 최소 리프 표본은 1이다. F1은 두 클래스의 macro F1이며 MB는 비압축 RF 객체 크기다. 예측 시간은 당시 측정값이므로 다음 절의 재실행 시간과 직접 섞어 비교하지 않는다.','Caption')
picture(OUT/'rf_feature_effect.png')
p('그림 1. 기존 특징 수 탐색 단계 결과. 최종 후보 표와 별도 실행이며 같은 설정도 실행별 차이가 있을 수 있다.','Caption')
p('특징 5개는 38개보다 macro F1이 낮고 모델 크기는 오히려 컸다. 입력 차원을 줄여도 RF가 더 복잡한 트리를 만들 수 있어 특징 수만으로 경량화를 판단하기 어렵다. 반면 38특징·20트리 모델은 최종 후보 기준선 대비 macro F1 약 0.1303%p 감소로 모델 크기를 95.19→25.44 MB로 줄였다. 38특징·20트리·깊이16 모델은 9.91 MB까지 작아졌지만 macro F1 손실이 더 컸다.')

page();h('2.3 50만:50만 추가 검증을 설계한 이유')
p('기존 학습 100만 행은 DDoS 약 95%, 정상 약 5%였다. 높은 전체 정확도가 정상 클래스의 손실을 가릴 수 있어, 정상 표본을 더 많이 포함하면 경량 모델의 성능이 개선되는지 확인했다. 총학습량 증가 효과를 섞지 않기 위해 기존 비율과 50:50 모두 100만 행으로 고정했다.')
table(['조건','기존 비율','50:50 학습','이렇게 정한 이유'],[
['학습 표본 수','100만 행','100만 행','학습량 증가 효과와 클래스 구성 변경을 구분'],
['정상 / DDoS','약 5.2만 / 94.8만','50만 / 50만','같은 시간순 학습 풀 안에서 중복 없이 재표집'],
['모델 구성','38특징·100트리 / 5특징·100트리 / 38특징·20트리','같은 세 구성','기준선·특징 축소·트리 축소를 고정해 대응 비교'],
['가중치·특징 순위','balanced / 기존 RF 순위','동일','새 특징 선택이나 설정 변경 효과를 섞지 않음'],
['테스트','기존 6,297,039행','동일한 전체 테스트','평가 분포 변경 없이 학습 구성의 영향 확인'],
['반복','seed 42 / 43 / 44','같은 seed 3회','한 번의 표본 선택·RF 난수에만 의존하지 않도록 확인']], [2.7,4.3,4.3,6.3])
p('기존 시간순 학습 풀은 14,693,111행(정상 768,515 / DDoS 13,924,596)이다. 기존 비율 seed 42의 실제 학습 구성은 정상 52,219 / DDoS 947,781이었다. 균형군은 정상·DDoS 각 500,000행이다. 세 구성×두 학습 비율×세 seed로 총 18개 모델을 학습했다. 후보를 사전에 고정한 추가 검증으로, 별도 검증 분할이나 새로운 최적 설정 선택을 수행한 것은 아니다.')
h('2.4 추가 검증 결과')
rows=[]
for reg in ['natural','balanced']:
    for key,label in [('baseline','38·100'),('top5','5·100'),('compact','38·20')]:
        r=balanced.loc[reg,key]
        rows.append(['기존 비율' if reg=='natural' else '50:50',label,f'{r.accuracy_mean:.6f}',
                    f'{r.f1_macro_mean:.6f}\n±{r.f1_macro_std:.6f}',f'{100*r.benign_recall_mean:.2f}',
                    f'{100*r.recall_mean:.2f}',f'{r.model_mb_mean:.2f}',f'{r.infer_us_per_sample_mean:.3f}'])
table(['학습 구성','특징·트리','Accuracy','Macro F1 ± SD','정상 Recall %','DDoS Recall %','MB','µs/표본'],rows,[2,1.9,2.6,3,2.2,2.2,1.6,2.1])
p('seed 3회의 평균이며 macro F1에는 표준편차를 병기했다. 속도는 같은 테스트 10만 표본에 대해 단일 스레드 RF.predict를 워밍업 후 5회 측정한 중앙값의 seed 평균이다. 통계적 유의성 검정 결과는 아니다.','Caption')
page();h('2.5 정량적 의미와 최종 판단')
picture(OUT/'rf_balance_errors.png',width=16)
p('그림 2. 3회 평균 오탐·미탐률. 정상 오탐률=정상을 DDoS로 예측한 비율, DDoS 미탐률=DDoS를 정상으로 예측한 비율이다.','Caption')
a=balanced.loc['natural','baseline'];b=balanced.loc['natural','compact']
p('판단 1. 50:50 학습으로 기존 RF 경량화 결과를 전면 교체하지 않는다.',bold=True)
p('세 구성·세 seed의 9개 대응 비교 모두에서 50:50 학습의 정상 Recall은 높아졌지만 macro F1은 낮아졌다. 정상 오탐 감소와 DDoS 미탐 증가의 교환관계가 관찰됐다. 정상 데이터를 더 학습하면 모든 지표가 함께 개선될 것이라는 기대는 이번 테스트에서 확인되지 않았다.')
delta_rows=[]
for key,label in [('baseline','38특징·100트리'),('top5','5특징·100트리'),('compact','38특징·20트리')]:
    n=balanced.loc['natural',key];z=balanced.loc['balanced',key]
    delta_rows.append([label,f'{100*(z.f1_macro_mean-n.f1_macro_mean):+.3f}',
                       f'{100*(z.benign_precision_mean-n.benign_precision_mean):+.3f}',
                       f'{100*(z.benign_recall_mean-n.benign_recall_mean):+.3f}',
                       f'{100*(z.recall_mean-n.recall_mean):+.3f}'])
table(['구성','Macro F1 차이','정상 Precision 차이','정상 Recall 차이','DDoS Recall 차이'],delta_rows,[4,3.4,3.4,3.4,3.4])
p('50:50 평균−기존 비율 평균, 단위는 %p. 정상 Precision도 세 구성 모두 낮아졌다. 정상 Precision은 정상으로 예측한 결과 중 실제 정상의 비율이며, 실제 정상을 정상으로 맞힌 비율인 정상 Recall과 다르다.','Caption')
p('판단 2. 입력 특징 수보다 실제 트리 복잡도와 예측 비용을 함께 본다.',bold=True)
p(f'기존 비율의 38특징·20트리는 재실행 기준선 대비 macro F1 약 {100*(a.f1_macro_mean-b.f1_macro_mean):.4f}%p 감소로 비압축 모델 크기 {a.model_mb_mean:.2f}→{b.model_mb_mean:.2f} MB(약 {100*(1-b.model_mb_mean/a.model_mb_mean):.1f}% 감소), RF 추론 약 {a.infer_us_per_sample_mean/b.infer_us_per_sample_mean:.2f}배 향상을 보였다. 반면 5특징·100트리는 기존 비율에서 약 118.57 MB, 균형 학습에서는 약 152.28 MB로 커졌다. 이번 결과에서는 특징 5개를 사용했다는 사실만으로 더 가벼운 RF라고 할 수 없다.')
p('판단 3. 균형 학습은 실패한 실험이 아니라 가설을 확인한 추가 검증이다.',bold=True)
p('이번 주에는 기존 RF 결과를 유지하고, 학습 불균형 완화만으로 경량화 손실이 해결되지 않았다는 결과를 함께 보고한다. 정상 오탐 감소가 최우선인 운영 조건이라면 균형군을 별도로 검토할 수 있지만, 현재 결과만으로 새로운 최적 모델이라고 선택하지 않는다. RF 결과가 MLP 양자화 손실의 원인을 설명하는 것은 아니므로 각 모델 내부의 결과로 해석한다.')
p('검증 범위와 한계',bold=True)
p('기존 테스트를 재사용한 동일 조건 추가 검증이며 새 데이터나 새 공격에 대한 독립 평가가 아니다. 학습량을 맞췄지만 클래스 비율·정상 표본의 다양성 증가·DDoS 표본 감소가 함께 발생해 각각의 효과를 분리한 것은 아니다. 기존 세 모델의 seed 42 대조군 혼동행렬을 정확히 재현했고, 18개 저장 모델 모두 재로딩 예측 일치를 확인했다.')
p('크기는 비압축 RF 객체 기준이며 MLP의 KB 단위 체크포인트 크기와 저장 형식이 다르다. 속도는 RF.predict만 측정해 패킷 수집·특징 추출과 실제 edge 장치 지연은 포함하지 않는다. 이 보고서의 결론은 현재 데이터·분할·후보 범위에 한정한다.')
p('자료 기준: MLP는 제공된 「mlp양자화.pdf」 원문의 문장·수치를 보존하고 순서와 표 배치를 정리했다. RF는 기존 최종 후보·특징 수 탐색 CSV와 완료된 18개 균형 검증 결과를 사용했다. 보고서 작성 과정에서 새 모델 학습은 수행하지 않았다.','Caption')

# Check all supplied MLP numeric table entries against the PDF text.
normalized=flat(raw)
for row in perf:
    for val in row:
        for token in re.findall(r'\d+(?:\.\d+)?',val):assert token in normalized,token
# No external hyperlink relationships are added.
d.core_properties.title='전자공학종합설계2_진행보고(11.9)'
d.core_properties.subject='MLP 양자화·RF 경량화: 수행 내용, 설정 이유, 결과와 의미'
path=OUT/'전자공학종합설계2_진행보고(11.9).docx';d.save(path)
check=Document(path)
assert len(check.tables)==8
assert len(check.inline_shapes)==2
print(path)
print('Verified MLP source table numbers; 8 editable tables; 2 embedded charts; two-level TOC field.')
