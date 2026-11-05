import json
import os
import random
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, KFold

def softmax(logits):
    logits = np.asarray(logits, dtype=float)
    if logits.ndim == 1:
        logits = logits.reshape(1, -1)
    logits = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(logits)
    s = exp.sum(axis=1, keepdims=True)
    s = np.where(s <= 0.0, 1.0, s)
    return exp / s

def proba_to_full(proba, classes, C, class_to_idx):
    out = np.zeros((proba.shape[0], C), dtype=float)
    for j, cls in enumerate(classes):
        key = str(cls)
        if key in class_to_idx:
            out[:, class_to_idx[key]] = proba[:, j]
    return out

def centroid_probs(X_train_s, y_idx, X_eval_s, C):
    global_mean = X_train_s.mean(axis=0)
    centroids = np.tile(global_mean, (C, 1))
    prior = np.zeros(C, dtype=float)
    for c in range(C):
        mask = y_idx == c
        cnt = int(mask.sum())
        prior[c] = float(cnt)
        if cnt > 0:
            class_mean = X_train_s[mask].mean(axis=0)
            centroids[c] = global_mean + 0.5 * (class_mean - global_mean)
    total = prior.sum()
    if total <= 0.0:
        prior[:] = 1.0 / C
    else:
        prior = prior / total
    own_d2 = np.sum((X_train_s - centroids[y_idx]) ** 2, axis=1)
    sigma2 = float(np.median(own_d2))
    if (not np.isfinite(sigma2)) or sigma2 <= 0.0:
        sigma2 = float(np.mean(own_d2) + 1e-12)
    x2 = np.sum(X_eval_s ** 2, axis=1)[:, None]
    c2 = np.sum(centroids ** 2, axis=1)[None, :]
    d2 = x2 + c2 - 2.0 * (X_eval_s @ centroids.T)
    d2 = np.maximum(d2, 0.0)
    logits = -d2 / (2.0 * sigma2) + np.log(prior + 1e-12)[None, :]
    return softmax(logits)

