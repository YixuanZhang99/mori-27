import json, os, math, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor, HistGradientBoostingRegressor, GradientBoostingRegressor
from sklearn.model_selection import KFold
from sklearn.preprocessing import OneHotEncoder
from collections import Counter

SEED = 7
np.random.seed(SEED)

def find_file(name):
    for p in [name, os.path.join('data', name)]:
        if os.path.exists(p):
            return p
    return name

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

protocol = load_json(find_file('protocol.json'))
train = pd.read_csv(find_file(protocol.get('training_file', 'train.csv')))
predict = pd.read_csv(find_file(protocol.get('prediction_file', 'predict.csv')))
features = protocol['features']
row_id = protocol.get('row_id', 'row_id')
targets = protocol['target_columns']
out_cols = protocol['output_columns']
output_file = protocol.get('output_file', 'predictions.csv')

num_features = [c for c in features if c != 'spacegroup']

medians = {}
for c in num_features:
    if c in train.columns:
        v = pd.to_numeric(train[c], errors='coerce').median()
    else:
        v = 0.0
    if pd.isna(v):
        v = 0.0
    medians[c] = float(v)

if 'spacegroup' in train.columns:
    sg_train = pd.to_numeric(train['spacegroup'], errors='coerce')
    mode_sg = sg_train.mode(dropna=True)
    mode_val = int(mode_sg.iloc[0]) if len(mode_sg) > 0 else 0
    freq_map = sg_train.value_counts(normalize=True, dropna=True).to_dict()
else:
    mode_val = 0
    freq_map = {}

atomic_props = {
    'Al': {'mass': 26.9815, 'en': 1.61, 'radius': 121, 'Z': 13},
    'Ga': {'mass': 69.723, 'en': 1.81, 'radius': 122, 'Z': 31},
    'In': {'mass': 114.818, 'en': 1.78, 'radius': 142, 'Z': 49}
}

