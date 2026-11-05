import os
import json
import random
import warnings
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, LabelEncoder, QuantileTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
from sklearn.model_selection import StratifiedKFold
from scipy.optimize import minimize, minimize_scalar

warnings.filterwarnings('ignore')
SEED = 7
random.seed(SEED)
np.random.seed(SEED)

with open(os.path.join('data', 'protocol.json'), 'r') as f:
    protocol = json.load(f)

features = protocol['features']
target_col = protocol['target_columns'][0]
row_id_col = protocol.get('row_id', 'row_id')
out_cols = protocol['output_columns']
class_names_out = out_cols[1:]

train = pd.read_csv(os.path.join('data', 'train.csv'))
pred = pd.read_csv(os.path.join('data', 'predict.csv'))

X_raw = train[features].astype(float).values
X_pred_raw = pred[features].astype(float).values
y_str = train[target_col].astype(str).values

le = LabelEncoder()
y = le.fit_transform(y_str)
model_class_names = list(le.classes_)
n_classes = len(model_class_names)

blocks = []
for prefix in ['margin', 'shape', 'texture']:
    idx = [i for i, name in enumerate(features) if name.startswith(prefix)]
    if len(idx) > 0:
        blocks.append(idx)

def prepare_fit_transform(X_tr, X_others):
    imputer = SimpleImputer(strategy='median')
    Xtr_i = imputer.fit_transform(X_tr)
    Xothers_i = [imputer.transform(X) for X in X_others]
    out = {}
    out['raw'] = (Xtr_i, Xothers_i)
    sc = StandardScaler()
    Xtr_s = sc.fit_transform(Xtr_i)
    Xothers_s = [sc.transform(Xo) for Xo in Xothers_i]
    out['std'] = (Xtr_s, Xothers_s)
    Xtr_b = Xtr_i.copy()
    Xothers_b = [Xo.copy() for Xo in Xothers_i]
    for idx in blocks:
        scb = StandardScaler()
        Xtr_b[:, idx] = scb.fit_transform(Xtr_i[:, idx])
        for j in range(len(Xothers_b)):
            Xothers_b[j][:, idx] = scb.transform(Xothers_i[j][:, idx])
    out['block'] = (Xtr_b, Xothers_b)
    nq = min(1000, Xtr_i.shape[0])
    qt = QuantileTransformer(n_quantiles=nq, output_distribution='normal', random_state=SEED, subsample=100000)
    Xtr_q = qt.fit_transform(Xtr_i)
    Xothers_q = [qt.transform(Xo) for Xo in Xothers_i]
    out['quant'] = (Xtr_q, Xothers_q)
    return out

