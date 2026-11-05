import json, os, random, warnings
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor, GradientBoostingRegressor
try:
    from sklearn.ensemble import HistGradientBoostingRegressor
    HAS_HIST = True
except Exception:
    HAS_HIST = False

SEED = 7
np.random.seed(SEED)
random.seed(SEED)
warnings.filterwarnings('ignore')

def safe_log1p(y):
    return np.log1p(np.maximum(np.asarray(y, dtype=float), 0.0))

def rmse(y, p):
    return float(np.sqrt(np.mean((np.asarray(y, dtype=float) - np.asarray(p, dtype=float)) ** 2)))

def build_features(df, feature_cols):
    X = pd.DataFrame(index=df.index)
    for c in feature_cols:
        if c in df.columns:
            X[c] = pd.to_numeric(df[c], errors='coerce')
    if X.shape[1] == 0:
        for c in df.columns:
            if c != 'row_id' and pd.api.types.is_numeric_dtype(df[c]):
                X[c] = pd.to_numeric(df[c], errors='coerce')
    eps = 1e-9
    def getv(name):
        if name in X.columns:
            return X[name].astype(float).values
        return None
    a = getv('lattice_vector_1_ang')
    b = getv('lattice_vector_2_ang')
    c = getv('lattice_vector_3_ang')
    al = getv('lattice_angle_alpha_degree')
    be = getv('lattice_angle_beta_degree')
    ga = getv('lattice_angle_gamma_degree')
    vol = None
    if a is not None and b is not None and c is not None and al is not None and be is not None and ga is not None:
        alr = np.deg2rad(al)
        ber = np.deg2rad(be)
        gar = np.deg2rad(ga)
        ca = np.cos(alr)
        cb = np.cos(ber)
        cg = np.cos(gar)
        sa = np.sin(alr)
        sb = np.sin(ber)
        sg = np.sin(gar)
        term = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
        vol = a * b * c * np.sqrt(np.maximum(term, 0.0))
        X['cell_volume'] = vol
        X['log_cell_volume'] = np.log1p(np.maximum(vol, 0.0))
        X['inv_cell_volume'] = 1.0 / np.maximum(vol, eps)
        X['cos_alpha'] = ca
        X['cos_beta'] = cb
        X['cos_gamma'] = cg
        X['sin_alpha'] = sa
        X['sin_beta'] = sb
        X['sin_gamma'] = sg
        X['angle_sum'] = al + be + ga
        X['angle_dev_alpha'] = np.abs(al - 90.0)
        X['angle_dev_beta'] = np.abs(be - 90.0)
        X['angle_dev_gamma'] = np.abs(ga - 90.0)
        X['vec_ratio_12'] = a / np.maximum(b, eps)
        X['vec_ratio_13'] = a / np.maximum(c, eps)
        X['vec_ratio_23'] = b / np.maximum(c, eps)
        X['vec_sum'] = a + b + c
        X['vec_mean'] = (a + b + c) / 3.0
        X['vec_std'] = np.sqrt(((a - X['vec_mean'].values) ** 2 + (b - X['vec_mean'].values) ** 2 + (c - X['vec_mean'].values) ** 2) / 3.0)
        X['ab_product'] = a * b
        X['ac_product'] = a * c
        X['bc_product'] = b * c
    n_atoms = getv('number_of_total_atoms')
    if n_atoms is not None:
        X['log_n_atoms'] = np.log1p(np.maximum(n_atoms, 0.0))
        X['inv_n_atoms'] = 1.0 / np.maximum(n_atoms, 1.0)
        if vol is not None:
            X['volume_per_atom'] = vol / np.maximum(n_atoms, 1.0)
            X['atoms_per_volume'] = n_atoms / np.maximum(vol, eps)
    comps = ['percent_atom_al', 'percent_atom_ga', 'percent_atom_in']
    for cname in comps:
        if cname in X.columns:
            X[cname + '_sq'] = X[cname] * X[cname]
    if all(cname in X.columns for cname in comps):
        pa = X['percent_atom_al'].astype(float).values
        pg = X['percent_atom_ga'].astype(float).values
        pi = X['percent_atom_in'].astype(float).values
        psum = pa + pg + pi
        po = np.maximum(0.0, np.minimum(1.0, 1.0 - psum))
        X['comp_sum'] = psum
        X['oxygen_frac'] = po
        X['comp_max'] = np.maximum(np.maximum(pa, pg), pi)
        X['comp_min'] = np.minimum(np.minimum(pa, pg), pi)
        X['comp_range'] = X['comp_max'] - X['comp_min']
        X['al_ga'] = pa * pg
        X['ga_in'] = pg * pi
        X['in_al'] = pi * pa
        X['comp_product'] = pa * pg * pi
        p = np.vstack([np.maximum(pa, eps), np.maximum(pg, eps), np.maximum(pi, eps), np.maximum(po, eps)])
        X['comp_entropy'] = -np.sum(p * np.log(p), axis=0)
        X['al_over_ga'] = pa / np.maximum(pg, eps)
        X['al_over_in'] = pa / np.maximum(pi, eps)
        X['ga_over_in'] = pg / np.maximum(pi, eps)
        X['percent_balance'] = pa * pg + pg * pi + pi * pa
        X['avg_mass'] = pa * 26.9815 + pg * 69.723 + pi * 114.818 + po * 15.999
        X['avg_electroneg'] = pa * 1.61 + pg * 1.81 + pi * 1.78 + po * 3.44
        X['avg_atomic_num'] = pa * 13.0 + pg * 31.0 + pi * 49.0 + po * 8.0
        X['avg_ionic_radius'] = pa * 0.535 + pg * 0.620 + pi * 0.800 + po * 1.400
        X['avg_cation_radius'] = pa * 0.535 + pg * 0.620 + pi * 0.800
        if n_atoms is not None:
            X['al_count'] = pa * n_atoms
            X['ga_count'] = pg * n_atoms
            X['in_count'] = pi * n_atoms
            X['oxygen_count'] = po * n_atoms
            X['cation_count'] = (pa + pg + pi) * n_atoms
        if vol is not None:
            X['mass_per_volume'] = X['avg_mass'].values / np.maximum(vol, eps)
            X['electroneg_per_volume'] = X['avg_electroneg'].values / np.maximum(vol, eps)
            X['density_proxy'] = (X['avg_mass'].values * np.maximum(n_atoms, 1.0)) / np.maximum(vol, eps)
            X['radius_per_volume'] = X['avg_ionic_radius'].values / np.maximum(vol, eps)
    if 'spacegroup' in X.columns:
        sgv = X['spacegroup'].astype(float)
        X['spacegroup_mod_10'] = sgv % 10
        X['spacegroup_mod_100'] = sgv % 100
        X['spacegroup_mod_2'] = sgv % 2
        X['spacegroup_mod_3'] = sgv % 3
        X['spacegroup_mod_4'] = sgv % 4
        masks = {
            'triclinic': (sgv >= 1) & (sgv <= 2),
            'monoclinic': (sgv >= 3) & (sgv <= 15),
            'orthorhombic': (sgv >= 16) & (sgv <= 74),
            'tetragonal': (sgv >= 75) & (sgv <= 142),
            'trigonal': (sgv >= 143) & (sgv <= 167),
            'hexagonal': (sgv >= 168) & (sgv <= 194),
            'cubic': (sgv >= 195) & (sgv <= 230)
        }
        known = pd.Series(False, index=X.index)
        for k, m in masks.items():
            X['cs_' + k] = m.astype(float)
            known = known | m
        X['cs_unknown'] = (~known).astype(float)
    X = X.replace([np.inf, -np.inf], np.nan)
    return X

