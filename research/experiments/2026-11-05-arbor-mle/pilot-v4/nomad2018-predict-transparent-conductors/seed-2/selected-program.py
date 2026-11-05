import json, os, random, warnings
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor, GradientBoostingRegressor
from sklearn.model_selection import KFold
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

def safe_nonneg(a):
    a = np.asarray(a, dtype=np.float64)
    a = np.nan_to_num(a, nan=0.0, posinf=1e300, neginf=0.0)
    return np.clip(a, 0.0, 1e300)

def rmsle(y_true, y_pred):
    y_true = safe_nonneg(y_true)
    y_pred = safe_nonneg(y_pred)
    return float(np.sqrt(np.mean((np.log1p(y_pred) - np.log1p(y_true)) ** 2)))

def make_onehot():
    try:
        return OneHotEncoder(handle_unknown='ignore', sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown='ignore', sparse=False)

def make_preprocessor(features, scale_numeric):
    categorical_features = [c for c in ['spacegroup'] if c in features]
    numeric_features = [c for c in features if c not in categorical_features]
    num_steps = [('imputer', SimpleImputer(strategy='median'))]
    if scale_numeric:
        num_steps.append(('scaler', StandardScaler()))
    num_pipe = Pipeline(steps=num_steps)
    transformers = []
    if numeric_features:
        transformers.append(('num', num_pipe, numeric_features))
    if categorical_features:
        cat_pipe = Pipeline(steps=[
            ('imputer', SimpleImputer(strategy='most_frequent')),
            ('onehot', make_onehot())
        ])
        transformers.append(('cat', cat_pipe, categorical_features))
    return ColumnTransformer(transformers=transformers, remainder='drop')

def make_model(model_name, seed):
    if model_name == 'ridge':
        return Ridge(alpha=10.0)
    if model_name == 'rf':
        return RandomForestRegressor(n_estimators=160, min_samples_leaf=2, max_features=0.8, random_state=seed, n_jobs=-1)
    if model_name == 'et':
        return ExtraTreesRegressor(n_estimators=160, min_samples_leaf=2, max_features=0.8, random_state=seed, n_jobs=-1)
    if model_name == 'gbr':
        return GradientBoostingRegressor(n_estimators=160, learning_rate=0.05, max_depth=3, random_state=seed)
    raise ValueError(model_name)

def make_pipeline(model_name, features, seed):
    return Pipeline(steps=[
        ('pre', make_preprocessor(features, model_name == 'ridge')),
        ('model', make_model(model_name, seed))
    ])

def inverse_target(pred, transform):
    pred = np.asarray(pred, dtype=np.float64)
    if transform == 'log1p':
        pred = np.clip(pred, -50.0, 50.0)
        pred = np.expm1(pred)
    return safe_nonneg(pred)

