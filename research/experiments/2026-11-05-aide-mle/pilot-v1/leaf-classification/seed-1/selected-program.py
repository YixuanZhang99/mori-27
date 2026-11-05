import os
import json
import warnings
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, QuantileTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.neighbors import KNeighborsClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

def align_proba(model, X, K):
    P = model.predict_proba(X)
    out = np.full((X.shape[0], K), 1e-12, dtype=float)
    for j, c in enumerate(model.classes_):
        try:
            ci = int(c)
        except Exception:
            ci = j
        if 0 <= ci < K:
            out[:, ci] = P[:, j]
        elif 0 <= j < K:
            out[:, j] = P[:, j]
    out = np.clip(out, 1e-15, 1.0)
    out = out / out.sum(axis=1, keepdims=True)
    return out

def map_labels(y_raw, classes):
    class_to_idx = {c: i for i, c in enumerate(classes)}
    K = len(classes)
    y_str = y_raw.astype(object).map(lambda v: str(v))
    if all(s in class_to_idx for s in y_str):
        return np.array([class_to_idx[s] for s in y_str], dtype=int)
    num = pd.to_numeric(y_raw, errors='coerce')
    if num.notna().all():
        nums = num.astype(int).to_numpy()
        uniq = np.sort(np.unique(nums))
        if len(uniq) == K:
            if np.array_equal(uniq, np.arange(K)):
                return nums.astype(int)
            if np.array_equal(uniq, np.arange(1, K + 1)):
                return (nums - 1).astype(int)
            mp = {int(v): i for i, v in enumerate(uniq)}
            return np.array([mp[int(v)] for v in nums], dtype=int)
        if nums.min() >= 0 and nums.max() < K:
            return nums.astype(int)
        if nums.min() >= 1 and nums.max() <= K:
            return (nums - 1).astype(int)
        mp = {int(v): i for i, v in enumerate(uniq)}
        return np.array([mp[int(v)] for v in nums], dtype=int)
    uniq = sorted(set(y_str))
    if len(uniq) == K:
        sorted_classes = sorted(classes)
        mp = {u: class_to_idx[sorted_classes[i]] for i, u in enumerate(uniq)}
        return np.array([mp[s] for s in y_str], dtype=int)
    mp = {u: i for i, u in enumerate(uniq)}
    return np.array([mp[s] for s in y_str], dtype=int)

def expert_specs(seed, final):
    specs = []
    for C in [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]:
        specs.append(('lr_std_' + str(C), LogisticRegression(C=C, max_iter=8000, solver='lbfgs', random_state=seed), 'std'))
    for C in [0.03, 0.1, 0.3, 1.0, 3.0]:
        specs.append(('lr_q_' + str(C), LogisticRegression(C=C, max_iter=8000, solver='lbfgs', random_state=seed), 'quant'))
    for s in [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 'auto']:
        specs.append(('lda_std_' + str(s), LinearDiscriminantAnalysis(solver='lsqr', shrinkage=s), 'std'))
    for s in [0.0, 0.1, 0.2, 0.5, 'auto']:
        specs.append(('lda_q_' + str(s), LinearDiscriminantAnalysis(solver='lsqr', shrinkage=s), 'quant'))
    specs.append(('lda_std_eigen_auto', LinearDiscriminantAnalysis(solver='eigen', shrinkage='auto'), 'std'))
    specs.append(('lda_q_eigen_auto', LinearDiscriminantAnalysis(solver='eigen', shrinkage='auto'), 'quant'))
    n_est = 450 if final else 220
    specs.append(('et1', ExtraTreesClassifier(n_estimators=n_est, max_features='sqrt', random_state=seed, n_jobs=1, bootstrap=False, min_samples_leaf=1), 'raw'))
    specs.append(('et2', ExtraTreesClassifier(n_estimators=n_est, max_features='sqrt', random_state=seed, n_jobs=1, bootstrap=False, min_samples_leaf=2), 'raw'))
    specs.append(('et3', ExtraTreesClassifier(n_estimators=n_est, max_features=0.5, random_state=seed, n_jobs=1, bootstrap=False, min_samples_leaf=1), 'raw'))
    specs.append(('rf1', RandomForestClassifier(n_estimators=n_est, max_features='sqrt', random_state=seed, n_jobs=1, bootstrap=True, min_samples_leaf=1), 'raw'))
    specs.append(('rf2', RandomForestClassifier(n_estimators=n_est, max_features='sqrt', random_state=seed, n_jobs=1, bootstrap=True, min_samples_leaf=2), 'raw'))
    for n in [1, 3, 5, 7, 11, 15]:
        specs.append(('knn_std_' + str(n), KNeighborsClassifier(n_neighbors=n, weights='distance', n_jobs=1), 'std'))
    specs.append(('knn_std_5_manhattan', KNeighborsClassifier(n_neighbors=5, weights='distance', p=1, n_jobs=1), 'std'))
    specs.append(('knn_q_5', KNeighborsClassifier(n_neighbors=5, weights='distance', n_jobs=1), 'quant'))
    specs.append(('knn_q_11', KNeighborsClassifier(n_neighbors=11, weights='distance', n_jobs=1), 'quant'))
    specs.append(('gnb_std', GaussianNB(), 'std'))
    specs.append(('gnb_q', GaussianNB(), 'quant'))
    return specs