def make_design(df, encoder=None, fit_encoder=False):
    X = pd.DataFrame(index=df.index)
    for c in num_features:
        if c in df.columns:
            vals = pd.to_numeric(df[c], errors='coerce')
        else:
            vals = pd.Series(np.nan, index=df.index)
        X[c] = vals.fillna(medians.get(c, 0.0)).astype(float)
    if 'spacegroup' in df.columns:
        sg_series = pd.to_numeric(df['spacegroup'], errors='coerce').fillna(mode_val)
    else:
        sg_series = pd.Series(mode_val, index=df.index)
    sg = sg_series.round().astype(int)
    eps = 1e-9
    a = X['lattice_vector_1_ang'].clip(lower=eps)
    b = X['lattice_vector_2_ang'].clip(lower=eps)
    c = X['lattice_vector_3_ang'].clip(lower=eps)
    alpha = np.deg2rad(X['lattice_angle_alpha_degree'].clip(0, 180))
    beta = np.deg2rad(X['lattice_angle_beta_degree'].clip(0, 180))
    gamma = np.deg2rad(X['lattice_angle_gamma_degree'].clip(0, 180))
    ca = np.cos(alpha)
    cb = np.cos(beta)
    cg = np.cos(gamma)
    term = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
    vol = a * b * c * np.sqrt(term.clip(lower=1e-9))
    X['lattice_volume'] = vol
    X['log_volume'] = np.log1p(vol.clip(lower=0))
    X['inv_volume'] = 1.0 / (vol + eps)
    X['log_lattice_1'] = np.log1p(a)
    X['log_lattice_2'] = np.log1p(b)
    X['log_lattice_3'] = np.log1p(c)
    X['lattice_avg'] = (a + b + c) / 3.0
    X['lattice_min'] = np.minimum(np.minimum(a, b), c)
    X['lattice_max'] = np.maximum(np.maximum(a, b), c)
    X['lattice_range'] = X['lattice_max'] - X['lattice_min']
    X['lattice_std'] = np.sqrt(((a - X['lattice_avg']) ** 2 + (b - X['lattice_avg']) ** 2 + (c - X['lattice_avg']) ** 2) / 3.0)
    X['lattice_ratio_ab'] = a / (b + eps)
    X['lattice_ratio_ac'] = a / (c + eps)
    X['lattice_ratio_bc'] = b / (c + eps)
    X['lattice_prod'] = a * b * c
    X['log_lattice_prod'] = np.log1p(X['lattice_prod'].clip(lower=0))
    X['atoms_per_volume'] = X['number_of_total_atoms'] / (vol + eps)
    X['volume_per_atom'] = vol / (X['number_of_total_atoms'] + eps)
    X['log_atoms'] = np.log1p(X['number_of_total_atoms'].clip(lower=0))
    p_al = X['percent_atom_al'].clip(lower=0)
    p_ga = X['percent_atom_ga'].clip(lower=0)
    p_in = X['percent_atom_in'].clip(lower=0)
    p_sum = p_al + p_ga + p_in
    X['comp_sum'] = p_sum
    n_al = p_al / (p_sum + eps)
    n_ga = p_ga / (p_sum + eps)
    n_in = p_in / (p_sum + eps)
    X['atom_al_count'] = X['number_of_total_atoms'] * p_al
    X['atom_ga_count'] = X['number_of_total_atoms'] * p_ga
    X['atom_in_count'] = X['number_of_total_atoms'] * p_in
    X['al_ga_diff'] = p_al - p_ga
    X['al_in_diff'] = p_al - p_in
    X['ga_in_diff'] = p_ga - p_in
    X['al_ga_ratio'] = p_al / (p_ga + eps)
    X['al_in_ratio'] = p_al / (p_in + eps)
    X['ga_in_ratio'] = p_ga / (p_in + eps)
    X['comp_entropy'] = -(n_al * np.log(n_al + eps) + n_ga * np.log(n_ga + eps) + n_in * np.log(n_in + eps))
    X['comp_entropy_norm'] = X['comp_entropy'] / math.log(3.0)
    X['al_sq'] = p_al ** 2
    X['ga_sq'] = p_ga ** 2
    X['in_sq'] = p_in ** 2
    X['al_ga_prod'] = p_al * p_ga
    X['al_in_prod'] = p_al * p_in
    X['ga_in_prod'] = p_ga * p_in
    mass_al = atomic_props['Al']['mass']
    mass_ga = atomic_props['Ga']['mass']
    mass_in = atomic_props['In']['mass']
    en_al = atomic_props['Al']['en']
    en_ga = atomic_props['Ga']['en']
    en_in = atomic_props['In']['en']
    rad_al = atomic_props['Al']['radius']
    rad_ga = atomic_props['Ga']['radius']
    rad_in = atomic_props['In']['radius']
    Z_al = atomic_props['Al']['Z']
    Z_ga = atomic_props['Ga']['Z']
    Z_in = atomic_props['In']['Z']
    avg_mass = n_al * mass_al + n_ga * mass_ga + n_in * mass_in
    avg_en = n_al * en_al + n_ga * en_ga + n_in * en_in
    avg_rad = n_al * rad_al + n_ga * rad_ga + n_in * rad_in
    avg_Z = n_al * Z_al + n_ga * Z_ga + n_in * Z_in
    X['avg_atomic_mass'] = avg_mass
    X['avg_electronegativity'] = avg_en
    X['avg_atomic_radius'] = avg_rad
    X['avg_atomic_number'] = avg_Z
    X['var_mass'] = n_al * (mass_al - avg_mass) ** 2 + n_ga * (mass_ga - avg_mass) ** 2 + n_in * (mass_in - avg_mass) ** 2
    X['var_en'] = n_al * (en_al - avg_en) ** 2 + n_ga * (en_ga - avg_en) ** 2 + n_in * (en_in - avg_en) ** 2
    X['var_rad'] = n_al * (rad_al - avg_rad) ** 2 + n_ga * (rad_ga - avg_rad) ** 2 + n_in * (rad_in - avg_rad) ** 2
    total_mass = X['atom_al_count'] * mass_al + X['atom_ga_count'] * mass_ga + X['atom_in_count'] * mass_in
    total_Z = X['atom_al_count'] * Z_al + X['atom_ga_count'] * Z_ga + X['atom_in_count'] * Z_in
    X['total_mass'] = total_mass
    X['total_Z'] = total_Z
    X['mass_per_atom'] = total_mass / (X['number_of_total_atoms'] + eps)
    X['Z_per_atom'] = total_Z / (X['number_of_total_atoms'] + eps)
    X['angle_alpha_dev90'] = np.abs(alpha - math.pi / 2.0)
    X['angle_beta_dev90'] = np.abs(beta - math.pi / 2.0)
    X['angle_gamma_dev90'] = np.abs(gamma - math.pi / 2.0)
    X['angle_gamma_dev120'] = np.abs(gamma - 2.0 * math.pi / 3.0)
    X['angle_sum'] = alpha + beta + gamma
    X['cos_alpha'] = ca
    X['cos_beta'] = cb
    X['cos_gamma'] = cg
    X['sin_alpha'] = np.sin(alpha)
    X['sin_beta'] = np.sin(beta)
    X['sin_gamma'] = np.sin(gamma)
    X['cos_sum'] = ca + cb + cg
    X['spacegroup_int'] = sg.values
    X['spacegroup_freq'] = sg.map(freq_map).fillna(0.0).values
    if fit_encoder:
        try:
            encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False, dtype=np.float32)
        except TypeError:
            encoder = OneHotEncoder(handle_unknown='ignore', sparse=False, dtype=np.float32)
        ohe = encoder.fit_transform(sg.values.reshape(-1, 1))
    else:
        ohe = encoder.transform(sg.values.reshape(-1, 1))
    Xv = X.values.astype(np.float32)
    ohev = ohe.astype(np.float32)
    return np.hstack([Xv, ohev]), encoder

