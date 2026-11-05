import json
import random
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.metrics import log_loss

SEED = 7
random.seed(SEED)
np.random.seed(SEED)
warnings.filterwarnings('ignore')

base = Path('.')
with open(base / 'data' / 'protocol.json', 'r', encoding='utf-8') as f:
    protocol = json.load(f)
train = pd.read_csv(base / 'data' / 'train.csv')
predict = pd.read_csv(base / 'data' / 'predict.csv')
row_id_col = protocol.get('row_id', 'row_id')
target_col = protocol.get('target_columns', ['target'])[0]
features = protocol['features']
output_columns = protocol['output_columns']
class_columns = [c for c in output_columns if c != row_id_col]

def block_cols(prefix):
    return [c for c in features if c.startswith(prefix)]

blocks = [block_cols('margin'), block_cols('shape'), block_cols('texture')]

X_train_all = train.reindex(columns=features).apply(pd.to_numeric, errors='coerce').fillna(0.0)
X_predict_all = predict.reindex(columns=features).apply(pd.to_numeric, errors='coerce').fillna(0.0)
y_train = train[target_col].astype(str).values

def prune_correlated(X, cols, threshold=0.995):
    if len(cols) <= 1:
        return list(cols)
    sub = X[cols]
    corr = sub.corr().abs().fillna(0.0)
    keep = []
    for c in cols:
        ok = True
        for k in keep:
            if corr.loc[c, k] > threshold:
                ok = False
                break
        if ok:
            keep.append(c)
    return keep

def fit_preprocess(X, cols_by_block, threshold=0.995):
    selected = []
    scalers = []
    for cols in cols_by_block:
        keep = prune_correlated(X, cols, threshold)
        selected.append(keep)
        scaler = StandardScaler()
        if keep:
            scaler.fit(X[keep].to_numpy(dtype=float))
        scalers.append(scaler)
    return selected, scalers

def transform_preprocess(X, selected, scalers):
    parts = []
    for keep, scaler in zip(selected, scalers):
        if keep:
            arr = X[keep].to_numpy(dtype=float)
            parts.append(scaler.transform(arr))
    if not parts:
        return np.zeros((len(X), 0), dtype=float)
    return np.hstack(parts)

C_grid = [0.1, 0.3, 1.0, 3.0]
cv = RepeatedStratifiedKFold(n_splits=2, n_repeats=2, random_state=SEED)
scores = {c: [] for c in C_grid}
for train_idx, val_idx in cv.split(X_train_all, y_train):
    X_tr = X_train_all.iloc[train_idx]
    X_val = X_train_all.iloc[val_idx]
    y_tr = y_train[train_idx]
    y_val = y_train[val_idx]
    selected, scalers = fit_preprocess(X_tr, blocks, threshold=0.995)
    X_tr_t = transform_preprocess(X_tr, selected, scalers)
    X_val_t = transform_preprocess(X_val, selected, scalers)
    for C in C_grid:
        clf = LogisticRegression(C=C, random_state=SEED, solver='lbfgs', max_iter=2000)
        clf.fit(X_tr_t, y_tr)
        proba = clf.predict_proba(X_val_t)
        try:
            loss = log_loss(y_val, proba, labels=clf.classes_)
            scores[C].append(-loss)
        except Exception:
            scores[C].append(-1e9)

best_C = 1.0
best_score = -np.inf
for C, vals in scores.items():
    if vals:
        mean_score = float(np.mean(vals))
        if mean_score > best_score:
            best_score = mean_score
            best_C = C

selected, scalers = fit_preprocess(X_train_all, blocks, threshold=0.995)
X_train = transform_preprocess(X_train_all, selected, scalers)
X_predict = transform_preprocess(X_predict_all, selected, scalers)

model = LogisticRegression(C=best_C, random_state=SEED, solver='lbfgs', max_iter=5000)
model.fit(X_train, y_train)
proba = model.predict_proba(X_predict)
classes = model.classes_
prob_df = pd.DataFrame(proba, columns=[str(c) for c in classes])
for c in class_columns:
    if c not in prob_df.columns:
        prob_df[c] = 0.0
prob_df = prob_df[class_columns]
vals = prob_df.to_numpy(dtype=float)
vals = np.clip(vals, 0.0, 1.0)
row_sums = vals.sum(axis=1)
bad = row_sums <= 0
if np.any(bad):
    vals[bad, :] = 1.0 / vals.shape[1]
    row_sums = vals.sum(axis=1)
vals = vals / row_sums[:, None]
out = pd.DataFrame(vals, columns=class_columns)
out.insert(0, row_id_col, predict[row_id_col].values)
out.to_csv(base / 'predictions.csv', index=False)