def fit_prep(Xtr_imp, kind, seed):
    if kind == 'std':
        sc = StandardScaler()
        sc.fit(Xtr_imp)
        return lambda X: sc.transform(X)
    if kind == 'quant':
        nq = min(1000, max(1, Xtr_imp.shape[0]))
        qt = QuantileTransformer(output_distribution='normal', n_quantiles=nq, random_state=seed)
        qt.fit(Xtr_imp)
        return lambda X: qt.transform(X)
    return lambda X: X

def blend_probs(oof, w, mode):
    if mode == 'linear':
        P = np.tensordot(w, oof, axes=(0, 0))
        P = np.clip(P, 1e-15, 1.0)
        P = P / P.sum(axis=1, keepdims=True)
        return P
    logP = np.tensordot(w, np.log(np.clip(oof, 1e-15, 1.0)), axes=(0, 0))
    logP = logP - np.max(logP, axis=1, keepdims=True)
    P = np.exp(logP)
    P = P / P.sum(axis=1, keepdims=True)
    return P

def optimize_weights(oof, y, K, mode, seed, reg=0.01):
    M = oof.shape[0]
    def obj(w):
        P = blend_probs(oof, w, mode)
        return log_loss(y, P, labels=np.arange(K)) + reg * np.sum(w * w)
    w0 = np.ones(M, dtype=float) / float(M)
    cons = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0},)
    bounds = [(0.0, 1.0)] * M
    res = minimize(obj, w0, method='SLSQP', bounds=bounds, constraints=cons, options={'maxiter': 600, 'ftol': 1e-10, 'disp': False})
    if res.success and np.all(np.isfinite(res.x)):
        w = np.clip(res.x, 0.0, 1.0)
        s = w.sum()
        if s > 0:
            w = w / s
            return w
    best_ll = np.inf
    best_w = w0
    for m in range(M):
        w = np.zeros(M, dtype=float)
        w[m] = 1.0
        P = blend_probs(oof, w, mode)
        ll = log_loss(y, P, labels=np.arange(K))
        if ll < best_ll:
            best_ll = ll
            best_w = w
    return best_w

def tune_post(P_base, y, K):
    best_alpha = 1.0
    best_eps = 0.0
    best_ll = np.inf
    for alpha in [0.4, 0.5, 0.65, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0, 2.5]:
        P_a = np.clip(P_base, 1e-15, 1.0) ** alpha
        P_a = P_a / P_a.sum(axis=1, keepdims=True)
        for eps in [0.0, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2]:
            P = (1.0 - eps) * P_a + eps / float(K)
            P = np.clip(P, 1e-15, 1.0)
            P = P / P.sum(axis=1, keepdims=True)
            ll = log_loss(y, P, labels=np.arange(K))
            if ll < best_ll:
                best_ll = ll
                best_alpha = alpha
                best_eps = eps
    return best_alpha, best_eps, best_ll

