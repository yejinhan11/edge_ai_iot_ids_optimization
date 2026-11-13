"""Validation-selected RF comparisons: legacy windows and native CICFlowMeter flows.

Feature ranking/configuration selection never reads test labels. Test evaluation
is restricted to frozen finalists. No DDoS subtype LOAO is fabricated from DoS.
"""
import argparse
from dataclasses import dataclass, asdict
import gc
import hashlib
import itertools
import json
from pathlib import Path
import platform
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
import sklearn

from build_dataset import FEATURES
from metrics import classification_metrics, inference_cost, model_size_mb, model_stats
from prepare_cicids2017_flows import prepare

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/cicids2017_comparison'


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, default=str)
    for attempt in range(20):
        try:
            path.write_text(text, encoding='utf-8')
            return
        except PermissionError:
            time.sleep(.1)
    raise PermissionError(f'Cannot write {path}')


def partitions(meta, grouped=False):
    """Same outer 70/30 for windows; whole-connection groups for native flows."""
    if grouped:
        groups = meta.groupby('split_group', sort=False).agg(
            source_pcap=('source_pcap', 'first'), binary_label=('binary_label', 'max'),
            first_ts=('window_start_ts', 'min'), count=('binary_label', 'size'))
        groups = groups.sort_values(['first_ts'], kind='stable')
        groups['split'] = 'test'
        for _, g in groups.groupby(['source_pcap', 'binary_label'], sort=False):
            prior = g['count'].cumsum() - g['count']
            pool = prior < g['count'].sum() * .7
            fit = prior < g.loc[pool, 'count'].sum() * .8
            groups.loc[g.index[pool & ~fit], 'split'] = 'validation'
            groups.loc[g.index[pool & fit], 'split'] = 'fit'
        label = meta.split_group.map(groups.split).to_numpy()
    else:
        g = meta.groupby(['source_pcap', 'binary_label'], observed=True)
        rank = g.row_in_file.rank(method='first').to_numpy() - 1
        total = g.row_in_file.transform('size').to_numpy()
        pool_count = np.ceil(total * .7)
        pool = rank < total * .7
        fit = rank < pool_count * .8
        label = np.where(~pool, 'test', np.where(fit, 'fit', 'validation'))
    masks = {name: label == name for name in ['fit', 'validation', 'test']}
    if not np.all(sum(m.astype(np.int8) for m in masks.values()) == 1):
        raise ValueError('Partitions must be disjoint and exhaustive')
    for name, mask in masks.items():
        if set(meta.loc[mask, 'binary_label']) != {0, 1}:
            raise ValueError(f'Both classes required in {name}')
    return masks


def cap_indices(mask, maximum, seed=42):
    idx = np.flatnonzero(mask)
    return np.random.default_rng(seed).choice(idx, maximum, replace=False) if len(idx) > maximum else idx


def impute_fit_only(raw, train_idx):
    """Median is fit on training rows; missing-only columns receive zero."""
    sample = raw[train_idx]
    medians = np.zeros(raw.shape[1], dtype=np.float32)
    varying = []
    for col in range(raw.shape[1]):
        valid = sample[:, col][np.isfinite(sample[:, col])]
        medians[col] = np.median(valid) if len(valid) else 0
        if len(valid) and valid.max() != valid.min():
            varying.append(col)
    result = raw.copy() if not np.isfinite(raw).all() else raw
    if result is not raw:
        for start in range(0, len(raw), 100000):
            block = result[start:start + 100000]
            r, c = np.where(~np.isfinite(block))
            block[r, c] = medians[c]
    return result, medians, varying