def main():
    random.seed(7)
    np.random.seed(7)
    with open(os.path.join('data', 'protocol.json'), 'r') as f:
        protocol = json.load(f)
    seed = int(protocol.get('seed', 7))
    random.seed(seed)
    np.random.seed(seed)
    train_path = os.path.join('data', protocol.get('training_file', 'train.csv'))
    predict_path = os.path.join('data', protocol.get('prediction_file', 'predict.csv'))
    output_path = protocol.get('output_file', 'predictions.csv')
    row_id_col = protocol.get('row_id', 'row_id')
    target_cols = protocol['target_columns']
    features = protocol['features']
    train = pd.read_csv(train_path)
    predict = pd.read_csv(predict_path)
    X_train = train[features].copy()
    X_predict = predict[features].copy()
    model_names = ['ridge', 'rf', 'et', 'gbr']
    transforms = ['raw', 'log1p']
    candidates = [(m, t) for m in model_names for t in transforms]
    n_repeats = 2
    n_splits = 3
    top_k = 4
    final_specs = {}
    for target_index, target in enumerate(target_cols):
        y = safe_nonneg(train[target].values)
        n = len(y)
        rep_folds = []
        for rep in range(n_repeats):
            kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed + 1000 * rep + 17 * target_index)
            rep_folds.append(list(kf.split(X_train)))
        baseline_scores = []
        for rep, folds in enumerate(rep_folds):
            oof_base = np.full(n, np.nan)
            for tr_idx, va_idx in folds:
                c = np.expm1(np.mean(np.log1p(y[tr_idx])))
                oof_base[va_idx] = c
            baseline_scores.append(rmsle(y, oof_base))
        baseline_score = float(np.mean(baseline_scores))
        stored = []
        for ci, (model_name, transform) in enumerate(candidates):
            oof_sum = np.zeros(n)
            per_rep_scores = []
            for rep, folds in enumerate(rep_folds):
                oof = np.full(n, np.nan)
                for fold_idx, (tr_idx, va_idx) in enumerate(folds):
                    y_fit = y[tr_idx] if transform == 'raw' else np.log1p(y[tr_idx])
                    pipe = make_pipeline(model_name, features, seed + 100 * rep + 10 * fold_idx + ci)
                    pipe.fit(X_train.iloc[tr_idx], y_fit)
                    pred = inverse_target(pipe.predict(X_train.iloc[va_idx]), transform)
                    oof[va_idx] = pred
                per_rep_scores.append(rmsle(y, oof))
                oof_sum += oof
            oof_avg = oof_sum / float(n_repeats)
            score = float(np.mean(per_rep_scores))
            stored.append({'model': model_name, 'transform': transform, 'score': score, 'oof': oof_avg, 'ci': ci})
        stored.sort(key=lambda d: d['score'])
        selected = stored[:min(top_k, len(stored))]
        if len(selected) == 1:
            weights = np.array([1.0])
            blend_score = selected[0]['score']
        else:
            P = np.column_stack([d['oof'] for d in selected])
            def objective(w):
                w = np.maximum(np.asarray(w, dtype=np.float64), 0.0)
                s = float(np.sum(w))
                if s <= 1e-12:
                    return 1e6
                w = w / s
                pred = safe_nonneg(P.dot(w))
                return float(np.mean((np.log1p(pred) - np.log1p(y)) ** 2))
            initial = np.ones(len(selected), dtype=np.float64) / float(len(selected))
            bounds = [(0.0, 1.0)] * len(selected)
            cons = ({'type': 'eq', 'fun': lambda w: float(np.sum(w) - 1.0)},)
            res = minimize(objective, initial, method='SLSQP', bounds=bounds, constraints=cons, options={'maxiter': 200, 'ftol': 1e-8})
            if res.success:
                weights = np.maximum(np.asarray(res.x, dtype=np.float64), 0.0)
                s = float(np.sum(weights))
                if s > 1e-12:
                    weights = weights / s
                else:
                    weights = initial
            else:
                weights = initial
            blend_score = rmsle(y, P.dot(weights))
        best_single_score = selected[0]['score']
        if best_single_score < blend_score - 1e-12:
            weights = np.zeros(len(selected), dtype=np.float64)
            weights[0] = 1.0
            blend_score = best_single_score
        full_constant = float(safe_nonneg([np.expm1(np.mean(np.log1p(y)))])[0])
        if baseline_score < blend_score - 1e-12:
            final_specs[target] = {'mode': 'baseline', 'constant': full_constant}
        else:
            final_specs[target] = {'mode': 'blend', 'selected': selected, 'weights': weights}
    preds = pd.DataFrame()
    preds[row_id_col] = predict[row_id_col].values
    for target in target_cols:
        spec = final_specs[target]
        if spec['mode'] == 'baseline':
            pred = np.full(len(predict), spec['constant'], dtype=np.float64)
        else:
            total = np.zeros(len(predict), dtype=np.float64)
            for d, w in zip(spec['selected'], spec['weights']):
                if w <= 1e-12:
                    continue
                y = safe_nonneg(train[target].values)
                y_fit = y if d['transform'] == 'raw' else np.log1p(y)
                pipe = make_pipeline(d['model'], features, seed + 5000 + d['ci'])
                pipe.fit(X_train, y_fit)
                p = inverse_target(pipe.predict(X_predict), d['transform'])
                total += w * p
            pred = safe_nonneg(total)
        preds[target] = safe_nonneg(pred)
    out_cols = [row_id_col] + target_cols
    preds = preds[out_cols]
    preds.to_csv(output_path, index=False)

if __name__ == '__main__':
    main()