def make_models():
    specs = []
    specs.append(('lr03', 'std', 'proba', lambda: LogisticRegression(C=0.3, solver='lbfgs', max_iter=5000, random_state=SEED)))
    specs.append(('lr1', 'std', 'proba', lambda: LogisticRegression(C=1.0, solver='lbfgs', max_iter=5000, random_state=SEED)))
    specs.append(('lr3', 'std', 'proba', lambda: LogisticRegression(C=3.0, solver='lbfgs', max_iter=5000, random_state=SEED)))
    specs.append(('lr10', 'std', 'proba', lambda: LogisticRegression(C=10.0, solver='lbfgs', max_iter=5000, random_state=SEED)))
    specs.append(('lr1b', 'block', 'proba', lambda: LogisticRegression(C=1.0, solver='lbfgs', max_iter=5000, random_state=SEED)))
    specs.append(('lr3b', 'block', 'proba', lambda: LogisticRegression(C=3.0, solver='lbfgs', max_iter=5000, random_state=SEED)))
    specs.append(('lda', 'std', 'proba', lambda: LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto')))
    specs.append(('ldab', 'block', 'proba', lambda: LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto')))
    specs.append(('rf', 'raw', 'proba', lambda: RandomForestClassifier(n_estimators=800, max_features='sqrt', random_state=SEED, n_jobs=-1)))
    specs.append(('et', 'raw', 'proba', lambda: ExtraTreesClassifier(n_estimators=1000, max_features='sqrt', random_state=SEED, n_jobs=-1)))
    specs.append(('knn1', 'std', 'proba', lambda: KNeighborsClassifier(n_neighbors=1, weights='distance', metric='euclidean', n_jobs=-1)))
    specs.append(('knn3', 'std', 'proba', lambda: KNeighborsClassifier(n_neighbors=3, weights='distance', metric='euclidean', n_jobs=-1)))
    specs.append(('knn5', 'std', 'proba', lambda: KNeighborsClassifier(n_neighbors=5, weights='distance', metric='euclidean', n_jobs=-1)))
    specs.append(('knn9', 'std', 'proba', lambda: KNeighborsClassifier(n_neighbors=9, weights='distance', metric='euclidean', n_jobs=-1)))
    specs.append(('knn5b', 'block', 'proba', lambda: KNeighborsClassifier(n_neighbors=5, weights='distance', metric='euclidean', n_jobs=-1)))
    specs.append(('knn5q', 'quant', 'proba', lambda: KNeighborsClassifier(n_neighbors=5, weights='distance', metric='euclidean', n_jobs=-1)))
    specs.append(('gnb', 'std', 'proba', lambda: GaussianNB()))
    specs.append(('svc10', 'std', 'decision', lambda: SVC(C=10.0, kernel='rbf', gamma='scale', decision_function_shape='ovr', random_state=SEED)))
    specs.append(('svc10b', 'block', 'decision', lambda: SVC(C=10.0, kernel='rbf', gamma='scale', decision_function_shape='ovr', random_state=SEED)))
    specs.append(('mlp', 'std', 'proba', lambda: MLPClassifier(hidden_layer_sizes=(256,), alpha=0.001, batch_size=64, learning_rate_init=0.001, max_iter=600, early_stopping=False, random_state=SEED)))
    return specs

def get_proba(model, X, kind):
    if kind == 'proba':
        p = model.predict_proba(X)
    else:
        d = model.decision_function(X)
        if d.ndim == 1:
            d = np.vstack([-d, d]).T
        d = d - d.max(axis=1, keepdims=True)
        e = np.exp(d)
        p = e / e.sum(axis=1, keepdims=True)
    p = np.clip(p, 1e-15, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    return p

specs = make_models()
n_models = len(specs)
oof = np.zeros((n_models, len(y), n_classes), dtype=float)
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)

for tr_idx, va_idx in skf.split(X_raw, y):
    X_tr_raw = X_raw[tr_idx]
    X_va_raw = X_raw[va_idx]
    y_tr = y[tr_idx]
    prep = prepare_fit_transform(X_tr_raw, [X_va_raw])
    for mi, (name, family, kind, builder) in enumerate(specs):
        Xt, others = prep[family]
        Xv = others[0]
        model = builder()
        model.fit(Xt, y_tr)
        p = get_proba(model, Xv, kind)
        full = np.zeros((len(va_idx), n_classes))
        for j, c in enumerate(model.classes_):
            full[:, int(c)] = p[:, j]
        oof[mi, va_idx, :] = full

def obj(w):
    w = np.maximum(w, 0.0)
    s = w.sum()
    if s <= 0:
        return 1e12
    w = w / s
    p = np.tensordot(w, oof, axes=(0, 0))
    p = np.clip(p, 1e-15, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    return -np.mean(np.log(p[np.arange(len(y)), y]))

w0 = np.ones(n_models) / n_models
bounds = [(0.0, 1.0)] * n_models
cons = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0},)

single_vals = []
for i in range(n_models):
    wi = np.zeros(n_models)
    wi[i] = 1.0
    single_vals.append(obj(wi))
best_single = int(np.argmin(single_vals))
w_start_best = np.zeros(n_models)
w_start_best[best_single] = 1.0

best_w = w0.copy()
best_val = obj(w0)
start_list = [w0, w_start_best]
for trial in range(8):
    start_list.append(np.random.dirichlet(np.ones(n_models)))
for w_start in start_list:
    try:
        res = minimize(obj, w_start, method='SLSQP', bounds=bounds, constraints=cons, options={'maxiter': 1000, 'ftol': 1e-10, 'disp': False})
        if res.success:
            ww = np.maximum(res.x, 0.0)
            if ww.sum() > 0:
                ww = ww / ww.sum()
                val = obj(ww)
                if val < best_val:
                    best_val = val
                    best_w = ww
    except Exception:
        pass
weights = best_w
print('weights', weights)

p_oof = np.tensordot(weights, oof, axes=(0, 0))
p_oof = np.clip(p_oof, 1e-15, 1.0)
p_oof = p_oof / p_oof.sum(axis=1, keepdims=True)
logp_oof = np.log(p_oof)

def nll_alpha(alpha):
    z = alpha * logp_oof
    z = z - z.max(axis=1, keepdims=True)
    lse = np.log(np.exp(z).sum(axis=1, keepdims=True))
    logp_cal = z - lse
    return -np.mean(logp_cal[np.arange(len(y)), y])

best_alpha = 1.0
best_alpha_val = nll_alpha(1.0)
for a in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
    v = nll_alpha(a)
    if v < best_alpha_val:
        best_alpha_val = v
        best_alpha = a
try:
    res = minimize_scalar(nll_alpha, bounds=(0.25, 4.0), method='bounded', options={'xatol': 1e-5})
    if res.success and res.fun < best_alpha_val:
        best_alpha = float(res.x)
        best_alpha_val = float(res.fun)
except Exception:
    pass
print('alpha', best_alpha, 'oof_nll', best_alpha_val)

prep_final = prepare_fit_transform(X_raw, [X_pred_raw])
pred_probas = []
for mi, (name, family, kind, builder) in enumerate(specs):
    Xt, others = prep_final[family]
    Xp = others[0]
    model = builder()
    model.fit(Xt, y)
    p = get_proba(model, Xp, kind)
    full = np.zeros((len(pred), n_classes))
    for j, c in enumerate(model.classes_):
        full[:, int(c)] = p[:, j]
    pred_probas.append(full)

pred_probas = np.array(pred_probas)
pred_model = np.tensordot(weights, pred_probas, axes=(0, 0))
pred_model = np.clip(pred_model, 1e-15, 1.0)
pred_model = pred_model / pred_model.sum(axis=1, keepdims=True)
logp_pred = np.log(pred_model)
z = best_alpha * logp_pred
z = z - z.max(axis=1, keepdims=True)
e = np.exp(z)
pred_model = e / e.sum(axis=1, keepdims=True)
pred_model = np.clip(pred_model, 1e-15, 1.0)
pred_model = pred_model / pred_model.sum(axis=1, keepdims=True)

out_map = {name: i for i, name in enumerate(class_names_out)}
pred_out = np.full((len(pred), len(class_names_out)), 1e-12)
for j, name in enumerate(model_class_names):
    if name in out_map:
        pred_out[:, out_map[name]] = pred_model[:, j]
pred_out = np.clip(pred_out, 1e-15, 1.0)
pred_out = pred_out / pred_out.sum(axis=1, keepdims=True)

df = pd.DataFrame(pred_out, columns=class_names_out)
df.insert(0, row_id_col, pred[row_id_col].values)
df.to_csv('predictions.csv', index=False)
print('wrote predictions.csv', df.shape)