X_train, ohe = make_design(train, fit_encoder=True)
X_pred, _ = make_design(predict, encoder=ohe, fit_encoder=False)

def model_list():
    return [
        ('et1', ExtraTreesRegressor(n_estimators=500, max_features=0.7, min_samples_leaf=1, random_state=SEED, n_jobs=-1)),
        ('et2', ExtraTreesRegressor(n_estimators=500, max_features=0.5, min_samples_leaf=2, random_state=SEED+1, n_jobs=-1)),
        ('et3', ExtraTreesRegressor(n_estimators=400, max_features=0.3, min_samples_leaf=3, random_state=SEED+11, n_jobs=-1)),
        ('rf1', RandomForestRegressor(n_estimators=500, max_features=0.7, min_samples_leaf=1, random_state=SEED+2, n_jobs=-1)),
        ('rf2', RandomForestRegressor(n_estimators=500, max_features=0.5, min_samples_leaf=2, random_state=SEED+3, n_jobs=-1)),
        ('rf3', RandomForestRegressor(n_estimators=400, max_features=0.3, min_samples_leaf=3, random_state=SEED+12, n_jobs=-1)),
        ('hgb1', HistGradientBoostingRegressor(max_iter=500, learning_rate=0.03, max_leaf_nodes=31, min_samples_leaf=20, l2_regularization=0.1, random_state=SEED+4)),
        ('hgb2', HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=10, l2_regularization=0.05, random_state=SEED+5)),
        ('gbr1', GradientBoostingRegressor(n_estimators=400, learning_rate=0.03, max_depth=4, subsample=0.8, max_features=0.7, random_state=SEED+6)),
        ('gbr2', GradientBoostingRegressor(n_estimators=300, learning_rate=0.04, max_depth=3, subsample=0.9, max_features=0.8, random_state=SEED+7))
    ]

models = model_list()
model_dict = dict(models)
kf = KFold(n_splits=5, shuffle=True, random_state=SEED)

def greedy_ensemble(oofs, rmses, y_log, max_iter=30):
    names = list(oofs.keys())
    best_name = min(rmses, key=rmses.get)
    ensemble = [best_name]
    current_pred = oofs[best_name].copy()
    current_rmse = rmses[best_name]
    for it in range(max_iter):
        best_add = None
        best_new_rmse = current_rmse
        best_new_pred = None
        for name in names:
            new_pred = (current_pred * len(ensemble) + oofs[name]) / (len(ensemble) + 1)
            new_rmse = math.sqrt(float(np.mean((new_pred - y_log) ** 2)))
            if new_rmse < best_new_rmse - 1e-12:
                best_new_rmse = new_rmse
                best_add = name
                best_new_pred = new_pred
        if best_add is None:
            break
        ensemble.append(best_add)
        current_pred = best_new_pred
        current_rmse = best_new_rmse
    counts = Counter(ensemble)
    total = sum(counts.values())
    weights = {name: counts[name] / total for name in counts}
    return weights, current_rmse

selected = {}
pred_all = {}
for target in targets:
    y = pd.to_numeric(train[target], errors='coerce').values
    mask = np.isfinite(y)
    y_log = np.log1p(np.clip(y[mask], 0.0, None))
    X_t = X_train[mask]
    oofs = {}
    rmses = {}
    for name, model in models:
        oof = np.zeros(len(y_log), dtype=float)
        for tr, va in kf.split(X_t):
            m = clone(model)
            m.fit(X_t[tr], y_log[tr])
            oof[va] = m.predict(X_t[va])
        rmse = math.sqrt(float(np.mean((oof - y_log) ** 2)))
        oofs[name] = oof
        rmses[name] = rmse
    weights, best_rmse = greedy_ensemble(oofs, rmses, y_log, max_iter=25)
    selected[target] = (weights, best_rmse)
    pl = np.zeros(len(predict), dtype=float)
    for name, w in weights.items():
        m = clone(model_dict[name])
        m.fit(X_t, y_log)
        pl += w * m.predict(X_pred)
    vals = np.expm1(pl)
    vals = np.nan_to_num(vals, nan=0.0, posinf=1e12, neginf=0.0)
    vals = np.clip(vals, 0.0, None)
    pred_all[target] = vals

out = pd.DataFrame({row_id: predict[row_id].values})
for target in targets:
    out[target] = pred_all[target]
for c in out_cols:
    if c not in out.columns:
        if c == row_id:
            out[c] = predict[row_id].values
        elif c in targets:
            out[c] = pred_all[c]
        else:
            out[c] = 0.0
out = out[out_cols]
out.to_csv(output_file, index=False)