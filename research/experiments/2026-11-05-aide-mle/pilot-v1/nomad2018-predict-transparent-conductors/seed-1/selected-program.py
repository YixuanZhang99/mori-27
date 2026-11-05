import os, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from sklearn.preprocessing import OneHotEncoder
from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor, HistGradientBoostingRegressor, GradientBoostingRegressor
from sklearn.model_selection import KFold

def load_protocol():
    for p in ['data/protocol.json', 'protocol.json']:
        if os.path.exists(p):
            with open(p, 'r') as f:
                return json.load(f)
    raise FileNotFoundError('protocol.json not found')

def load_csv(name):
    for p in [name, os.path.join('data', name)]:
        if os.path.exists(p):
            return pd.read_csv(p)
    raise FileNotFoundError(name)

protocol = load_protocol()
SEED = int(protocol.get('seed', 7))
np.random.seed(SEED)
train = load_csv(protocol.get('training_file', 'train.csv'))
test = load_csv(protocol.get('prediction_file', 'predict.csv'))
features = protocol['features']
targets = protocol['target_columns']
row_id = protocol.get('row_id', 'row_id')
output_columns = protocol.get('output_columns', [row_id] + targets)

def get_num(df, name, idx):
    if name in df.columns:
        return pd.to_numeric(df[name], errors='coerce')
    return pd.Series(np.nan, index=idx)

