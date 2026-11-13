"""Summarize the completed equal-budget CICIoT2023 RF balance ablation."""
import json
import os
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/ciciot2023_balanced_rf'
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'data/tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+
                     ['| '+' | '.join(map(str,r))+' |' for r in rows])


def main():
    df=pd.read_csv(OUT/'results.csv')
    protocol=json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
    status=json.loads((OUT/'status.json').read_text(encoding='utf-8'))
    assert status['status']=='complete' and len(df)==18
    assert df.saved_model_reload_verified.all()
    assert (df.n==6297039).all() and (df.n_benign==329362).all()
    assert (df[['tn','fp','fn','tp']].sum(axis=1)==df.n).all()
    for c in ['baseline','top5','compact']:
        assert json.loads((OUT/f'archive_reproduction_{c}.json').read_text())['exact_counts_match']
    means=df.groupby(['regime','candidate']).mean(numeric_only=True)
    stds=df.groupby(['regime','candidate']).std(numeric_only=True)
    labels={'baseline':'38특징·100트리','top5':'5특징·100트리','compact':'38특징·20트리'}
    regimes={'natural':'기존 비율','balanced':'50:50 학습'}
    order=[(r,c) for r in ['natural','balanced'] for c in ['baseline','top5','compact']]
    fmt=lambda value:f'{value:.6f}'
    result_rows=[]
    for r,c in order:
        m=means.loc[r,c];s=stds.loc[r,c]
        result_rows.append([regimes[r],labels[c],fmt(m.accuracy),f'{m.f1_macro:.6f} ± {s.f1_macro:.6f}',
                            fmt(m.benign_precision),fmt(m.benign_recall),fmt(m.recall),
                            f'{m.model_mb:.2f}',f'{m.infer_us_per_sample:.3f}'])
    samples=df.drop_duplicates(['regime','seed'])
    sampling=table(['학습 구성','seed','정상','DDoS','합계'],[[regimes[r.regime],r.seed,
                     f'{r.train_benign:,}',f'{r.train_ddos:,}',f'{r.train_rows:,}'] for r in samples.itertuples()])
    plt.rcParams.update({'font.family':'Malgun Gothic','axes.unicode_minus':False,'font.size':10,
                         'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(11,7.4),layout='constrained')
    for ax,key,title in zip(axes.flat,['f1_macro','benign_precision','benign_recall','model_mb'],
                            ['Macro F1','정상 Precision','정상 Recall','비압축 모델 크기 (MB)']):
        xs=np.arange(3)
        for offset,r,color in [(-.19,'natural','#8B9DAE'),(.19,'balanced','#168C87')]:
            vals=[means.loc[r,c][key] for c in ['baseline','top5','compact']]
            errs=[stds.loc[r,c][key] for c in ['baseline','top5','compact']]
            ax.bar(xs+offset,vals,width=.36,color=color,label=regimes[r],yerr=errs,capsize=3)
            for x,v in zip(xs+offset,vals):ax.text(x,v,f'{v:.3f}' if key!='model_mb' else f'{v:.1f}',
                                                   ha='center',va='bottom',fontsize=8)
        ax.set_xticks(xs,['38특징\n100트리','5특징\n100트리','38특징\n20트리'])
        ax.set_title(title,fontweight='bold');ax.set_ylim(0,None if key=='model_mb' else 1.1)
        ax.yaxis.grid(alpha=.15);ax.set_axisbelow(True)
    axes[0,0].legend(frameon=False)
    fig.savefig(OUT/'balance_tradeoff.png',dpi=190,facecolor='white');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for ax,key,title in zip(axes,['infer_us_per_sample','model_mb'],['RF 추론 시간 (µs/표본)','비압축 모델 크기 (MB)']):
        for r,color,marker in [('natural','#647C91','o'),('balanced','#168C87','s')]:
            for c in ['baseline','top5','compact']:
                m=means.loc[r,c]
                ax.scatter(m[key],m.f1_macro,color=color,marker=marker,s=65)
                ax.annotate(labels[c],(m[key],m.f1_macro),xytext=(4,5),textcoords='offset points',fontsize=8)
            ax.scatter([],[],color=color,marker=marker,label=regimes[r])
        ax.set_xlabel(title);ax.set_ylabel('Macro F1');ax.grid(alpha=.18);ax.margins(.22)
        ax.legend(frameon=False,fontsize=8)
    fig.savefig(OUT/'performance_cost.png',dpi=190,facecolor='white');plt.close(fig)
    detailed=table(['학습 구성','후보','seed','Accuracy','Macro F1','TN','FP','FN','TP'],
        [[regimes[r.regime],labels[r.candidate],r.seed,fmt(r.accuracy),fmt(r.f1_macro),
          r.tn,r.fp,r.fn,r.tp] for r in df.itertuples()])
    comparisons=[]
    for c in ['baseline','top5','compact']:
        a=means.loc['natural',c];b=means.loc['balanced',c]
        comparisons.append([labels[c],f'{100*(b.accuracy-a.accuracy):+.3f}',
                            f'{100*(b.f1_macro-a.f1_macro):+.3f}',
                            f'{100*(b.benign_precision-a.benign_precision):+.3f}',
                            f'{100*(b.benign_recall-a.benign_recall):+.3f}',
                            f'{100*(b.recall-a.recall):+.3f}'])
    base=means.loc['balanced','baseline'];compact=means.loc['balanced','compact'];top5=means.loc['balanced','top5']
    speed=base.infer_us_per_sample/compact.infer_us_per_sample
    paired=pd.read_csv(OUT/'paired_deltas.csv')
    all_macro_lower=bool((paired.f1_macro_delta<0).all())
    all_normal_recall_higher=bool((paired.benign_recall_delta>0).all())
    recommendation=('세 후보·세 seed의 9개 대응 비교에서 모두 균형 학습의 macro F1이 낮았다. '
        '정상 Recall은 모든 대응 비교에서 높았다. 따라서 이 테스트에서는 균형 학습이 정상 오탐을 줄이는 대신 '
        'DDoS 탐지와 종합 F1을 희생하는 방향으로 나타났다. 기존 결과를 폐기하거나 50:50 학습으로 전면 교체할 근거는 없다. '
        '기존 비율의 38특징·20트리 결과는 유지하고, 균형군은 학습 구성에 따른 오탐·미탐의 교환관계를 보여주는 추가 결과로 보관한다.'
        if all_macro_lower and all_normal_recall_higher else
        '균형 학습의 효과는 후보별·지표별 차이를 함께 보고 판단한다. 기존 결과를 폐기하지 않고 대응 비교 결과를 함께 보관한다.')
    validation=dict(rows=18,seeds=[42,43,44],all_test_counts_identical=True,
                    archive_reproduction_exact_for_all_three_seed42_controls=True,
                    all_models_reloaded=True,all_models_confusion_counts_consistent=True,
                    model_selection='none; all candidates prespecified',
                    test_sha256=protocol['test_sha256'])
    (OUT/'validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
    text=f'''# CICIoT2023 RF 경량화: 동일 학습량에서 클래스 균형의 영향

기존 PCAP 기반 38특징·비중첩 10패킷 데이터를 재사용했다. CICIDS2017이 아닌 CICIoT2023 실험이다. 원본 데이터·특징 계산·파일별 시간순 70/30 분할·테스트는 유지하고, 학습 표본 구성만 비교했다. 기존 결과 파일은 덮어쓰지 않았다.

## 연구 질문과 설계

학습 100만 행을 유지하면서 정상 표본을 약 5만 행에서 50만 행으로 늘리면, 특징 축소 및 트리 축소에 따른 정상/DDoS 성능과 모델 비용이 어떻게 달라지는지 확인했다. 특징 5개·트리 100개와 특징 38개·트리 20개는 서로 다른 경량화 축이다. RF에서는 특징 수 감소가 노드 수나 모델 크기 감소를 보장하지 않는다.

- 대조군: 기존 학습 풀에서 무작위 100만 행. seed 42에서 과거 baseline/top5/C1의 테스트 혼동행렬을 모두 정확히 재현했다.
- 균형군: 같은 학습 풀에서 정상 50만 + DDoS 50만, 중복 추출 없이 선택했다. 총학습량은 100만 행으로 같다.
- 설정: 38특징·100트리 기준선, 고정된 기존 상위 5특징·100트리, 기존 C1인 38특징·20트리. 깊이 무제한·최소 리프 표본 1. 각 구성에 seed 42/43/44를 적용해 총 18개 모델을 학습했다.
- 두 군 모두 class_weight=balanced를 유지했다. 균형군은 클래스 표본 수가 같아 가중치가 1이다. 가중치 보정과 정상 표본의 다양성 증가는 구분한다.
- top5는 기존 RF 중요도 상위 `Tot size`, `Tot sum`, `AVG`, `HTTPS`, `Max`다. 재순위화하지 않아 특징 선택 변경 효과를 섞지 않았다.
- 새로운 설정 선택 없이 사전에 정한 세 후보를 비교했다. 별도 검증 분할을 추가하지 않고 기존 70% 학습 풀을 사용했다. 이미 관찰한 테스트를 재사용한 고정 설정 대조 실험이며 새 holdout이나 검증 선택 실험이 아니다.

## 데이터와 표본 수

전체 20,990,150개 윈도우에서 학습 풀 {protocol['train_pool_rows']:,}개(정상 {protocol['train_pool_benign']:,} / DDoS {protocol['train_pool_ddos']:,})를 사용했다. 테스트는 정상 329,362 / DDoS 5,967,677, 총 6,297,039개로 모든 모델에 동일하다. 테스트를 50:50으로 바꾸지 않았다.

{sampling}

seed별 학습 인덱스와 고정 테스트 인덱스는 로컬에 보관하고 해시를 protocol/results에 기록했다. 파일·공격별 표본 수는 sampling_audit.csv, 원래 분할은 partition_audit.csv에 기록했다.

## 최종 테스트 결과

지표·비용은 seed 3회 평균이다. macro F1에 표준편차를 병기했다. Precision/Recall은 정상과 DDoS를 구분한다. MB는 RF 객체 비압축 joblib 크기이며 압축 저장 파일 크기는 results.csv의 model_file_mb다.

{table(['학습 구성','후보','Accuracy','Macro F1 ± SD','정상 Precision','정상 Recall','DDoS Recall','MB','µs/표본'],result_rows)}

![같은 학습량에서 클래스 구성과 RF 설정의 영향](balance_tradeoff.png)

오차 막대는 seed 3회의 표준편차다. 통계적 유의성을 검정한 결과는 아니다. 각 축의 막대는 0부터 표시했다.

## 같은 모델에서 학습 구성 변경 효과

50:50 학습 평균에서 기존 비율 학습 평균을 뺀 값이며 단위는 %p다. 테스트 클래스 구성은 동일하다.

{table(['후보','Accuracy 차이','Macro F1 차이','정상 Precision 차이','정상 Recall 차이','DDoS Recall 차이'],comparisons)}

정상 Recall 증가는 실제 정상을 DDoS로 오탐하는 비율의 감소를 뜻한다. 정상 Precision 증가는 정상으로 예측한 결과에 DDoS가 섞이는 비율의 감소를 뜻한다. 둘은 서로 다른 지표이므로 정상 Precision을 정상 클래스 정확도라고 부르지 않는다. 혼동행렬은 results.csv의 TN/FP/FN/TP에 기록했다.

## 경량화 해석

![RF 성능과 추론 비용·모델 크기의 관계](performance_cost.png)

각 점은 seed 3회 평균이다. RF 추론 시간은 작을수록, macro F1은 클수록 좋다. 크기와 속도는 서로 다른 비용이므로 각각 표시했다.

균형 학습 안에서 38특징·20트리는 38특징·100트리 대비 macro F1 차이 {100*(compact.f1_macro-base.f1_macro):+.4f}%p, 비압축 모델 크기 {base.model_mb:.2f} → {compact.model_mb:.2f} MB, RF 추론 속도 약 {speed:.2f}배다. 같은 데이터 구성에서 트리 축소의 비용·성능 관계를 보여준다.

균형 학습의 5특징·100트리는 38특징·100트리 대비 macro F1 차이 {100*(top5.f1_macro-base.f1_macro):+.4f}%p, 모델 크기 {base.model_mb:.2f} → {top5.model_mb:.2f} MB다. 특징 수뿐 아니라 노드 수·모델 크기를 함께 보고 경량화 여부를 판단해야 한다. 이 결과를 보고 새로운 특징 집합이나 설정을 추가 선택하지 않았다.

## 기존 RF 결과를 수정해야 하는가?

{recommendation}

이는 세 번의 반복에서 관찰한 결과이며 통계검정에 따른 유의성 주장이나 다른 배포 환경에 대한 보장은 아니다. 정상 오탐 감소가 최우선인 운영 조건에서는 균형군도 검토할 수 있지만, 그 선택 기준은 실제 운영 비용으로 정해야 한다.

## 범위와 한계

- 기존 테스트를 재사용했으므로 새 공격·새 환경에 대한 독립 검증이 아니다. 파일별 시간순 분할은 같은 캡처의 앞뒤 구간 비교이며 모든 연결 단위의 분리나 원본 패킷 전체의 대표성을 보장하지 않는다.
- 학습량을 맞췄지만 클래스 비율·정상 고유 표본 증가·DDoS 표본 감소가 함께 발생한다. 각 요인의 효과를 따로 분리한 실험은 아니다.
- 학습 풀에서만 재표집했다. 전처리 재수행, 테스트 재표집, 기기별 실험, LOAO, 정상 전체+동수 DDoS의 약 154만 행 확장 실험은 포함하지 않았다.
- 속도는 같은 테스트 10만 표본에 대한 단일 스레드 RF.predict, 워밍업 후 5회 중앙값이다. 데이터 수집·특징 추출·edge 장치 비용을 포함하지 않는다. 서로 다른 컴퓨터의 MLP 속도와 직접 비교하지 않는다.
- 이 결과는 RF 특징/트리 축소 결과다. MLP FP32→INT8 양자화 손실의 원인이 불균형이라는 증거는 아니며, 해당 원인은 MLP의 양자화 전후 클래스별 결과로 확인해야 한다.

## 재현과 검증

### 실행별 지표와 혼동행렬

TN=정상을 정상으로 예측, FP=정상을 DDoS로 오탐, FN=DDoS를 정상으로 미탐, TP=DDoS를 탐지한 수다. 아래는 평균이 아닌 각 실행의 실제 정수 개수다.

{detailed}

실행: `.venv/Scripts/python.exe -u src/run_ciciot2023_balanced_rf.py`, 정리: `.venv/Scripts/python.exe src/report_ciciot2023_balanced_rf.py`.

results.csv는 모델별 전체 지표·혼동행렬·비용·학습 표본 해시, summary.csv는 평균·표준편차, paired_deltas.csv는 같은 seed의 구성 간 차이, protocol.json은 입력/코드 해시와 프로토콜, archive_reproduction_*.json은 기존 세 모델 대조군 재현 확인이다. 18개 저장 모델 모두 다시 로드해 예측 일치를 확인했다.

완료 체크포인트 기준 누적 실행 시간: {status['elapsed_sec']/60:.2f}분(중단 직전 미저장 작업 및 서버 대기시간 제외). 서버 재시작 후 저장된 {protocol.get('resumed_completed_models',0)}개 모델의 결과를 재사용하고 나머지를 실행했다. 원본/가공 데이터·모델 바이너리·인덱스·실행 로그는 로컬에 보관한다.
'''
    (OUT/'REPORT.md').write_text(text,encoding='utf-8')
    print('Report complete:',OUT/'REPORT.md')


if __name__=='__main__':main()
