import json
import os
import warnings
import numpy as np
import pandas as pd
from sklearn.model_selection import RepeatedKFold
from sklearn.ensemble import HistGradientBoostingRegressor, ExtraTreesRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer

warnings.filterwarnings('ignore')
SEED = 7
np.random.seed(SEED)

with open(os.path.join('data', 'protocol.json'), 'r') as f:
    protocol = json.load(f)

train = pd.read_csv(os.path.join('data', protocol.get('training_file', 'train.csv')))
predict = pd.read_csv(os.path.join('data', protocol.get('prediction_file', 'predict.csv')))
features = protocol['features']
targets = protocol['target_columns']
row_id = protocol.get('row_id', 'row_id')

for df in (train, predict):
    for c in features:
        if c not in df.columns:
            df[c] = np.nan

def add_features(df):
    out = pd.DataFrame(index=df.index)
    for c in features:
        if c == 'spacegroup':
            out[c] = df[c]
        else:
            out[c] = pd.to_numeric(df[c], errors='coerce')
    def getcol(name, default=0.0):
        if name in out.columns:
            return pd.to_numeric(out[name], errors='coerce').to_numpy(dtype=float)
        return np.full(len(out), default, dtype=float)
    a = getcol('lattice_vector_1_ang', 1.0)
    b = getcol('lattice_vector_2_ang', 1.0)
    c = getcol('lattice_vector_3_ang', 1.0)
    alpha = getcol('lattice_angle_alpha_degree', 90.0)
    beta = getcol('lattice_angle_beta_degree', 90.0)
    gamma = getcol('lattice_angle_gamma_degree', 90.0)
    total = getcol('number_of_total_atoms', 0.0)
    al = getcol('percent_atom_al', 0.0)
    ga = getcol('percent_atom_ga', 0.0)
    ind = getcol('percent_atom_in', 0.0)
    ar = np.deg2rad(alpha)
    br = np.deg2rad(beta)
    gr = np.deg2rad(gamma)
    cos_a = np.cos(ar)
    cos_b = np.cos(br)
    cos_g = np.cos(gr)
    val = 1.0 - cos_a**2 - cos_b**2 - cos_g**2 + 2.0 * cos_a * cos_b * cos_g
    val = np.where(np.isfinite(val), val, 0.0)
    volume = a * b * c * np.sqrt(np.maximum(val, 1e-9))
    out['eng_volume'] = volume
    out['eng_abc_sum'] = a + b + c
    out['eng_abc_prod'] = a * b * c
    out['eng_ab_ratio'] = a / (b + 1e-6)
    out['eng_bc_ratio'] = b / (c + 1e-6)
    out['eng_ca_ratio'] = c / (a + 1e-6)
    out['eng_atom_sum'] = al + ga + ind
    out['eng_atom_missing'] = 100.0 - (al + ga + ind)
    out['eng_atom_al_ga'] = al * ga
    out['eng_atom_al_in'] = al * ind
    out['eng_atom_ga_in'] = ga * ind
    out['eng_total_per_volume'] = total / (volume + 1e-6)
    out['eng_volume_per_atom'] = volume / (total + 1e-6)
    out['eng_atom_al_per_total'] = al / (total + 1e-6)
    out['eng_atom_ga_per_total'] = ga / (total + 1e-6)
    out['eng_atom_in_per_total'] = ind / (total + 1e-6)
    for pname, pval in [('al', al), ('ga', ga), ('in', ind)]:
        out['eng_' + pname + '_vol'] = pval * volume / 100.0
        out['eng_' + pname + '_a'] = pval * a / 100.0
        out['eng_' + pname + '_b'] = pval * b / 100.0
        out['eng_' + pname + '_c'] = pval * c / 100.0
        out['eng_' + pname + '_sumabc'] = pval * (a + b + c) / 100.0
    out['eng_angle_sum'] = alpha + beta + gamma
    out['eng_angle_dev'] = abs(alpha - 90.0) + abs(beta - 90.0) + abs(gamma - 90.0)
    out['eng_total_angle_dev'] = total * out['eng_angle_dev'].to_numpy()
    out['eng_vol_angle_dev'] = volume * out['eng_angle_dev'].to_numpy()
    out = out.replace([np.inf, -np.inf], np.nan)
    return out

Xtr_eng = add_features(train)
Xte_eng = add_features(predict)
cat_features = ['spacegroup'] if 'spacegroup' in Xtr_eng.columns else []
num_features = [c for c in Xtr_eng.columns if c not in cat_features]

def make_onehot():
    try:
        return OneHotEncoder(handle_unknown='ignore', sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown='ignore', sparse=False)