def make_candidates(seed):
    cand = []
    for alpha in [0.3, 1.0, 3.0, 10.0]:
        cand.append(('ridge_' + str(alpha), Pipeline([('imp', SimpleImputer(strategy='median')), ('sc', StandardScaler()), ('m', Ridge(alpha=alpha, random_state=seed))])))
    cand.append(('rf_400_06_1', Pipeline([('imp', SimpleImputer(strategy='median')), ('m', RandomForestRegressor(n_estimators=400, max_features=0.6, min_samples_leaf=1, random_state=seed, n_jobs=-1))])))
    cand.append(('et_400_07_1', Pipeline([('imp', SimpleImputer(strategy='median')), ('m', ExtraTreesRegressor(n_estimators=400, max_features=0.7, min_samples_leaf=1, random_state=seed, n_jobs=-1))])))
    cand.append(('et_300_09_2', Pipeline([('imp', SimpleImputer(strategy='median')), ('m', ExtraTreesRegressor(n_estimators=300, max_features=0.9, min_samples_leaf=2, random_state=seed, n_jobs=-1))])))
    cand.append(('gb_250_005_3', Pipeline([('imp', SimpleImputer(strategy='median')), ('m', GradientBoostingRegressor(n_estimators=250, learning_rate=0.05, max_depth=3, subsample=0.8, random_state=seed))])))
    if HAS_HIST:
        cand.append(('hist_350_005_31', Pipeline([('imp', SimpleImputer(strategy='median')), ('m', HistGradientBoostingRegressor(max_iter=350, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=0.1, min_samples_leaf=20, random_state=seed))])))
        cand.append(('hist_250_003_15', Pipeline([('imp', SimpleImputer(strategy='median')), ('m', HistGradientBoostingRegressor(max_iter=250, learning_rate=0.03, max_leaf_nodes=15, l2_regularization=0.5, min_samples_leaf=10, random_state=seed))])))
    return cand

def cv_oof(X, y, cand, seed, n_splits=5):
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    splits = list(kf.split(X))
    oof = {}
    scores = {}
    for name, model in cand:
        pred = np.zeros(len(y), dtype=float)
        for tr, va in splits:
            m = clone(model)
            m.fit(X.iloc[tr], y[tr])
            pred[va] = m.predict(X.iloc[va])
        pred = np.maximum(pred, 0.0)
        oof[name] = pred
        scores[name] = rmse(y, pred)
    return oof, scores

