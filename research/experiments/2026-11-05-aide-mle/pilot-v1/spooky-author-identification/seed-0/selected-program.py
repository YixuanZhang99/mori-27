import json
import os
import random
import warnings
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.naive_bayes import MultinomialNB, ComplementNB
from sklearn.model_selection import StratifiedKFold
try:
    from scipy.optimize import minimize
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False

SEED = 7
warnings.filterwarnings('ignore')

def read_protocol():
    with open(os.path.join('data', 'protocol.json'), 'r', encoding='utf-8') as f:
        return json.load(f)

def get_text(df, features):
    cols = [c for c in features if c in df.columns]
    if not cols:
        for c in ['text', 'excerpt', 'sentence', 'content']:
            if c in df.columns:
                cols = [c]
                break
    if not cols:
        for c in df.columns:
            if df[c].dtype == object:
                cols = [c]
                break
    if not cols:
        raise ValueError('no text column')
    s = df[cols[0]].fillna('').astype(str)
    for c in cols[1:]:
        s = s + ' ' + df[c].fillna('').astype(str)
    return s

def canon(v, prob_cols):
    s = str(v).strip()
    u = s.upper()
    if u in prob_cols:
        return u
    if 'EDGAR' in u or 'ALLAN' in u or 'POE' in u:
        return 'EAP'
    if 'LOVECRAFT' in u or 'H.P' in u or 'H P' in u or 'HOWARD' in u:
        return 'HPL'
    if 'MARY' in u or 'SHELLEY' in u or 'WOLLSTONECRAFT' in u:
        return 'MWS'
    return s

def find_target(train, features, id_col):
    for c in ['target', 'author', 'label', 'class']:
        if c in train.columns:
            return c
    for c in train.columns:
        if c not in features and c != id_col and c != 'id':
            if train[c].dtype == object:
                return c
    raise ValueError('no target column')

def align(model, X, n_classes):
    p = model.predict_proba(X)
    classes = np.asarray(model.classes_).astype(int)
    out = np.zeros((X.shape[0], n_classes), dtype=np.float64)
    for j, cls in enumerate(classes):
        out[:, int(cls)] = p[:, j]
    return out

def main():
    protocol = read_protocol()
    seed = int(protocol.get('seed', SEED))
    random.seed(seed)
    np.random.seed(seed)
    train_file = protocol.get('training_file', 'train.csv')
    predict_file = protocol.get('prediction_file', 'predict.csv')
    output_file = protocol.get('output_file', 'predictions.csv')
    output_cols = protocol.get('output_columns', ['row_id', 'EAP', 'HPL', 'MWS'])
    out_id_col = output_cols[0] if output_cols else 'row_id'
    prob_cols = [c for c in output_cols if c != out_id_col]
    if not prob_cols:
        prob_cols = ['EAP', 'HPL', 'MWS']
    features = protocol.get('features', ['text'])
    train = pd.read_csv(os.path.join('data', train_file))
    predict = pd.read_csv(os.path.join('data', predict_file))
    text_train = get_text(train, features)
    text_predict = get_text(predict, features)
    target_col = find_target(train, features, out_id_col)
    y_raw = train[target_col].astype(str).values
    label_to_idx = {c: i for i, c in enumerate(prob_cols)}
    y = np.array([label_to_idx[canon(v, prob_cols)] for v in y_raw], dtype=int)
    n_classes = len(prob_cols)

    word_vec = TfidfVectorizer(analyzer='word', ngram_range=(1, 2), min_df=1, max_features=150000, sublinear_tf=True, strip_accents='unicode', lowercase=True, dtype=np.float32)
    char_wb_vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 6), min_df=2, max_features=200000, sublinear_tf=True, strip_accents='unicode', lowercase=True, dtype=np.float32)
    char_vec = TfidfVectorizer(analyzer='char', ngram_range=(2, 6), min_df=2, max_features=200000, sublinear_tf=True, strip_accents='unicode', lowercase=True, dtype=np.float32)
    vec = FeatureUnion([('word', word_vec), ('char_wb', char_wb_vec), ('char', char_vec)])
    X_train = vec.fit_transform(text_train)
    X_predict = vec.transform(text_predict)

    def make_models():
        models = {}
        for name, C in [('lr2', 2.0), ('lr6', 6.0), ('lr15', 15.0)]:
            try:
                models[name] = LogisticRegression(C=C, solver='lbfgs', max_iter=1500, random_state=seed, multi_class='multinomial')
            except TypeError:
                models[name] = LogisticRegression(C=C, solver='lbfgs', max_iter=1500, random_state=seed)
        models['mnb'] = MultinomialNB(alpha=0.05)
        models['cnb'] = ComplementNB(alpha=0.3)
        models['sgd'] = SGDClassifier(loss='log_loss', penalty='l2', alpha=2e-6, max_iter=2000, tol=1e-4, random_state=seed)
        return models

    names = ['lr2', 'lr6', 'lr15', 'mnb', 'cnb', 'sgd']
    K = len(names)
    n_splits = 5
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    oof = {name: np.zeros((len(y), n_classes), dtype=np.float64) for name in names}
    for tr_idx, va_idx in skf.split(X_train, y):
        X_tr, X_va = X_train[tr_idx], X_train[va_idx]
        y_tr = y[tr_idx]
        models = make_models()
        for name, model in models.items():
            model.fit(X_tr, y_tr)
            oof[name][va_idx] = align(model, X_va, n_classes)

    def loss(w):
        w = np.maximum(np.asarray(w, dtype=float), 0.0)
        s = w.sum()
        if s <= 0:
            return 1e9
        w = w / s
        blend = np.zeros_like(oof[names[0]])
        for i, name in enumerate(names):
            blend += w[i] * oof[name]
        blend = np.clip(blend, 1e-15, 1.0)
        blend = blend / blend.sum(axis=1, keepdims=True)
        return -np.mean(np.log(blend[np.arange(len(y)), y]))

    if HAS_SCIPY:
        x0 = np.ones(K) / K
        bounds = [(0, 1)] * K
        cons = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        res = minimize(loss, x0, method='SLSQP', bounds=bounds, constraints=cons, options={'maxiter': 2000, 'ftol': 1e-10})
        if res.success:
            weights = np.maximum(res.x, 0)
            weights = weights / weights.sum()
        else:
            weights = np.ones(K) / K
    else:
        weights = np.ones(K) / K

    models = make_models()
    preds = []
    for name in names:
        model = models[name]
        model.fit(X_train, y)
        preds.append(align(model, X_predict, n_classes))

    out_proba = np.zeros((X_predict.shape[0], n_classes), dtype=np.float64)
    for i, p in enumerate(preds):
        out_proba += weights[i] * p
    out_proba = np.clip(out_proba, 1e-7, 1.0)
    out_proba = out_proba / out_proba.sum(axis=1, keepdims=True)

    rid_col = None
    for c in [protocol.get('row_id', 'row_id'), 'row_id', 'id']:
        if c in predict.columns:
            rid_col = c
            break
    if rid_col is None:
        rid_col = predict.columns[0]

    out = pd.DataFrame({out_id_col: predict[rid_col].values})
    for i, c in enumerate(prob_cols):
        out[c] = out_proba[:, i]
    out.to_csv(output_file, index=False)

if __name__ == '__main__':
    main()
