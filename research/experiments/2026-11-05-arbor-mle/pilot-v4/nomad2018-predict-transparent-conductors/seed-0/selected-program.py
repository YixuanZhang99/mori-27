import json
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import KFold
from sklearn.metrics import mean_squared_error

with open('data/protocol.json') as f:
    protocol = json.load(f)

targets = protocol['target_columns']
seed = int(protocol.get('seed', 7))
id_col = protocol['row_id']

train = pd.read_csv('data/train.csv')
predict = pd.read_csv('data/predict.csv')

sg_freq = train['spacegroup'].value_counts(normalize=True).to_dict()

def add_features(df):
    df = df.copy()
    a = df['lattice_vector_1_ang'].astype(float).values
    b = df['lattice_vector_2_ang'].astype(float).values
    c = df['lattice_vector_3_ang'].astype(float).values
    alpha = np.radians(df['lattice_angle_alpha_degree'].astype(float).values)
    beta = np.radians(df['lattice_angle_beta_degree'].astype(float).values)
    gamma = np.radians(df['lattice_angle_gamma_degree'].astype(float).values)
    ca = np.cos(alpha)
    cb = np.cos(beta)
    cg = np.cos(gamma)
    arg = 1.0 - ca*ca - cb*cb - cg*cg + 2.0*ca*cb*cg
    arg = np.clip(arg, 0.0, None)
    volume = a * b * c * np.sqrt(arg)
    df['lattice_volume'] = volume
    mean_l = (a + b + c) / 3.0
    df['lattice_mean'] = mean_l
    df['aspect_ab'] = a / np.where(b > 0, b, np.nan)
    df['aspect_bc'] = b / np.where(c > 0, c, np.nan)
    df['aspect_ac'] = a / np.where(c > 0, c, np.nan)
    max_l = np.maximum(np.maximum(a, b), c)
    min_l = np.minimum(np.minimum(a, b), c)
    df['lattice_anisotropy'] = max_l / np.where(mean_l > 0, mean_l, np.nan)
    df['lattice_range'] = max_l - min_l
    p_al = df['percent_atom_al'].astype(float).values / 100.0
    p_ga = df['percent_atom_ga'].astype(float).values / 100.0
    p_in = df['percent_atom_in'].astype(float).values / 100.0
    eps = 1e-12
    ent = -(p_al * np.log(np.clip(p_al, eps, 1.0)) +
            p_ga * np.log(np.clip(p_ga, eps, 1.0)) +
            p_in * np.log(np.clip(p_in, eps, 1.0)))
    df['atom_entropy'] = ent
    df['spacegroup_freq'] = df['spacegroup'].map(sg_freq).fillna(0.0).astype(float)
    return df

train = add_features(train)
predict = add_features(predict)

feature_cols = [
    'number_of_total_atoms',
    'percent_atom_al',
    'percent_atom_ga',
    'percent_atom_in',
    'lattice_vector_1_ang',
    'lattice_vector_2_ang',
    'lattice_vector_3_ang',
    'lattice_angle_alpha_degree',
    'lattice_angle_beta_degree',
    'lattice_angle_gamma_degree',
    'lattice_volume',
    'lattice_mean',
    'aspect_ab',
    'aspect_bc',
    'aspect_ac',
    'lattice_anisotropy',
    'lattice_range',
    'atom_entropy',
    'spacegroup_freq'
]

X_train_df = train[feature_cols].replace([np.inf, -np.inf], np.nan)
X_predict_df = predict[feature_cols].replace([np.inf, -np.inf], np.nan)
medians = X_train_df.median().fillna(0.0)
X_train_df = X_train_df.fillna(medians)
X_predict_df = X_predict_df.fillna(medians)
X_train = X_train_df.values.astype(float)
X_predict = X_predict_df.values.astype(float)

param_grid = []
for max_leaf_nodes in [15, 31]:
    for learning_rate in [0.03, 0.1]:
        for l2 in [0.0, 0.1]:
            param_grid.append((max_leaf_nodes, learning_rate, l2))

def cv_score_for_params(X, y_log, params):
    max_leaf_nodes, learning_rate, l2 = params
    kf = KFold(n_splits=3, shuffle=True, random_state=seed)
    scores = []
    for tr_idx, va_idx in kf.split(X):
        model = HistGradientBoostingRegressor(
            loss='squared_error',
            learning_rate=learning_rate,
            max_iter=300,
            max_leaf_nodes=max_leaf_nodes,
            l2_regularization=l2,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=10,
            tol=1e-7,
            random_state=seed
        )
        model.fit(X[tr_idx], y_log[tr_idx])
        pred_log = model.predict(X[va_idx])
        rmse = np.sqrt(mean_squared_error(y_log[va_idx], pred_log))
        scores.append(rmse)
    return float(np.mean(scores))

preds = {}
for target in targets:
    y = train[target].astype(float).values
    y = np.clip(y, 0.0, None)
    y_log = np.log1p(y)
    best_score = None
    best_params = None
    for params in param_grid:
        score = cv_score_for_params(X_train, y_log, params)
        if best_score is None or score < best_score:
            best_score = score
            best_params = params
    max_leaf_nodes, learning_rate, l2 = best_params
    final_model = HistGradientBoostingRegressor(
        loss='squared_error',
        learning_rate=learning_rate,
        max_iter=300,
        max_leaf_nodes=max_leaf_nodes,
        l2_regularization=l2,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=10,
        tol=1e-7,
        random_state=seed
    )
    final_model.fit(X_train, y_log)
    pred_log = final_model.predict(X_predict)
    pred_log = np.clip(pred_log, -50.0, 50.0)
    pred = np.expm1(pred_log)
    pred = np.where(np.isfinite(pred), pred, 0.0)
    pred = np.clip(pred, 0.0, None)
    preds[target] = pred

out = predict[[id_col]].copy()
for target in targets:
    out[target] = preds[target]
out.to_csv('predictions.csv', index=False)
