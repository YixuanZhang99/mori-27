import json
import os
import random
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import GridSearchCV, StratifiedKFold

def find_path(name, default):
    if name is None:
        name = default
    candidates = []
    if os.path.isabs(name):
        candidates.append(name)
    else:
        candidates.append(name)
        candidates.append(os.path.join('data', os.path.basename(name)))
        candidates.append(os.path.join('data', name))
    for p in candidates:
        if os.path.exists(p):
            return p
    fallback = os.path.join('data', os.path.basename(default))
    if os.path.exists(fallback):
        return fallback
    return name

def main():
    random.seed(7)
    np.random.seed(7)
    proto_path = find_path('data/protocol.json', 'data/protocol.json')
    with open(proto_path, 'r', encoding='utf-8') as f:
        protocol = json.load(f)
    seed = int(protocol.get('seed', 7))
    random.seed(seed)
    np.random.seed(seed)
    train_path = find_path(protocol.get('training_file', 'train.csv'), 'train.csv')
    pred_name = protocol.get('prediction_file', protocol.get('predict_file', 'predict.csv'))
    pred_path = find_path(pred_name, 'predict.csv')
    train = pd.read_csv(train_path)
    pred = pd.read_csv(pred_path)
    row_id = protocol.get('row_id', 'row_id')
    features = protocol.get('features', ['text'])
    target_cols = protocol.get('target_columns', ['target'])
    y_col = target_cols[0]
    out_cols = protocol.get('output_columns', [row_id, 'EAP', 'HPL', 'MWS'])
    classes = [c for c in out_cols if c != row_id]
    def make_text(df):
        if len(features) == 1:
            return df[features[0]].fillna('').astype(str)
        return df[features].fillna('').astype(str).agg(' '.join, axis=1)
    X_text = make_text(train)
    P_text = make_text(pred)
    y = train[y_col].astype(str).values
    def make_pipeline(C=1.0, sublinear=True):
        word = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=50000, sublinear_tf=sublinear, strip_accents='unicode', lowercase=True)
        char = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 5), min_df=2, max_features=80000, sublinear_tf=sublinear, lowercase=True)
        feats = FeatureUnion([('word', word), ('char', char)])
        clf = LogisticRegression(solver='lbfgs', max_iter=2000, random_state=seed, C=C)
        return Pipeline([('features', feats), ('clf', clf)])
    Cs = [0.5, 1.0, 2.0]
    sublinear_options = [True, False]
    param_grid = []
    for sl in sublinear_options:
        param_grid.append({'features__word__sublinear_tf': [sl], 'features__char__sublinear_tf': [sl], 'clf__C': Cs})
    cv = StratifiedKFold(n_splits=2, shuffle=True, random_state=seed)
    search = GridSearchCV(make_pipeline(), param_grid=param_grid, scoring='neg_log_loss', cv=cv, n_jobs=1, refit=True, verbose=0)
    search.fit(X_text, y)
    best = search.best_params_
    best_C = best.get('clf__C', 1.0)
    best_sub = best.get('features__word__sublinear_tf', True)
    if isinstance(best_sub, list):
        best_sub = best_sub[0]
    final_pipe = make_pipeline(C=best_C, sublinear=best_sub)
    try:
        calibrated = CalibratedClassifierCV(estimator=final_pipe, method='sigmoid', cv=3)
    except TypeError:
        calibrated = CalibratedClassifierCV(base_estimator=final_pipe, method='sigmoid', cv=3)
    calibrated.fit(X_text, y)
    probs = calibrated.predict_proba(P_text)
    model_classes = list(calibrated.classes_)
    prob_df = pd.DataFrame(probs, columns=model_classes, index=pred.index)
    for c in classes:
        if c not in prob_df.columns:
            prob_df[c] = 0.0
    prob_df = prob_df[classes].astype(float)
    vals = prob_df.values
    vals = np.nan_to_num(vals, nan=0.0)
    vals = np.clip(vals, 0.0, 1.0)
    sums = vals.sum(axis=1)
    zero = sums <= 0
    if zero.any():
        vals[zero, :] = 1.0 / len(classes)
        sums = vals.sum(axis=1)
    vals = vals / sums[:, None]
    out = pred[[row_id]].copy()
    for i, c in enumerate(classes):
        out[c] = vals[:, i]
    output_file = protocol.get('output_file', 'predictions.csv')
    out.to_csv(output_file, index=False)

if __name__ == '__main__':
    main()