def engineer(df, features, sg_freq_map=None):
    idx = df.index
    X = pd.DataFrame(index=idx)
    for c in features:
        if c != 'spacegroup':
            X[c] = get_num(df, c, idx)
    if 'spacegroup' in df.columns:
        sg = df['spacegroup'].astype('object').where(df['spacegroup'].notna(), 'missing').astype(str)
        X['spacegroup_num'] = pd.to_numeric(df['spacegroup'], errors='coerce')
        if sg_freq_map is not None:
            X['spacegroup_freq'] = sg.map(sg_freq_map).fillna(0.0).astype(float)
        else:
            X['spacegroup_freq'] = 0.0
    else:
        sg = pd.Series('missing', index=idx, dtype='object')
        X['spacegroup_num'] = np.nan
        X['spacegroup_freq'] = 0.0
    def col(name):
        if name in X.columns:
            return X[name].astype(float)
        return pd.Series(np.nan, index=idx, dtype=float)
    a = col('lattice_vector_1_ang')
    b = col('lattice_vector_2_ang')
    c = col('lattice_vector_3_ang')
    al = col('lattice_angle_alpha_degree')
    be = col('lattice_angle_beta_degree')
    ga = col('lattice_angle_gamma_degree')
    ca = np.cos(np.deg2rad(al.to_numpy(dtype=float)))
    cb = np.cos(np.deg2rad(be.to_numpy(dtype=float)))
    cg = np.cos(np.deg2rad(ga.to_numpy(dtype=float)))
    sa = np.sin(np.deg2rad(al.to_numpy(dtype=float)))
    sb = np.sin(np.deg2rad(be.to_numpy(dtype=float)))
    sc = np.sin(np.deg2rad(ga.to_numpy(dtype=float)))
    aa = a.to_numpy(dtype=float)
    bb = b.to_numpy(dtype=float)
    cc = c.to_numpy(dtype=float)
    term = 1.0 - ca*ca - cb*cb - cg*cg + 2.0*ca*cb*cg
    vol = aa*bb*cc*np.sqrt(np.maximum(term, 0.0))
    X['lattice_volume'] = vol
    X['lattice_volume_log'] = np.log1p(np.maximum(vol, 0.0))
    X['lattice_abc_product'] = aa*bb*cc
    X['lattice_ab'] = aa*bb
    X['lattice_bc'] = bb*cc
    X['lattice_ca'] = cc*aa
    X['lattice_mean'] = (aa+bb+cc)/3.0
    X['lattice_std'] = np.std(np.vstack([aa,bb,cc]), axis=0)
    X['lattice_max'] = np.max(np.vstack([aa,bb,cc]), axis=0)
    X['lattice_min'] = np.min(np.vstack([aa,bb,cc]), axis=0)
    X['lattice_range'] = X['lattice_max'] - X['lattice_min']
    X['lattice_ratio_ab'] = aa / (bb + 1e-9)
    X['lattice_ratio_bc'] = bb / (cc + 1e-9)
    X['lattice_ratio_ca'] = cc / (aa + 1e-9)
    X['lattice_ratio_ac'] = aa / (cc + 1e-9)
    X['lattice_ratio_ba'] = bb / (aa + 1e-9)
    X['lattice_ratio_cb'] = cc / (bb + 1e-9)
    X['recip_a'] = 1.0 / (aa + 1e-9)
    X['recip_b'] = 1.0 / (bb + 1e-9)
    X['recip_c'] = 1.0 / (cc + 1e-9)
    X['cos_alpha'] = ca
    X['cos_beta'] = cb
    X['cos_gamma'] = cg
    X['sin_alpha'] = sa
    X['sin_beta'] = sb
    X['sin_gamma'] = sc
    X['angle_sum_deg'] = al + be + ga
    X['angle_mean_deg'] = (al + be + ga)/3.0
    X['angle_std_deg'] = np.std(np.vstack([al.to_numpy(dtype=float), be.to_numpy(dtype=float), ga.to_numpy(dtype=float)]), axis=0)
    X['angle_alpha_beta_diff'] = al - be
    X['angle_beta_gamma_diff'] = be - ga
    X['angle_gamma_alpha_diff'] = ga - al
    X['angle_max_deg'] = np.max(np.vstack([al.to_numpy(dtype=float), be.to_numpy(dtype=float), ga.to_numpy(dtype=float)]), axis=0)
    X['angle_min_deg'] = np.min(np.vstack([al.to_numpy(dtype=float), be.to_numpy(dtype=float), ga.to_numpy(dtype=float)]), axis=0)
    X['volume_term'] = term
    nat = col('number_of_total_atoms')
    X['density_atoms_per_volume'] = nat / (vol + 1e-6)
    X['volume_per_atom'] = vol / (nat + 1e-6)
    X['total_atoms_log'] = np.log1p(np.maximum(nat.to_numpy(dtype=float), 0.0))
    p_al = col('percent_atom_al')
    p_ga = col('percent_atom_ga')
    p_in = col('percent_atom_in')
    p_sum = p_al + p_ga + p_in
    X['percent_sum'] = p_sum
    X['percent_mean'] = p_sum / 3.0
    X['percent_std'] = np.std(np.vstack([p_al.to_numpy(dtype=float), p_ga.to_numpy(dtype=float), p_in.to_numpy(dtype=float)]), axis=0)
    X['percent_max'] = np.max(np.vstack([p_al.to_numpy(dtype=float), p_ga.to_numpy(dtype=float), p_in.to_numpy(dtype=float)]), axis=0)
    X['percent_min'] = np.min(np.vstack([p_al.to_numpy(dtype=float), p_ga.to_numpy(dtype=float), p_in.to_numpy(dtype=float)]), axis=0)
    X['percent_range'] = X['percent_max'] - X['percent_min']
    X['percent_al_ga'] = p_al + p_ga
    X['percent_ga_in'] = p_ga + p_in
    X['percent_al_in'] = p_al + p_in
    eps = 1e-6
    X['frac_al'] = p_al / (p_sum + eps)
    X['frac_ga'] = p_ga / (p_sum + eps)
    X['frac_in'] = p_in / (p_sum + eps)
    X['frac_al_ga'] = X['frac_al'] + X['frac_ga']
    X['frac_ga_in'] = X['frac_ga'] + X['frac_in']
    X['frac_al_in'] = X['frac_al'] + X['frac_in']
    X['frac_diff_al_ga'] = X['frac_al'] - X['frac_ga']
    X['frac_diff_ga_in'] = X['frac_ga'] - X['frac_in']
    X['frac_diff_in_al'] = X['frac_in'] - X['frac_al']
    X['count_al'] = nat * p_al / 100.0
    X['count_ga'] = nat * p_ga / 100.0
    X['count_in'] = nat * p_in / 100.0
    X['count_sum'] = X['count_al'] + X['count_ga'] + X['count_in']
    X['count_mean'] = X['count_sum'] / 3.0
    X['vol_frac_al'] = vol * X['frac_al']
    X['vol_frac_ga'] = vol * X['frac_ga']
    X['vol_frac_in'] = vol * X['frac_in']
    mass_al, mass_ga, mass_in = 26.9815, 69.723, 114.818
    z_al, z_ga, z_in = 13.0, 31.0, 49.0
    en_al, en_ga, en_in = 1.61, 1.81, 1.78
    rad_al, rad_ga, rad_in = 121.0, 122.0, 142.0
    f_al = X['frac_al'].to_numpy(dtype=float)
    f_ga = X['frac_ga'].to_numpy(dtype=float)
    f_in = X['frac_in'].to_numpy(dtype=float)
    X['mass_mean'] = f_al*mass_al + f_ga*mass_ga + f_in*mass_in
    X['atomic_number_mean'] = f_al*z_al + f_ga*z_ga + f_in*z_in
    X['electronegativity_mean'] = f_al*en_al + f_ga*en_ga + f_in*en_in
    X['radius_mean'] = f_al*rad_al + f_ga*rad_ga + f_in*rad_in
    X['mass_var'] = f_al*(mass_al - X['mass_mean'])**2 + f_ga*(mass_ga - X['mass_mean'])**2 + f_in*(mass_in - X['mass_mean'])**2
    X['en_var'] = f_al*(en_al - X['electronegativity_mean'])**2 + f_ga*(en_ga - X['electronegativity_mean'])**2 + f_in*(en_in - X['electronegativity_mean'])**2
    X['radius_var'] = f_al*(rad_al - X['radius_mean'])**2 + f_ga*(rad_ga - X['radius_mean'])**2 + f_in*(rad_in - X['radius_mean'])**2
    X = X.replace([np.inf, -np.inf], np.nan)
    return X, sg

