"""Evaluation helpers: classification metrics + inference cost (time, model size, memory)."""
import os
import tempfile
import time

import joblib
import numpy as np
import psutil
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, precision_score,
                             recall_score)


def classification_metrics(y_true, y_pred):
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    maj = max(np.mean(y_true == 1), np.mean(y_true == 0)) if len(y_true) else float('nan')
    return dict(n=int(len(y_true)), n_benign=int((y_true == 0).sum()), n_ddos=int((y_true == 1).sum()),
                accuracy=accuracy_score(y_true, y_pred),
                precision=precision_score(y_true, y_pred, zero_division=0),
                recall=recall_score(y_true, y_pred, zero_division=0),
                f1=f1_score(y_true, y_pred, zero_division=0),
                f1_macro=f1_score(y_true, y_pred, average='macro', zero_division=0),
                majority_baseline_acc=maj, tn=int(tn), fp=int(fp), fn=int(fn), tp=int(tp))


def inference_cost(model, X, n_samples=100_000, repeats=5, seed=0):
    """Median wall time of single-threaded predict() over a fixed random sample."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(X), size=min(n_samples, len(X)), replace=False)
    Xs = np.ascontiguousarray(np.asarray(X)[idx])
    old = getattr(model, 'n_jobs', None)
    if old is not None:
        model.n_jobs = 1
    model.predict(Xs[:1000])  # warm-up
    times = []
    for _ in range(repeats):
        t = time.perf_counter()
        model.predict(Xs)
        times.append(time.perf_counter() - t)
    if old is not None:
        model.n_jobs = old
    total = float(np.median(times))
    n = len(Xs)
    return dict(infer_samples=n, infer_total_ms=total * 1e3, infer_us_per_sample=total / n * 1e6,
                infer_samples_per_sec=n / total)


def model_size_mb(model):
    with tempfile.NamedTemporaryFile(suffix='.joblib', delete=False) as f:
        path = f.name
    try:
        joblib.dump(model, path, compress=0)
        return os.path.getsize(path) / 1e6
    finally:
        os.remove(path)


def peak_rss_mb():
    info = psutil.Process().memory_info()
    return getattr(info, 'peak_wset', info.rss) / 1e6


def model_stats(model):
    ests = getattr(model, 'estimators_', [])
    return dict(n_trees=len(ests),
                total_nodes=int(sum(e.tree_.node_count for e in ests)),
                max_depth=int(max((e.tree_.max_depth for e in ests), default=0)))