def greedy(oof, scores, y, n_iter=15):
    names = list(oof.keys())
    best = min(scores, key=lambda k: scores[k])
    ens = oof[best].copy()
    counts = {best: 1}
    total = 1
    best_score = scores[best]
    for _ in range(n_iter):
        bc = None
        bs = best_score
        for name in names:
            cand = (ens * total + oof[name]) / (total + 1.0)
            sc = rmse(y, cand)
            if sc + 1e-12 < bs:
                bs = sc
                bc = name
        if bc is None:
            break
        ens = (ens * total + oof[bc]) / (total + 1.0)
        counts[bc] = counts.get(bc, 0) + 1
        total += 1
        best_score = bs
    return {k: v / float(total) for k, v in counts.items()}, best_score

def main():
    with open(os.path.join('data', 'protocol.json'), 'r', encoding='utf-8') as f:
        protocol = json.load(f)
    train = pd.read_csv(os.path.join('data', protocol.get('training_file', 'train.csv')))
    predict = pd.read_csv(os.path.join('data', protocol.get('prediction_file', 'predict.csv')))
    row_id = protocol.get('row_id', 'row_id')
    targets = protocol.get('target_columns', ['formation_energy_ev_natom', 'bandgap_energy_ev'])
    feature_cols = protocol.get('features', [])
    Xtr = build_features(train, feature_cols)
    Xpr = build_features(predict, feature_cols)
    if 'spacegroup' in Xtr.columns and 'spacegroup' in Xpr.columns:
        sg_t = Xtr['spacegroup'].astype(float)
        sg_p = Xpr['spacegroup'].astype(float)
        freq = sg_t.value_counts(dropna=False)
        total = max(len(Xtr), 1)
        top = list(freq.head(40).index)
        Xtr['spacegroup_freq'] = sg_t.map(freq).fillna(0.0).astype(float) / float(total)
        Xpr['spacegroup_freq'] = sg_p.map(freq).fillna(0.0).astype(float) / float(total)
        for sg in top:
            if pd.isna(sg):
                continue
            try:
                si = int(sg)
            except Exception:
                continue
            col = 'sg_' + str(si)
            Xtr[col] = (sg_t == sg).astype(float)
            Xpr[col] = (sg_p == sg).astype(float)
        Xtr['spacegroup_rare'] = (~sg_t.isin(top)).astype(float)
        Xpr['spacegroup_rare'] = (~sg_p.isin(top)).astype(float)
    cols = list(Xtr.columns)
    for c in Xpr.columns:
        if c not in cols:
            cols.append(c)
    Xtr = Xtr.reindex(columns=cols)
    Xpr = Xpr.reindex(columns=cols)
    cand = make_candidates(SEED)
    preds = {}
    for target in targets:
        y_orig = pd.to_numeric(train[target], errors='coerce').values
        y_orig = np.nan_to_num(y_orig, nan=0.0, posinf=0.0, neginf=0.0)
        y_orig = np.maximum(y_orig, 0.0)
        ylog = safe_log1p(y_orig)
        oof, scores = cv_oof(Xtr, ylog, cand, SEED, 5)
        sorted_names = sorted(scores, key=lambda k: scores[k])
        blends = []
        best_name = sorted_names[0]
        blends.append(({best_name: 1.0}, scores[best_name]))
        for k in [2, 3, 4]:
            if len(sorted_names) >= k:
                w = {n: 1.0 / k for n in sorted_names[:k]}
                ens = np.zeros(len(ylog), dtype=float)
                for n in sorted_names[:k]:
                    ens += oof[n] / float(k)
                blends.append((w, rmse(ylog, ens)))
        gw, gs = greedy(oof, scores, ylog, n_iter=15)
        blends.append((gw, gs))
        best_w, best_score = min(blends, key=lambda x: x[1])
        tw = sum(best_w.values())
        if tw <= 0:
            best_w = {best_name: 1.0}
            tw = 1.0
        best_w = {k: v / tw for k, v in best_w.items()}
        pl = np.zeros(len(Xpr), dtype=float)
        for name, model in cand:
            if name in best_w and best_w[name] > 1e-12:
                m = clone(model)
                m.fit(Xtr, ylog)
                p = m.predict(Xpr)
                p = np.maximum(p, 0.0)
                pl += best_w[name] * p
        max_train = float(np.max(y_orig))
        upper_log = np.log1p(max_train * 2.0 + 1e-6)
        pl = np.clip(pl, 0.0, upper_log)
        p = np.expm1(pl)
        p = np.nan_to_num(p, nan=0.0, posinf=max_train * 10.0 + 1e6, neginf=0.0)
        p = np.maximum(p, 0.0)
        preds[target] = p
    out = pd.DataFrame()
    out[row_id] = predict[row_id].values
    for target in targets:
        out[target] = preds[target]
    out = out.reindex(columns=protocol.get('output_columns', [row_id] + targets))
    out.to_csv(protocol.get('output_file', 'predictions.csv'), index=False)

if __name__ == '__main__':
    main()