def main():
    with open(os.path.join('data', 'protocol.json'), 'r', encoding='utf-8') as f:
        protocol = json.load(f)
    seed = int(protocol.get('seed', 7))
    np.random.seed(seed)
    features = protocol['features']
    output_columns = protocol['output_columns']
    row_id_name = protocol.get('row_id', 'row_id')
    classes = [c for c in output_columns if c != row_id_name]
    K = len(classes)
    class_to_idx = {c: i for i, c in enumerate(classes)}
    train = pd.read_csv(os.path.join('data', protocol.get('training_file', 'train.csv')))
    predict = pd.read_csv(os.path.join('data', protocol.get('prediction_file', 'predict.csv')))
    target_cols = protocol.get('target_columns', ['target'])
    target_col = target_cols[0] if target_cols else 'target'
    if target_col not in train.columns:
        cand = [c for c in train.columns if c not in features and c != row_id_name]
        if cand:
            target_col = cand[0]
        else:
            raise ValueError('target column not found')
    mask = train[target_col].notna()
    train_labelled = train.loc[mask].reset_index(drop=True)
    if len(train_labelled) == 0:
        raise ValueError('no labeled training rows')
    y = map_labels(train_labelled[target_col], classes)
    X = train_labelled.reindex(columns=features).apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
    X_pred = predict.reindex(columns=features).apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
    specs0 = expert_specs(seed, False)
    M = len(specs0)
    _, counts = np.unique(y, return_counts=True)
    min_count = int(counts.min()) if len(counts) > 0 else 0
    n_splits = min(5, min_count) if min_count >= 2 else 0
    best_mode = 'linear'
    best_w = np.ones(M, dtype=float) / float(M)
    best_alpha = 1.0
    best_eps = 0.01
    if n_splits >= 2:
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        oof = np.zeros((M, len(y), K), dtype=float)
        for tr_idx, va_idx in skf.split(X, y):
            imp = SimpleImputer(strategy='median')
            Xtr_imp = imp.fit_transform(X[tr_idx])
            Xva_imp = imp.transform(X[va_idx])
            ytr = y[tr_idx]
            specs = expert_specs(seed, False)
            prep_cache = {}
            for m, (name, est, kind) in enumerate(specs):
                try:
                    if kind not in prep_cache:
                        prep_cache[kind] = fit_prep(Xtr_imp, kind, seed)
                    trans = prep_cache[kind]
                    Xtr_t = trans(Xtr_imp)
                    Xva_t = trans(Xva_imp)
                    est.fit(Xtr_t, ytr)
                    P = align_proba(est, Xva_t, K)
                except Exception:
                    P = np.full((Xva_imp.shape[0], K), 1.0 / K, dtype=float)
                oof[m, va_idx, :] = P
        results = []
        for mode in ['linear', 'log']:
            w = optimize_weights(oof, y, K, mode, seed, reg=0.01)
            P_base = blend_probs(oof, w, mode)
            alpha, eps, ll = tune_post(P_base, y, K)
            results.append((ll, mode, w, alpha, eps))
        results.sort(key=lambda x: x[0])
        best_ll, best_mode, best_w, best_alpha, best_eps = results[0]
    imp = SimpleImputer(strategy='median')
    Xtr_imp = imp.fit_transform(X)
    Xpred_imp = imp.transform(X_pred)
    specs = expert_specs(seed, True)
    final_probs = np.zeros((M, Xpred_imp.shape[0], K), dtype=float)
    prep_cache = {}
    for m, (name, est, kind) in enumerate(specs):
        try:
            if kind not in prep_cache:
                prep_cache[kind] = fit_prep(Xtr_imp, kind, seed)
            trans = prep_cache[kind]
            Xtr_t = trans(Xtr_imp)
            Xpred_t = trans(Xpred_imp)
            est.fit(Xtr_t, y)
            P = align_proba(est, Xpred_t, K)
        except Exception:
            P = np.full((Xpred_imp.shape[0], K), 1.0 / K, dtype=float)
        final_probs[m, :, :] = P
    P = blend_probs(final_probs, best_w, best_mode)
    P = np.clip(P, 1e-15, 1.0) ** best_alpha
    P = P / P.sum(axis=1, keepdims=True)
    P = (1.0 - best_eps) * P + best_eps / float(K)
    P = np.clip(P, 1e-15, 1.0)
    P = P / P.sum(axis=1, keepdims=True)
    if row_id_name in predict.columns:
        rid_values = predict[row_id_name].values
    else:
        rid_values = predict.iloc[:, 0].values
    out = pd.DataFrame({row_id_name: rid_values})
    for c in classes:
        out[c] = P[:, class_to_idx[c]]
    for c in output_columns:
        if c not in out.columns:
            out[c] = 0.0
    out = out[output_columns]
    out.to_csv(protocol.get('output_file', 'predictions.csv'), index=False)

if __name__ == '__main__':
    main()