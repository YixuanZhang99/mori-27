import os, json, warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss
from sklearn.base import clone
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.neighbors import KNeighborsClassifier
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

def align_proba(model, X, n_classes):
    proba = model.predict_proba(X)
    out = np.zeros((proba.shape[0], n_classes), dtype=np.float64)
    for j, cls in enumerate(model.classes_):
        try:
            idx = int(cls)
        except Exception:
            idx = j
        if 0 <= idx < n_classes:
            out[:, idx] += proba[:, j]
    s = out.sum(axis=1, keepdims=True)
    bad = s[:, 0] <= 0
    if np.any(bad):
        out[bad] = 1.0 / float(n_classes)
    else:
        out = out / s
    return out

def smooth_probs(p, alpha, n_classes):
    p = np.nan_to_num(p, nan=1.0 / float(n_classes), posinf=0.0, neginf=0.0)
    p = np.maximum(p, 0.0)
    p = (p + alpha) / (1.0 + float(n_classes) * alpha)
    s = p.sum(axis=1, keepdims=True)
    bad = s[:, 0] <= 0
    if np.any(bad):
        p[bad] = 1.0 / float(n_classes)
    else:
        p = p / s
    return p

def apply_temp(p, t):
    p = np.nan_to_num(p, nan=1.0 / float(p.shape[1]), posinf=0.0, neginf=0.0)
    p = np.maximum(p, 0.0)
    if abs(t - 1.0) < 1e-12:
        return p
    q = np.power(np.maximum(p, 1e-300), 1.0 / t)
    s = q.sum(axis=1, keepdims=True)
    bad = s[:, 0] <= 0
    if np.any(bad):
        q[bad] = 1.0 / float(p.shape[1])
    else:
        q = q / s
    return q

def make_models(n_estimators, seed):
    return [
        ('et_gini', ExtraTreesClassifier(n_estimators=n_estimators, criterion='gini', max_features='sqrt', min_samples_leaf=1, random_state=seed, n_jobs=-1)),
        ('et_entropy', ExtraTreesClassifier(n_estimators=n_estimators, criterion='entropy', max_features='sqrt', min_samples_leaf=1, random_state=seed + 1, n_jobs=-1)),
        ('et_half', ExtraTreesClassifier(n_estimators=n_estimators, criterion='gini', max_features=0.5, min_samples_leaf=1, random_state=seed + 2, n_jobs=-1)),
        ('et_leaf2', ExtraTreesClassifier(n_estimators=n_estimators, criterion='gini', max_features='sqrt', min_samples_leaf=2, random_state=seed + 3, n_jobs=-1)),
        ('rf_gini', RandomForestClassifier(n_estimators=n_estimators, criterion='gini', max_features='sqrt', min_samples_leaf=1, random_state=seed + 4, n_jobs=-1)),
        ('rf_entropy', RandomForestClassifier(n_estimators=n_estimators, criterion='entropy', max_features='sqrt', min_samples_leaf=1, random_state=seed + 5, n_jobs=-1)),
        ('rf_half', RandomForestClassifier(n_estimators=n_estimators, criterion='gini', max_features=0.5, min_samples_leaf=1, random_state=seed + 6, n_jobs=-1)),
        ('rf_leaf2', RandomForestClassifier(n_estimators=n_estimators, criterion='gini', max_features='sqrt', min_samples_leaf=2, random_state=seed + 7, n_jobs=-1)),
        ('lr_01', make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=5000, solver='lbfgs', random_state=seed + 8))),
        ('lr_05', make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=5000, solver='lbfgs', random_state=seed + 9))),
        ('lr_20', make_pipeline(StandardScaler(), LogisticRegression(C=2.0, max_iter=5000, solver='lbfgs', random_state=seed + 10))),
        ('lda', make_pipeline(StandardScaler(), LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto'))),
        ('knn5', make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=5, weights='distance', n_jobs=-1))),
        ('knn11', make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=11, weights='distance', n_jobs=-1)))
    ]

