"""Add a validation-constrained compact native RF, validate artifacts, then plot."""
import argparse
import hashlib
from importlib.metadata import version
import json
import platform
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd

import compare_cicids2017_rf as experiment
from plot_cicids2017_comparison import main as plot

ROOT, OUT = experiment.ROOT, experiment.OUT


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--wait', action='store_true', help='Wait for the main comparison to finish before benchmarking')
    args = ap.parse_args()
    if args.wait:
        print('Waiting for main comparison to finish (no concurrent RF benchmarking)', flush=True)
        while True:
            try:
                state = json.loads((OUT / 'status.json').read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(5)
                continue
            if state['status'] == 'failed':
                raise RuntimeError(f'Main comparison failed: {state}')
            if state['status'] == 'complete':
                break
            time.sleep(5)
    started = time.time()
    previous_status = json.loads((OUT / 'status.json').read_text())
    experiment.save_json(OUT / 'status.json', dict(status='running', stage='compact_native_validation', updated=time.time()))
    directory = OUT / 'native_flows'
    native_results = pd.read_csv(directory / 'final_test.csv')
    if 'validation_lightweight' not in set(native_results.candidate):
        protocol = json.loads((directory / 'protocol.json').read_text())
        selection = json.loads((directory / 'selection.json').read_text())
        search = pd.read_csv(directory / 'validation_search.csv')
        manifest = json.loads((directory / 'search_manifest.json').read_text())
        configs = {r['config_id']: experiment.Config(tuple(r['columns']), r['trees'], r['depth'], r['leaf'], r['weight'])
                   for r in manifest['configs']}
        tolerance = .001
        threshold = selection['best_validation']['f1_macro'] - tolerance
        eligible = search[search.f1_macro >= threshold].sort_values(['trees', 'n_features', 'depth', 'min_leaf'])
        features = protocol['features']
        d = pd.read_parquet(ROOT / 'data/processed/cicids2017_native_flows/flows.parquet')
        raw = d[features].to_numpy(np.float32)
        meta = d[['source_pcap', 'row_in_file', 'binary_label', 'window_start_ts', 'split_group']].copy()
        y = d.binary_label.to_numpy(copy=True)
        del d
        masks = experiment.partitions(meta, grouped=True)
        fit_idx = experiment.cap_indices(masks['fit'], 1000000)
        X, _, _ = experiment.impute_fit_only(raw, fit_idx)
        chosen = None
        for _, row in eligible.head(5).iterrows():
            cfg = configs[row.config_id]
            print(f'Compact native validation: k={len(cfg.columns)}, trees={cfg.trees}', flush=True)
            model, val = experiment.fit_evaluate(X, y, fit_idx, np.flatnonzero(masks['validation']), cfg)
            del model
            val['evaluation'] = 'validation'
            experiment.append_result(directory / 'lightweight_validation.csv', val)
            if val['f1_macro'] >= threshold:
                chosen = cfg
                break
        if chosen is None:
            raise ValueError('No compact native candidate meets the declared validation tolerance')
        experiment.save_json(directory / 'lightweight_selection.json', dict(
            config_id=chosen.key, columns=chosen.columns, trees=chosen.trees, depth=chosen.depth,
            leaf=chosen.leaf, weight=chosen.weight, validation=val,
            allowed_macro_f1_loss=tolerance, validation_threshold=threshold, test_used_for_selection=False))
        del X
        idx = experiment.cap_indices(masks['fit'] | masks['validation'], 1000000)
        X, medians, _ = experiment.impute_fit_only(raw, idx)
        model, result = experiment.fit_evaluate(X, y, idx, np.flatnonzero(masks['test']), chosen, costs=True)
        result.update(arm='native_flows', candidate='validation_lightweight', evaluation='test', sample_unit='flow',
                      selected_on='validation only', features=';'.join(features[i] for i in chosen.columns))
        experiment.append_result(directory / 'final_test.csv', result)
        pd.Series(model.feature_importances_, index=[features[i] for i in chosen.columns]).sort_values(ascending=False).to_csv(
            directory / 'validation_lightweight_seed42_importance.csv', header=['importance'])
        joblib.dump(dict(model=model, medians=medians, features=features, selected_columns=chosen.columns,
                         sample_unit='flow'), directory / 'validation_lightweight.joblib', compress=3)
    rows = []
    for arm in ['native_flows', 'legacy_windows']:
        rows += pd.read_csv(OUT / arm / 'final_test.csv').to_dict('records')
    experiment.report(rows)
    validation = []
    excluded_inputs = {'Flow ID', 'Source IP', 'Source Port', 'Destination IP', 'Destination Port',
                       'Timestamp', 'Label', 'binary_label', 'source_pcap', 'row_in_file', 'split_group'}
    native_inputs = set(json.loads((OUT / 'native_flows/protocol.json').read_text())['features'])
    if native_inputs & excluded_inputs:
        raise ValueError('Identifiers or labels must not enter native RF input')
    for arm in ['native_flows', 'legacy_windows']:
        final = pd.read_csv(OUT / arm / 'final_test.csv')
        if final.n.nunique() != 1 or not (final.n == final.tn + final.fp + final.fn + final.tp).all():
            raise ValueError(f'Inconsistent test counts: {arm}')
        if not np.allclose(final.recall, final.tp / (final.tp + final.fn)):
            raise ValueError(f'Inconsistent DDoS recall: {arm}')
        for path in (OUT / arm).glob('*.joblib'):
            bundle = joblib.load(path)
            model = bundle['model']
            if model.n_features_in_ != len(bundle['selected_columns']) or model.classes_.tolist() != [0, 1]:
                raise ValueError(f'Invalid saved model: {path}')
            validation.append(dict(model=str(path.relative_to(OUT)), features=model.n_features_in_,
                                   trees=len(model.estimators_), load_verified=True))
    experiment.save_json(OUT / 'artifact_validation.json', dict(models=validation, test_counts_consistent=True,
                         recall_consistent=True, test_not_used_for_selection=True,
                         native_identifiers_ports_timestamps_labels_excluded=True))
    environment = json.loads((OUT / 'environment.json').read_text())
    environment.update(platform=platform.platform(), pandas=pd.__version__, joblib=joblib.__version__,
                       pyarrow=version('pyarrow'), matplotlib=version('matplotlib'),
                       source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in [ROOT / 'src' / name for name in [
                                          'compare_cicids2017_rf.py', 'prepare_cicids2017_flows.py',
                                          'finalize_cicids2017_comparison.py', 'plot_cicids2017_comparison.py',
                                          'metrics.py', 'train_rf.py']]})
    experiment.save_json(OUT / 'environment.json', environment)
    paths = [ROOT / 'data/processed/cicids2017_native_flows/flows.parquet',
             ROOT / 'data/raw/cicids2017/labels/GeneratedLabelledFlows.zip']
    paths += sorted((ROOT / 'data/processed/cicids2017_ddos_benign').glob('*.parquet'))
    inputs = []
    for path in paths:
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
        inputs.append(dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size, sha256=digest.hexdigest()))
    experiment.save_json(OUT / 'input_manifest.json', inputs)
    plot()
    report = OUT / 'REPORT.md'
    text = report.read_text(encoding='utf-8')
    text += ('\n## 추가 해석\n\n'
             '- native의 경량 후보는 검증 macro F1 손실 0.001 이내에서 트리 수·특징 수가 적은 설정을 우선하고, 최대 100만 fit 표본으로 검증한 뒤 테스트했다.\n'
             '- native 그룹 분할은 같은 날짜의 5-tuple 그룹 첫 시각을 정렬 기준으로 삼는다. 그룹 전체를 보존하므로 개별 flow의 시각 경계가 완전히 분리되는 것은 아니며, 두 방식 모두 엄격한 공통 시각 경계의 미래 예측 평가가 아니다.\n'
             '- seed 42/43/44 반복은 동일 테스트 분할에서 학습 표본 선택·RF 난수의 변동을 본다. 새 데이터셋이나 새 공격에 대한 반복 검증은 아니다.\n'
             '- 모델 joblib은 RF 객체 단독이 아니라 model, medians, features, selected_columns를 가진 전처리 포함 묶음이다. 원본 후보 열을 features 순서로 배열하고 medians로 결측을 채운 뒤 selected_columns를 선택해 예측한다.\n')
    report.write_text(text, encoding='utf-8')
    experiment.save_json(OUT / 'status.json', dict(status='complete', stage='complete_with_compact_and_artifact_validation',
                         updated=time.time(), report='REPORT.md',
                         elapsed_sec=previous_status.get('elapsed_sec', 0) + time.time() - started))
    print(pd.read_csv(OUT / 'summary.csv').to_string(index=False), flush=True)


if __name__ == '__main__':
    main()