@dataclass(frozen=True)
class Config:
    columns: tuple
    trees: int = 100
    depth: int = 0
    leaf: int = 1
    weight: str | None = 'balanced'

    @property
    def key(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


def forest(cfg, seed=42):
    return RandomForestClassifier(n_estimators=cfg.trees, max_depth=cfg.depth or None,
                                  min_samples_leaf=cfg.leaf, class_weight=cfg.weight,
                                  n_jobs=-1, random_state=seed)


def grids(p, rank, perm=None):
    full = tuple(range(p))
    configs = [Config(full)]
    if perm is None:
        configs += [Config(tuple(rank[:k])) for k in [5, 10, 15, 20] if k < p]
        for k, trees in itertools.product([min(15, p), p], [10, 20, 50, 100]):
            cols = full if k == p else tuple(rank[:k])
            configs.append(Config(cols, trees))
        for k, depth, leaf in itertools.product([min(15, p), p], [8, 12, 16, 0], [1, 10, 100]):
            cols = full if k == p else tuple(rank[:k])
            configs.append(Config(cols, 20, depth, leaf))
    else:
        for order, k in itertools.product([rank, perm], [5, 10, 15, 20, 30]):
            if k < p:
                configs.append(Config(tuple(order[:k])))
        for cols, trees in itertools.product([full, tuple(perm[:min(20, p)])], [20, 50, 100, 200]):
            configs.append(Config(cols, trees))
        for cols, depth, leaf in itertools.product([full, tuple(perm[:min(20, p)])], [8, 12, 16, 0], [1, 10, 100]):
            configs.append(Config(cols, 50, depth, leaf))
        for trees, weight in itertools.product([50, 100], [None, 'balanced_subsample']):
            configs.append(Config(tuple(perm[:min(20, p)]), trees, weight=weight))
    return list(dict.fromkeys(configs))


def fit_evaluate(X, y, train_idx, eval_idx, cfg, seed=42, costs=False):
    model = forest(cfg, seed)
    started = time.perf_counter()
    model.fit(X[train_idx][:, cfg.columns], y[train_idx])
    seconds = time.perf_counter() - started
    Xt = X[eval_idx][:, cfg.columns]
    result = classification_metrics(y[eval_idx], model.predict(Xt))
    result.update(train_sec=seconds, train_rows=len(train_idx), n_features=len(cfg.columns),
                  trees=cfg.trees, depth=cfg.depth, min_leaf=cfg.leaf, weight=cfg.weight,
                  config_id=cfg.key, seed=seed, columns=json.dumps(cfg.columns), **model_stats(model))
    if costs:
        result.update(model_mb=model_size_mb(model), **inference_cost(model, Xt, seed=seed))
    return model, result


def append_result(path, row):
    pd.DataFrame([row]).to_csv(path, mode='a', header=not path.exists(), index=False)


def select_best(rows):
    """Only validation results are accepted by this selection function."""
    if any(r.get('evaluation') != 'validation' for r in rows):
        raise ValueError('Model selection must use validation results only')
    return max(rows, key=lambda r: (r['f1_macro'], r['recall'], -r['n_features'], -r['trees']))


def run_arm(arm, raw, y, meta, features, screen_cap, configs_override=None):
    directory = OUT / arm
    directory.mkdir(parents=True, exist_ok=True)
    split = partitions(meta, grouped=arm == 'native_flows')
    native = arm == 'native_flows'
    cap = screen_cap if native else 1000000
    train_idx = cap_indices(split['fit'], cap)
    val_idx = np.flatnonzero(split['validation'])
    test_idx = np.flatnonzero(split['test'])
    X, medians, varying = impute_fit_only(raw, train_idx)
    # Preserve the legacy 38 columns exactly; native constant removal is fit-only.
    active = varying if native else list(range(len(features)))
    dropped = [features[i] for i in range(len(features)) if i not in active]
    if native:
        raw = raw[:, active]
        X = X[:, active]
        medians = medians[active]
        features = [features[i] for i in active]
    audit = []
    for name, mask in split.items():
        for cls in [0, 1]:
            audit.append(dict(partition=name, binary_label=cls, rows=int((mask & (y == cls)).sum())))
    pd.DataFrame(audit).to_csv(directory / 'partition_audit.csv', index=False)
    save_json(directory / 'protocol.json', dict(features=features, dropped_fit_constant=dropped,
              outer_train_fraction=.7, inner_train_fraction=.8, screen_cap=cap,
              final_cap=1000000, seed=42, grouping='day-connection' if native else 'source-label',
              test_previously_observed=not native, median_fit_partition='fit only',
              counts={name: int(mask.sum()) for name, mask in split.items()},
              partition_sha256={name: hashlib.sha256(np.flatnonzero(mask).tobytes()).hexdigest()
                                for name, mask in split.items()}))
    print(f'{arm}: rows={len(y):,} features={len(features)} fit={len(train_idx):,} validation={len(val_idx):,} test={len(test_idx):,}', flush=True)
    ranking_path = directory / 'ranking.json'
    base = Config(tuple(range(len(features))))
    rows_path = directory / 'validation_search.csv'
    rows = pd.read_csv(rows_path).to_dict('records') if rows_path.exists() else []
    if ranking_path.exists():
        ranking = json.loads(ranking_path.read_text())
        rank, perm = ranking['mdi_order'], ranking['permutation_order']
    else:
        print(f'{arm}: fitting ranking baseline', flush=True)
        model, baseline = fit_evaluate(X, y, train_idx, val_idx, base)
        baseline.update(evaluation='validation', arm=arm)
        if base.key not in {r['config_id'] for r in rows}:
            append_result(rows_path, baseline)
            rows.append(baseline)
        mdi = model.feature_importances_
        rank = np.argsort(-mdi, kind='stable').tolist()
        pd.DataFrame({'feature': features, 'importance': mdi}).sort_values('importance', ascending=False).to_csv(directory / 'mdi_ranking.csv', index=False)
        perm = None
        if native:
            pi_idx = cap_indices(split['validation'], 30000)
            model.n_jobs = 1
            print(f'{arm}: validation permutation ranking ({len(pi_idx):,} rows)', flush=True)
            pi = permutation_importance(model, X[pi_idx], y[pi_idx], scoring='f1_macro',
                                        n_repeats=2, random_state=42, n_jobs=1)
            perm = sorted(range(len(features)), key=lambda i: (-pi.importances_mean[i], -mdi[i], i))
            pd.DataFrame({'feature': features, 'importance_mean': pi.importances_mean,
                          'importance_std': pi.importances_std}).sort_values('importance_mean', ascending=False).to_csv(directory / 'permutation_ranking.csv', index=False)
        save_json(ranking_path, dict(mdi_order=rank, permutation_order=perm))
        del model
        gc.collect()
    # Feasibility is an explicitly declared scheduling gate, not a universal suitability criterion.
    base_row = next(r for r in rows if r['config_id'] == base.key)
    feasible = native or (base_row['f1_macro'] >= .90 and base_row['recall'] >= .90)
    configs = configs_override or (grids(len(features), rank, perm) if feasible else [base])
    save_json(directory / 'search_manifest.json', dict(feasibility_gate_passed=feasible,
              feasibility_gate='window validation macro F1 >= .90 and DDoS recall >= .90; scheduling only',
              configs=[dict(config_id=c.key, **asdict(c)) for c in configs]))
    lookup = {c.key: c for c in configs}
    done = {r['config_id'] for r in rows}
    started = time.time()
    for i, cfg in enumerate(configs):
        if cfg.key in done:
            continue
        save_json(OUT / 'status.json', dict(status='running', stage='validation_search', arm=arm,
                  completed=len(done), total=len(configs), current=asdict(cfg), updated=time.time()))
        model, result = fit_evaluate(X, y, train_idx, val_idx, cfg)
        result.update(evaluation='validation', arm=arm)
        append_result(rows_path, result)
        rows.append(result)
        done.add(cfg.key)
        print(f'{arm} {len(done)}/{len(configs)} k={len(cfg.columns)} trees={cfg.trees} depth={cfg.depth} leaf={cfg.leaf} '
              f'val F1m={result["f1_macro"]:.5f} recall={result["recall"]:.5f} fit={result["train_sec"]:.1f}s', flush=True)
        del model
        gc.collect()
    eligible = [r for r in rows if r['config_id'] in lookup]
    if native and cap < 1000000:
        full_fit_idx = cap_indices(split['fit'], 1000000)
        large_X, _, _ = impute_fit_only(raw, full_fit_idx)
        top_ids = [r['config_id'] for r in sorted(eligible, key=lambda r: r['f1_macro'], reverse=True)[:3]]
        refined = []
        for key in dict.fromkeys(top_ids + [base.key]):
            cfg = lookup[key]
            print(f'{arm}: full-cap validation refinement {key}', flush=True)
            model, result = fit_evaluate(large_X, y, full_fit_idx, val_idx, cfg)
            result.update(evaluation='validation', arm=arm)
            append_result(directory / 'validation_refinement.csv', result)
            refined.append(result)
            del model
        eligible = refined
        del large_X
    selected = lookup[select_best(eligible)['config_id']]
    # Freeze this file before any final test evaluation.
    save_json(directory / 'selection.json', dict(selected=asdict(selected), config_id=selected.key,
              criterion='highest validation macro F1, then recall; fewer features/trees break ties',
              best_validation=select_best(eligible), test_used_for_selection=False))
    finalists = {'baseline': base, 'validation_selected': selected}
    if not native and feasible:
        finalists.update(C1=Config(tuple(range(len(features))), 20),
                          C2=Config(tuple(range(len(features))), 10),
                          C3=Config(tuple(rank[:15]), 20),
                          C4=Config(tuple(range(len(features))), 20, 16))
    del X
    gc.collect()
    pool = split['fit'] | split['validation']
    final_rows = []
    final_path = directory / 'final_test.csv'
    previous = pd.read_csv(final_path) if final_path.exists() else pd.DataFrame()
    for name, cfg in finalists.items():
        seeds = [42, 43, 44] if name == 'validation_selected' else [42]
        for seed in seeds:
            old = previous[(previous.candidate == name) & (previous.seed == seed)] if len(previous) else previous
            if len(old):
                final_rows.extend(old.to_dict('records'))
                continue
            final_idx = cap_indices(pool, 1000000, seed)
            final_X, final_medians, _ = impute_fit_only(raw, final_idx)
            save_json(OUT / 'status.json', dict(status='running', stage='final_test', arm=arm,
                      candidate=name, seed=seed, updated=time.time()))
            print(f'{arm}: final {name} seed={seed}', flush=True)
            model, result = fit_evaluate(final_X, y, final_idx, test_idx, cfg, seed, costs=True)
            result.update(arm=arm, candidate=name, evaluation='test',
                          sample_unit='flow' if native else '10-packet window',
                          selected_on='validation only',
                          features=';'.join(features[i] for i in cfg.columns))
            append_result(final_path, result)
            final_rows.append(result)
            pd.Series(model.feature_importances_, index=[features[i] for i in cfg.columns]).sort_values(ascending=False).to_csv(
                directory / f'{name}_seed{seed}_importance.csv', header=['importance'])
            if seed == 42:
                joblib.dump(dict(model=model, medians=final_medians, features=features,
                                 selected_columns=cfg.columns, sample_unit=result['sample_unit']),
                            directory / f'{name}.joblib', compress=3)
            print(f'{arm}: TEST {name} seed={seed} F1m={result["f1_macro"]:.5f} recall={result["recall"]:.5f} '
                  f'{result["infer_us_per_sample"]:.2f}us {result["model_mb"]:.2f}MB', flush=True)
            del model, final_X
            gc.collect()
    return final_rows


def report(rows):
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / 'comparison.csv', index=False)
    summary = frame.groupby(['arm', 'candidate'], sort=False).agg(
        seeds=('seed', 'size'), f1_macro_mean=('f1_macro', 'mean'), f1_macro_std=('f1_macro', 'std'),
        precision_mean=('precision', 'mean'), recall_mean=('recall', 'mean'),
        features=('n_features', 'first'), trees=('trees', 'first'),
        model_mb=('model_mb', 'mean'), infer_us=('infer_us_per_sample', 'mean'))
    summary.to_csv(OUT / 'summary.csv')
    lines = ['# CICIDS2017 RF 비교', '',
             'BENIGN/DDoS 이진 분류. DoS·PortScan·Bot 등은 공격 양성에 합치지 않았다.', '',
             '## 두 표본 단위', '',
             '- legacy_windows: 기존 38특징·10패킷 방식. 파일·라벨별 앞 70% 중 80%로 fit, 나머지로 validation, 뒤 30%로 test. 기존에 관찰한 테스트를 고정해서 재사용했다.',
             '- native_flows: 공식 CICFlowMeter 수치 특징. IP·port·Flow ID·Timestamp는 입력에서 제외하고 동일 특징 중복 및 라벨 충돌을 제거했다. 같은 날짜의 양방향 5-tuple 전체를 한 분할에 묶고 시간순으로 나눴다.',
             '- flow와 10패킷 윈도우는 표본·라벨 품질·정제·분할이 다르다. 서로의 F1 차이를 특징만 바꾼 순수 효과로 해석하지 않는다. legacy_windows 안의 baseline/C1–C4/선택 모델은 동일 테스트 표본에서 비교한다.', '',
             '## 선택 방법', '',
             '특징 순위·상수 제거·결측치 중앙값·설정 선택은 fit/validation에 한정했다. native 탐색은 30만 fit 표본으로 선별하고 상위 3개와 baseline을 최대 100만 fit 표본으로 재검증했다. 최종 후보를 selection.json에 동결한 다음 앞 70%에서 최대 100만 행으로 재학습하고 test를 평가했다. 선택 모델은 seed 42/43/44로 반복했다.',
             '이번 후보 범위의 검증 최고 설정이며, 모든 가능한 특징·설정의 전역 최적해를 보장하지 않는다.', '',
             '## LOAO', '',
             'Leave One Attack Out: 공격 한 종류를 학습에서 빼고, 다른 공격으로 학습한 모델이 빠진 공격을 탐지하는지 평가한다. 현재 BENIGN/DDoS 범위에는 DDoS 라벨이 한 종류뿐이다. 이를 빼면 학습 양성이 없어 이진 RF LOAO는 성립하지 않는다. DoS를 DDoS로 바꾸거나 임의 시간 구간을 공격 종류라고 부르지 않았다.', '',
             '## 결과 (테스트)', '',
             '| 방식 | 후보 | 특징 | 트리 | macro F1 평균 | DDoS precision | DDoS recall | MB | µs/표본 |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for (arm, candidate), r in summary.iterrows():
        lines.append(f'| {arm} | {candidate} | {r.features:.0f} | {r.trees:.0f} | {r.f1_macro_mean:.6f} | {r.precision_mean:.6f} | {r.recall_mean:.6f} | {r.model_mb:.2f} | {r.infer_us:.3f} |')
    lines += ['', '공식 특징/시나리오 출처: https://www.unb.ca/cic/datasets/ids-2017.html', '',
              '설정별 검증 결과는 각 arm의 validation_search.csv, 최종 평가 상세는 final_test.csv, 분할 수와 특징 목록은 protocol.json/partition_audit.csv, 검증 선택은 selection.json에 기록했다.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    save_json(OUT / 'environment.json', dict(python=platform.python_version(), sklearn=sklearn.__version__,
              numpy=np.__version__, seed=42, final_seeds=[42, 43, 44],
              loao=dict(status='not_applicable', positive_attack_labels=['DDoS'],
                        reason='holding out the only DDoS class leaves no training positives')))
    all_rows = []
    try:
        save_json(OUT / 'status.json', dict(status='running', stage='prepare_native'))
        path = prepare()
        manifest = json.loads(path.with_suffix('.json').read_text())
        save_json(OUT / 'native_preparation.json', manifest)
        d = pd.read_parquet(path)
        features = manifest['features']
        raw = d[features].to_numpy(np.float32)
        meta = d[['source_pcap', 'row_in_file', 'binary_label', 'window_start_ts', 'split_group']].copy()
        y = d.binary_label.to_numpy(copy=True)
        del d
        gc.collect()
        all_rows += run_arm('native_flows', raw, y, meta, features, 300000)
        del raw, y, meta
        gc.collect()
        save_json(OUT / 'status.json', dict(status='running', stage='load_legacy_windows'))
        data_dir = ROOT / 'data/processed/cicids2017_ddos_benign'
        cols = FEATURES + ['binary_label', 'source_pcap', 'row_in_file', 'window_start_ts']
        d = pd.concat([pd.read_parquet(p, columns=cols) for p in sorted(data_dir.glob('*.parquet'))], ignore_index=True)
        raw = d[FEATURES].to_numpy(np.float32)
        meta = d[['source_pcap', 'row_in_file', 'binary_label', 'window_start_ts']].copy()
        y = d.binary_label.to_numpy(copy=True)
        del d
        gc.collect()
        all_rows += run_arm('legacy_windows', raw, y, meta, FEATURES, 1000000)
        report(all_rows)
        save_json(OUT / 'status.json', dict(status='complete', stage='complete', elapsed_sec=time.time()-started))
    except BaseException as error:
        save_json(OUT / 'status.json', dict(status='failed', error=str(error), elapsed_sec=time.time()-started))
        raise


if __name__ == '__main__':
    main()
