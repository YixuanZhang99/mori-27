import os, json, random, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.naive_bayes import MultinomialNB, ComplementNB
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss

def normalize(arr):
    arr = np.asarray(arr, dtype=float)
    arr = np.clip(arr, 1e-15, 1.0)
    s = arr.sum(axis=1, keepdims=True)
    s[s == 0] = 1.0
    return arr / s

def align_probs(probs, classes, out_cols):
    df = pd.DataFrame(probs, columns=list(classes))
    df = df.reindex(columns=out_cols, fill_value=0.0)
    return normalize(df.values)

def make_vectorizers(X):
    vecs = {}
    vecs['w12'] = TfidfVectorizer(analyzer='word', ngram_range=(1,2), min_df=2, max_df=0.9, sublinear_tf=True, strip_accents='unicode', dtype=np.float32)
    vecs['w13'] = TfidfVectorizer(analyzer='word', ngram_range=(1,3), min_df=3, max_df=0.9, sublinear_tf=True, strip_accents='unicode', dtype=np.float32)
    vecs['c25'] = TfidfVectorizer(analyzer='char_wb', ngram_range=(2,5), min_df=2, max_df=0.95, sublinear_tf=True, strip_accents='unicode', dtype=np.float32)
    vecs['c26'] = TfidfVectorizer(analyzer='char_wb', ngram_range=(2,6), min_df=3, max_df=0.95, sublinear_tf=True, strip_accents='unicode', dtype=np.float32)
    vecs['c35'] = TfidfVectorizer(analyzer='char', ngram_range=(3,5), min_df=2, max_df=1.0, sublinear_tf=True, strip_accents='unicode', dtype=np.float32)
    vecs['cnt12'] = CountVectorizer(analyzer='word', ngram_range=(1,2), min_df=2, max_df=0.95, strip_accents='unicode', dtype=np.float32)
    vecs['cnt13'] = CountVectorizer(analyzer='word', ngram_range=(1,3), min_df=3, max_df=0.95, strip_accents='unicode', dtype=np.float32)
    vecs['bin12'] = CountVectorizer(analyzer='word', ngram_range=(1,2), min_df=2, max_df=0.95, binary=True, strip_accents='unicode', dtype=np.float32)
    for v in vecs.values():
        v.fit(X)
    return vecs

def transform_key(vecs, key, X):
    parts = []
    for k in key.split('+'):
        parts.append(vecs[k].transform(X))
    if len(parts) == 1:
        return parts[0].astype(np.float32)
    return sp.hstack(parts, format='csr', dtype=np.float32)

def fit_predict(typ, param, Xtr, ytr, Xva, seed):
    if typ == 'lr':
        clf = LogisticRegression(C=float(param), solver='lbfgs', max_iter=2000, tol=1e-3, random_state=seed)
    elif typ == 'mnb':
        clf = MultinomialNB(alpha=float(param))
    elif typ == 'cnb':
        clf = ComplementNB(alpha=float(param))
    elif typ == 'sgd':
        clf = SGDClassifier(loss='log_loss', alpha=float(param), max_iter=2000, tol=1e-4, random_state=seed, learning_rate='optimal')
    else:
        raise ValueError(typ)
    clf.fit(Xtr, ytr)
    return clf, clf.predict_proba(Xva)

def greedy_weights(oof, y, out_cols):
    n_models = len(oof)
    scores = []
    for p in oof:
        scores.append(log_loss(y, p, labels=out_cols))
    best_i = int(np.argmin(scores))
    blend = oof[best_i].copy()
    counts = np.zeros(n_models, dtype=float)
    counts[best_i] = 1.0
    best_score = scores[best_i]
    total = 1.0
    for _ in range(120):
        current_best = best_score
        chosen = -1
        for m in range(n_models):
            cand = (blend * total + oof[m]) / (total + 1.0)
            cand = normalize(cand)
            sc = log_loss(y, cand, labels=out_cols)
            if sc < current_best - 1e-9:
                current_best = sc
                chosen = m
        if chosen < 0:
            break
        counts[chosen] += 1.0
        blend = (blend * total + oof[chosen]) / (total + 1.0)
        blend = normalize(blend)
        total += 1.0
        best_score = current_best
    if counts.sum() == 0:
        counts[best_i] = 1.0
    return counts / counts.sum()