def main():
    base = os.getcwd()
    data_dir = os.path.join(base, 'data')
    with open(os.path.join(data_dir, 'protocol.json'), 'r') as f:
        protocol = json.load(f)
    seed = int(protocol.get('seed', 7))
    np.random.seed(seed)
    random.seed(seed)
    features = list(protocol['features'])
    row_id_col = protocol.get('row_id', 'row_id')
    target_cols = protocol.get('target_columns', ['target'])
    target_col = target_cols[0]
    output_columns = list(protocol['output_columns'])
    class_columns = [c for c in output_columns if c != row_id_col]
    C = len(class_columns)
    class_to_idx = {c: i for i, c in enumerate(class_columns)}
    train = pd.read_csv(os.path.join(data_dir, protocol.get('training_file', 'train.csv')))
    pred = pd.read_csv(os.path.join(data_dir, protocol.get('prediction_file', 'predict.csv')))
    X_train = train[features].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
    X_pred = pred[features].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
    y_train = train[target_col].astype(str).to_numpy()
    y_idx = np.array([class_to_idx.get(str(v), -1) for v in y_train], dtype=int)
    valid = y_idx >= 0
    counts = np.bincount(y_idx[valid], minlength=C).astype(float) if np.any(valid) else np.zeros(C, dtype=float)
    total_counts = counts.sum()
    if total_counts <= 0.0:
        prior = np.ones(C, dtype=float) / C
    else:
        prior = counts / total_counts
    oof_base = np.zeros((len(train), C), dtype=float)
    oof_cent = np.zeros((len(train), C), dtype=float)
    n = len(train)
    splits = []
    if n >= 2:
        pos_counts = counts[counts > 0]
        min_count = int(pos_counts.min()) if len(pos_counts) > 0 else 1
        if min_count >= 2:
            n_splits = min(5, min_count, n)
            if n_splits >= 2:
                splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
                splits = list(splitter.split(X_train, y_idx))
        else:
            n_splits = min(5, n)
            if n_splits >= 2:
                splitter = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
                splits = list(splitter.split(X_train))
    for train_idx, val_idx in splits:
        imp = SimpleImputer(strategy='median')
        sc = StandardScaler()
        X_tr_imp = imp.fit_transform(X_train[train_idx])
        X_tr_s = sc.fit_transform(X_tr_imp)
        X_va_s = sc.transform(imp.transform(X_train[val_idx]))
        y_tr = y_train[train_idx]
        y_tr_idx = y_idx[train_idx]
        uniq = np.unique(y_tr)
        if len(uniq) >= 2:
            pca = PCA(n_components=0.95, svd_solver='full', random_state=seed)
            Z_tr = pca.fit_transform(X_tr_s)
            Z_va = pca.transform(X_va_s)
            clf = LogisticRegression(solver='lbfgs', max_iter=5000, random_state=seed)
            clf.fit(Z_tr, y_tr)
            proba = clf.predict_proba(Z_va)
            classes = clf.classes_
        else:
            cls = uniq[0] if len(uniq) == 1 else y_train[0]
            proba = np.ones((len(val_idx), 1), dtype=float)
            classes = np.array([cls])
        oof_base[val_idx] = proba_to_full(proba, classes, C, class_to_idx)
        y_for_cent = y_tr_idx.copy()
        if np.any(y_for_cent < 0):
            y_for_cent[y_for_cent < 0] = 0
        oof_cent[val_idx] = centroid_probs(X_tr_s, y_for_cent, X_va_s, C)
    temps = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0]
    lams = [0.0, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5]
    ws = [0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5]
    best_T, best_lam, best_w, best_loss = 1.0, 0.0, 0.0, float('inf')
    if len(splits) > 0 and np.any(valid):
        idxs = np.where(valid)[0]
        log_base = np.log(np.clip(oof_base[idxs], 1e-15, 1.0))
        cent_sub = oof_cent[idxs]
        y_sub = y_idx[idxs]
        for T in temps:
            p_temp = softmax(log_base / T)
            for lam in lams:
                p_cal = (1.0 - lam) * p_temp + lam * prior[None, :]
                s = p_cal.sum(axis=1, keepdims=True)
                p_cal = p_cal / np.where(s <= 0.0, 1.0, s)
                for w in ws:
                    p = (1.0 - w) * p_cal + w * cent_sub
                    s = p.sum(axis=1, keepdims=True)
                    p = p / np.where(s <= 0.0, 1.0, s)
                    p = np.clip(p, 1e-15, 1.0)
                    s = p.sum(axis=1, keepdims=True)
                    p = p / np.where(s <= 0.0, 1.0, s)
                    loss = -np.mean(np.log(p[np.arange(len(y_sub)), y_sub]))
                    if loss < best_loss:
                        best_loss = float(loss)
                        best_T = float(T)
                        best_lam = float(lam)
                        best_w = float(w)
    imp = SimpleImputer(strategy='median')
    sc = StandardScaler()
    X_train_imp = imp.fit_transform(X_train)
    X_train_s = sc.fit_transform(X_train_imp)
    X_pred_s = sc.transform(imp.transform(X_pred))
    uniq_full = np.unique(y_train)
    if len(uniq_full) >= 2:
        pca = PCA(n_components=0.95, svd_solver='full', random_state=seed)
        Z_train = pca.fit_transform(X_train_s)
        Z_pred = pca.transform(X_pred_s)
        clf = LogisticRegression(solver='lbfgs', max_iter=5000, random_state=seed)
        clf.fit(Z_train, y_train)
        base_pred = proba_to_full(clf.predict_proba(Z_pred), clf.classes_, C, class_to_idx)
    else:
        cls = uniq_full[0] if len(uniq_full) == 1 else y_train[0]
        base_pred = np.zeros((len(pred), C), dtype=float)
        if str(cls) in class_to_idx:
            base_pred[:, class_to_idx[str(cls)]] = 1.0
        else:
            base_pred[:, 0] = 1.0
    y_for_cent_full = y_idx.copy()
    if np.any(y_for_cent_full < 0):
        y_for_cent_full[y_for_cent_full < 0] = 0
    cent_pred = centroid_probs(X_train_s, y_for_cent_full, X_pred_s, C)
    log_base_pred = np.log(np.clip(base_pred, 1e-15, 1.0))
    p_temp = softmax(log_base_pred / best_T)
    p_cal = (1.0 - best_lam) * p_temp + best_lam * prior[None, :]
    s = p_cal.sum(axis=1, keepdims=True)
    p_cal = p_cal / np.where(s <= 0.0, 1.0, s)
    p_final = (1.0 - best_w) * p_cal + best_w * cent_pred
    s = p_final.sum(axis=1, keepdims=True)
    p_final = p_final / np.where(s <= 0.0, 1.0, s)
    p_final = np.nan_to_num(p_final, nan=0.0, posinf=0.0, neginf=0.0)
    p_final[p_final < 0.0] = 0.0
    s = p_final.sum(axis=1, keepdims=True)
    zero = s[:, 0] <= 0.0
    if np.any(zero):
        p_final[zero, :] = 1.0 / C
        s = p_final.sum(axis=1, keepdims=True)
    p_final = p_final / s
    p_final = np.clip(p_final, 0.0, 1.0)
    s = p_final.sum(axis=1, keepdims=True)
    p_final = p_final / np.where(s <= 0.0, 1.0, s)
    out = pd.DataFrame(p_final, columns=class_columns)
    result = pd.DataFrame({row_id_col: pred[row_id_col].to_numpy()})
    for c in class_columns:
        result[c] = out[c].to_numpy()
    result = result[output_columns]
    result.to_csv(os.path.join(os.getcwd(), protocol.get('output_file', 'predictions.csv')), index=False)

if __name__ == '__main__':
    main()