if 'spacegroup' in train.columns:
    sg_train_series = train['spacegroup'].astype('object').where(train['spacegroup'].notna(), 'missing').astype(str)
    sg_freq_map = sg_train_series.value_counts(normalize=True).to_dict()
else:
    sg_freq_map = {'missing': 1.0}

X_train_num, train_sg = engineer(train, features, sg_freq_map)
X_test_num, test_sg = engineer(test, features, sg_freq_map)

def impute_numeric(Xtr_df, Xte_df):
    tr = Xtr_df.to_numpy(dtype=float)
    te = Xte_df.to_numpy(dtype=float)
    med = np.zeros(tr.shape[1], dtype=float)
    for j in range(tr.shape[1]):
        col = tr[:, j]
        finite = col[np.isfinite(col)]
        if finite.size > 0:
            med[j] = np.median(finite)
        else:
            med[j] = 0.0
    tr = np.where(np.isfinite(tr), tr, med)
    te = np.where(np.isfinite(te), te, med)
    return tr, te

X_train_imp, X_test_imp = impute_numeric(X_train_num, X_test_num)

train_sg_df = train_sg.to_frame('spacegroup')
test_sg_df = test_sg.to_frame('spacegroup')
try:
    encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False)
except TypeError:
    encoder = OneHotEncoder(handle_unknown='ignore', sparse=False)
train_sg_enc = encoder.fit_transform(train_sg_df)
test_sg_enc = encoder.transform(test_sg_df)
X_train = np.hstack([X_train_imp, train_sg_enc]).astype(float)
X_test = np.hstack([X_test_imp, test_sg_enc]).astype(float)

y = train[targets].to_numpy(dtype=float)
y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
y = np.maximum(y, 0.0)
y_log = np.log1p(y)

def get_model(name, seed):
    if name == 'rf1':
        return RandomForestRegressor(n_estimators=500, max_features=0.6, min_samples_leaf=1, random_state=seed, n_jobs=-1)
    if name == 'rf2':
        return RandomForestRegressor(n_estimators=400, max_features=0.8, min_samples_leaf=2, random_state=seed+1, n_jobs=-1)
    if name == 'et1':
        return ExtraTreesRegressor(n_estimators=500, max_features=0.7, min_samples_leaf=1, random_state=seed, n_jobs=-1)
    if name == 'et2':
        return ExtraTreesRegressor(n_estimators=400, max_features=0.9, min_samples_leaf=2, random_state=seed+1, n_jobs=-1)
    if name == 'hgb1':
        return HistGradientBoostingRegressor(max_iter=500, learning_rate=0.03, max_leaf_nodes=15, min_samples_leaf=10, l2_regularization=0.5, random_state=seed, early_stopping=False)
    if name == 'hgb2':
        return HistGradientBoostingRegressor(max_iter=450, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=5, l2_regularization=1.0, random_state=seed+1, early_stopping=False)
    if name == 'hgb3':
        return HistGradientBoostingRegressor(max_iter=600, learning_rate=0.02, max_leaf_nodes=7, min_samples_leaf=15, l2_regularization=0.0, random_state=seed+2, early_stopping=False)
    if name == 'hgb4':
        return HistGradientBoostingRegressor(max_iter=400, learning_rate=0.04, max_leaf_nodes=63, min_samples_leaf=20, l2_regularization=0.1, random_state=seed+3, early_stopping=False)
    return GradientBoostingRegressor(n_estimators=500, learning_rate=0.03, max_depth=3, min_samples_leaf=5, subsample=0.8, random_state=seed)