def main():
    with open(os.path.join('data','protocol.json'),'r',encoding='utf-8') as f:
        protocol = json.load(f)
    seed = int(protocol.get('seed', 7))
    random.seed(seed)
    np.random.seed(seed)

    train_path = os.path.join('data', protocol.get('training_file','train.csv'))
    pred_path = os.path.join('data', protocol.get('prediction_file','predict.csv'))
    out_path = protocol.get('output_file','predictions.csv')
    train = pd.read_csv(train_path)
    pred = pd.read_csv(pred_path)

    features = protocol.get('features', ['text'])
    text_col = None
    for c in features:
        if c in train.columns:
            text_col = c
            break
    if text_col is None:
        text_col = 'text' if 'text' in train.columns else [c for c in train.columns if c not in protocol.get('target_columns', [])][0]
    tgt_cols = protocol.get('target_columns', ['target'])
    target_col = tgt_cols[0]
    row_col = protocol.get('row_id','row_id')
    all_out_cols = protocol.get('output_columns', [row_col,'EAP','HPL','MWS'])
    out_cols = [c for c in all_out_cols if c != row_col]

    X_train = train[text_col].fillna('').astype(str).values
    y_train = train[target_col].values
    X_pred = pred[text_col].fillna('').astype(str).values

    model_specs = [
        ('lr', 0.3, 'w12+c25'),
        ('lr', 0.5, 'w12+c25'),
        ('lr', 1.0, 'w12+c25'),
        ('lr', 2.0, 'w12+c25'),
        ('lr', 4.0, 'w12+c25'),
        ('lr', 8.0, 'w12+c25'),
        ('lr', 0.7, 'w13+c26'),
        ('lr', 1.5, 'w13+c26'),
        ('lr', 2.0, 'w12+c26'),
        ('lr', 1.0, 'w12+c35'),
        ('lr', 2.0, 'w12'),
        ('lr', 2.0, 'c25'),
        ('mnb', 0.03, 'cnt12'),
        ('mnb', 0.08, 'cnt12'),
        ('mnb', 0.15, 'cnt12'),
        ('mnb', 0.30, 'cnt12'),
        ('mnb', 0.05, 'cnt13'),
        ('mnb', 0.12, 'bin12'),
        ('mnb', 0.04, 'w12'),
        ('cnb', 0.15, 'w12+c25'),
        ('cnb', 0.35, 'w12+c25'),
        ('cnb', 0.25, 'cnt12'),
        ('cnb', 0.50, 'w13+c26'),
        ('sgd', 1e-6, 'w12+c25'),
        ('sgd', 1e-5, 'w12+c25'),
        ('sgd', 1e-4, 'w12+c25'),
        ('sgd', 3e-5, 'w13+c26'),
    ]

    n_models = len(model_specs)
    unique_keys = sorted(set(spec[2] for spec in model_specs))
    can_cv = len(train) >= 300 and pd.Series(y_train).value_counts().min() >= 5
    weights = None
    if can_cv:
        oof = [np.zeros((len(X_train), len(out_cols)), dtype=float) for _ in range(n_models)]
        skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=seed)
        for tr_idx, va_idx in skf.split(X_train, y_train):
            X_tr = X_train[tr_idx]
            y_tr = y_train[tr_idx]
            X_va = X_train[va_idx]
            vecs = make_vectorizers(X_tr)
            tr_mats = {k: transform_key(vecs, k, X_tr) for k in unique_keys}
            va_mats = {k: transform_key(vecs, k, X_va) for k in unique_keys}
            for i, (typ, param, key) in enumerate(model_specs):
                try:
                    clf, probs = fit_predict(typ, param, tr_mats[key], y_tr, va_mats[key], seed)
                    oof[i][va_idx] = align_probs(probs, clf.classes_, out_cols)
                except Exception:
                    oof[i][va_idx] = np.full((len(va_idx), len(out_cols)), 1.0 / len(out_cols))
        weights = greedy_weights(oof, y_train, out_cols)
    if weights is None or weights.sum() <= 0:
        weights = np.zeros(n_models, dtype=float)
        best_idx = 3
        for i, spec in enumerate(model_specs):
            if spec[0] == 'lr' and abs(spec[1] - 2.0) < 1e-12 and spec[2] == 'w12+c25':
                best_idx = i
                break
        weights[best_idx] = 1.0

    vecs = make_vectorizers(X_train)
    tr_mats = {k: transform_key(vecs, k, X_train) for k in unique_keys}
    pred_mats = {k: transform_key(vecs, k, X_pred) for k in unique_keys}
    probs = np.zeros((len(X_pred), len(out_cols)), dtype=float)
    for i, (typ, param, key) in enumerate(model_specs):
        w = weights[i]
        if w <= 0:
            continue
        try:
            clf, p = fit_predict(typ, param, tr_mats[key], y_train, pred_mats[key], seed)
            probs += w * align_probs(p, clf.classes_, out_cols)
        except Exception:
            pass
    if probs.sum() <= 0:
        probs = np.full((len(X_pred), len(out_cols)), 1.0 / len(out_cols))
    probs = normalize(probs)

    out = pd.DataFrame()
    out[row_col] = pred[row_col].values
    for i, c in enumerate(out_cols):
        out[c] = probs[:, i]
    out = out[all_out_cols]
    out.to_csv(out_path, index=False)

if __name__ == '__main__':
    main()