def build_preprocessor(scale_numeric):
    transformers = []
    if cat_features:
        cat_pipe = Pipeline([
            ('imputer', SimpleImputer(strategy='most_frequent')),
            ('onehot', make_onehot())
        ])
        transformers.append(('cat', cat_pipe, cat_features))
    if num_features:
        if scale_numeric:
            num_pipe = Pipeline([
                ('imputer', SimpleImputer(strategy='median')),
                ('scaler', StandardScaler())
            ])
        else:
            num_pipe = Pipeline([
                ('imputer', SimpleImputer(strategy='median'))
            ])
        transformers.append(('num', num_pipe, num_features))
    return ColumnTransformer(transformers, remainder='drop')

def make_model(name):
    if name == 'hgb':
        return Pipeline([
            ('pre', build_preprocessor(False)),
            ('model', HistGradientBoostingRegressor(
                loss='squared_error',
                learning_rate=0.05,
                max_iter=300,
                max_leaf_nodes=31,
                l2_regularization=1e-3,
                early_stopping=True,
                validation_fraction=0.15,
                n_iter_no_change=20,
                random_state=SEED
            ))
        ])
    if name == 'et':
        return Pipeline([
            ('pre', build_preprocessor(False)),
            ('model', ExtraTreesRegressor(
                n_estimators=200,
                max_features='sqrt',
                min_samples_leaf=2,
                random_state=SEED,
                n_jobs=-1
            ))
        ])
    if name == 'rf':
        return Pipeline([
            ('pre', build_preprocessor(False)),
            ('model', RandomForestRegressor(
                n_estimators=200,
                max_features='sqrt',
                min_samples_leaf=2,
                random_state=SEED,
                n_jobs=-1
            ))
        ])
    return Pipeline([
        ('pre', build_preprocessor(True)),
        ('model', Ridge(alpha=1.0))
    ])

def oof_predictions(name, X_df, y_log):
    rkf = RepeatedKFold(n_splits=5, n_repeats=2, random_state=SEED)
    oof_sum = np.zeros(len(y_log), dtype=float)
    counts = np.zeros(len(y_log), dtype=float)
    for tr_idx, va_idx in rkf.split(X_df):
        try:
            model = make_model(name)
            model.fit(X_df.iloc[tr_idx], y_log[tr_idx])
            pred = model.predict(X_df.iloc[va_idx])
            pred = np.asarray(pred, dtype=float)
            pred = np.where(np.isfinite(pred), pred, np.nan)
        except Exception:
            pred = np.full(len(va_idx), np.nan, dtype=float)
        oof_sum[va_idx] += pred
        counts[va_idx] += 1.0
    oof = oof_sum / np.maximum(counts, 1.0)
    fill = float(np.nanmean(y_log)) if np.any(np.isfinite(y_log)) else 0.0
    oof = np.where(np.isfinite(oof), oof, fill)
    return oof

def solve_weights(P, y):
    n = P.shape[1]
    if n == 0:
        return np.array([], dtype=float)
    try:
        from scipy.optimize import nnls
        w, _ = nnls(P, y)
        if np.all(np.isfinite(w)) and np.sum(w) > 1e-12:
            return w / np.sum(w)
    except Exception:
        pass
    return np.ones(n, dtype=float) / n

def fit_predict_model(name, X_train, y_log, X_pred, fill):
    try:
        model = make_model(name)
        model.fit(X_train, y_log)
        pred = model.predict(X_pred)
        pred = np.asarray(pred, dtype=float)
        pred = np.where(np.isfinite(pred), pred, fill)
        return pred
    except Exception:
        return np.full(len(X_pred), fill, dtype=float)

model_names = ['hgb', 'et', 'rf', 'ridge']
predictions = {}
for target in targets:
    y = pd.to_numeric(train[target], errors='coerce').to_numpy(dtype=float)
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    y = np.maximum(y, 0.0)
    y_log = np.log1p(y)
    oof_list = []
    for name in model_names:
        oof_list.append(oof_predictions(name, Xtr_eng, y_log))
    P = np.column_stack(oof_list)
    w = solve_weights(P, y_log)
    fill = float(np.mean(y_log)) if len(y_log) > 0 else 0.0
    pred_logs = []
    for name in model_names:
        pred_logs.append(fit_predict_model(name, Xtr_eng, y_log, Xte_eng, fill))
    pred_logs = np.column_stack(pred_logs)
    blend_log = pred_logs @ w
    pred = np.expm1(blend_log)
    pred = np.where(np.isfinite(pred), pred, 0.0)
    pred = np.maximum(pred, 0.0)
    predictions[target] = pred

out = pd.DataFrame({row_id: predict[row_id].values if row_id in predict.columns else np.arange(len(predict))})
for target in targets:
    out[target] = predictions[target]
output_columns = protocol.get('output_columns', [row_id] + list(targets))
out = out[output_columns]
out.to_csv(protocol.get('output_file', 'predictions.csv'), index=False)