def main():
    with open(os.path.join('data', 'protocol.json'), 'r') as f:
        protocol = json.load(f)
    features = list(protocol['features'])
    out_cols = list(protocol['output_columns'])
    row_out_col = out_cols[0]
    class_names = out_cols[1:]
    n_classes = len(class_names)
    row_id_col = protocol.get('row_id', row_out_col)
    target_cols = protocol.get('target_columns', ['target'])
    target_col = target_cols[0]
    seed = int(protocol.get('seed', 7))
    np.random.seed(seed)

    train = pd.read_csv(os.path.join('data', 'train.csv'))
    pred = pd.read_csv(os.path.join('data', 'predict.csv'))

    for c in features:
        if c not in train.columns:
            train[c] = 0.0
        if c not in pred.columns:
            pred[c] = 0.0

    if row_id_col not in pred.columns:
        for c in ['row_id', 'id', 'Id']:
            if c in pred.columns:
                row_id_col = c
                break
    if target_col not in train.columns:
        for c in ['target', 'species', 'label']:
            if c in train.columns:
                target_col = c
                break

    X = train[features].astype(float).values
    Xp = pred[features].astype(float).values
    X[~np.isfinite(X)] = np.nan
    Xp[~np.isfinite(Xp)] = np.nan
    med = np.nanmedian(X, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    inds = np.where(np.isnan(X))
    if len(inds[0]) > 0:
        X[inds] = med[inds[1]]
    inds = np.where(np.isnan(Xp))
    if len(inds[0]) > 0:
        Xp[inds] = med[inds[1]]

    y_raw = train[target_col].values
    class_to_idx = {str(v).strip(): i for i, v in enumerate(class_names)}
    y_list = []
    for v in y_raw:
        key = str(v).strip()
        if key in class_to_idx:
            y_list.append(class_to_idx[key])
        else:
            try:
                iv = int(v)
                y_list.append(iv if 0 <= iv < n_classes else 0)
            except Exception:
                y_list.append(0)
    y = np.asarray(y_list, dtype=np.int64)

    cv_models = make_models(600, seed)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    oof_list = []
    for name, model in cv_models:
        oof = np.zeros((X.shape[0], n_classes), dtype=np.float64)
        for tr_idx, va_idx in skf.split(X, y):
            m = clone(model)
            m.fit(X[tr_idx], y[tr_idx])
            oof[va_idx] = align_proba(m, X[va_idx], n_classes)
        oof_list.append(oof)

    oof_stack = np.stack(oof_list, axis=0)
    m_models = len(oof_list)

    def normalize_w(w):
        w = np.asarray(w, dtype=np.float64)
        w = np.maximum(w, 0.0)
        sw = w.sum()
        if sw <= 0:
            return np.ones(m_models, dtype=np.float64) / float(m_models)
        return w / sw

    def blend(w):
        return np.tensordot(w, oof_stack, axes=(0, 0))

    def score(w, alpha, temp):
        p = blend(w)
        p = apply_temp(p, temp)
        p = smooth_probs(p, alpha, n_classes)
        return log_loss(y, p, labels=np.arange(n_classes))

    def objective(w, alpha, temp):
        wn = normalize_w(w)
        val = score(wn, alpha, temp)
        val += 1e-4 * np.sum((wn - 1.0 / float(m_models)) ** 2)
        return val

    alphas = [0.0, 1e-6, 1e-5, 1e-4, 1e-3, 5e-3, 1e-2, 5e-2, 1e-1]
    temps = [0.7, 0.85, 1.0, 1.15, 1.3, 1.5]
    bounds = [(0.0, 1.0)] * m_models
    cons = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}
    x0 = np.ones(m_models, dtype=np.float64) / float(m_models)

    best_ll = np.inf
    best_w = x0.copy()
    best_alpha = 0.0
    best_temp = 1.0

    for temp in temps:
        for alpha in alphas:
            try:
                res = minimize(lambda w: objective(w, alpha, temp), x0, method='SLSQP', bounds=bounds, constraints=cons, options={'maxiter': 300, 'ftol': 1e-8, 'disp': False})
                w = normalize_w(res.x)
            except Exception:
                w = x0.copy()
            ll = score(w, alpha, temp)
            if ll < best_ll:
                best_ll = ll
                best_w = w
                best_alpha = alpha
                best_temp = temp

    final_models = make_models(2200, seed)
    final_probas = []
    for name, model in final_models:
        model.fit(X, y)
        p = align_proba(model, Xp, n_classes)
        final_probas.append(p)

    final_stack = np.stack(final_probas, axis=0)
    p_final = np.tensordot(best_w, final_stack, axes=(0, 0))
    p_final = apply_temp(p_final, best_temp)
    p_final = smooth_probs(p_final, best_alpha, n_classes)
    p_final = np.nan_to_num(p_final, nan=1.0 / float(n_classes), posinf=0.0, neginf=0.0)
    p_final = np.maximum(p_final, 0.0)
    s = p_final.sum(axis=1, keepdims=True)
    bad = s[:, 0] <= 0
    if np.any(bad):
        p_final[bad] = 1.0 / float(n_classes)
    else:
        p_final = p_final / s

    out_df = pd.DataFrame(p_final, columns=class_names)
    if row_id_col in pred.columns:
        row_ids = pred[row_id_col].values
    else:
        row_ids = pred.iloc[:, 0].values
    out_df.insert(0, row_out_col, row_ids)
    out_df = out_df[out_cols]
    out_df.to_csv('predictions.csv', index=False)

if __name__ == '__main__':
    main()