model_names = ['rf1', 'rf2', 'et1', 'et2', 'hgb1', 'hgb2', 'hgb3', 'hgb4', 'gbr']

def fit_nnls_intercept(yv, P, iters=300):
    n, m = P.shape
    w = np.full(m, 1.0 / max(m, 1), dtype=float)
    b = float(np.mean(yv - P.dot(w)))
    for _ in range(iters):
        b = float(np.mean(yv - P.dot(w)))
        for j in range(m):
            r = yv - b - P.dot(w) + w[j] * P[:, j]
            denom = float(np.dot(P[:, j], P[:, j])) + 1e-12
            num = float(np.dot(P[:, j], r))
            w[j] = max(0.0, num / denom)
    b = float(np.mean(yv - P.dot(w)))
    return w, b

def choose_blend(yv, P):
    n, m = P.shape
    candidates = []
    w_eq = np.ones(m, dtype=float) / m
    candidates.append((float(np.sqrt(np.mean((P.dot(w_eq) - yv) ** 2))), 'equal', w_eq, 0.0))
    mses = np.mean((P - yv[:, None]) ** 2, axis=0) + 1e-12
    w_inv = (1.0 / mses)
    w_inv = w_inv / w_inv.sum()
    candidates.append((float(np.sqrt(np.mean((P.dot(w_inv) - yv) ** 2))), 'inv', w_inv, 0.0))
    w_nn, b_nn = fit_nnls_intercept(yv, P)
    candidates.append((float(np.sqrt(np.mean((P.dot(w_nn) + b_nn - yv) ** 2))), 'nnls', w_nn, b_nn))
    for j in range(m):
        pred = P[:, j]
        candidates.append((float(np.sqrt(np.mean((pred - yv) ** 2))), 'single_p%d' % j, np.eye(m)[j], 0.0))
    order = np.argsort(mses)
    top3 = order[:min(3, m)]
    w_top = np.zeros(m, dtype=float)
    w_top[top3] = 1.0 / len(top3)
    candidates.append((float(np.sqrt(np.mean((P.dot(w_top) - yv) ** 2))), 'top3', w_top, 0.0))
    best = min(candidates, key=lambda x: x[0])
    return best[2], best[3], best[1], best[0]

n_train = X_train.shape[0]
n_test = X_test.shape[0]
preds = np.zeros((n_test, len(targets)), dtype=float)
kf = KFold(n_splits=5, shuffle=True, random_state=SEED)

for t_idx, target in enumerate(targets):
    oof = np.zeros((n_train, len(model_names)), dtype=float)
    for tr, va in kf.split(X_train):
        X_tr, X_va = X_train[tr], X_train[va]
        y_tr = y_log[tr, t_idx]
        for m_idx, name in enumerate(model_names):
            model = get_model(name, SEED)
            model.fit(X_tr, y_tr)
            oof[va, m_idx] = model.predict(X_va)
    w, b, blend_name, blend_rmse = choose_blend(y_log[:, t_idx], oof)
    test_model_preds = np.zeros((n_test, len(model_names)), dtype=float)
    for m_idx, name in enumerate(model_names):
        model = get_model(name, SEED)
        model.fit(X_train, y_log[:, t_idx])
        test_model_preds[:, m_idx] = model.predict(X_test)
    test_log = test_model_preds.dot(w) + b
    max_train_log = float(np.max(y_log[:, t_idx])) if y_log.shape[0] > 0 else 0.0
    upper = max_train_log + 1.0
    test_log = np.clip(test_log, 0.0, upper)
    pred = np.expm1(test_log)
    pred = np.nan_to_num(pred, nan=0.0, posinf=0.0, neginf=0.0)
    pred = np.maximum(pred, 0.0)
    preds[:, t_idx] = pred

out = pd.DataFrame({row_id: test[row_id].to_numpy()})
for i, target in enumerate(targets):
    out[target] = preds[:, i]
out = out[output_columns]
out.to_csv(protocol.get('output_file', 'predictions.csv'), index=False)