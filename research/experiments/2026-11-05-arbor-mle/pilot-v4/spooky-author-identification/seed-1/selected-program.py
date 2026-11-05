import os
import json
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.model_selection import StratifiedKFold, GridSearchCV
from sklearn.metrics import log_loss
from sklearn.preprocessing import LabelEncoder

SEED = 7
np.random.seed(SEED)

def main():
    base = os.getcwd()
    data_dir = os.path.join(base, 'data')
    with open(os.path.join(data_dir, 'protocol.json'), 'r', encoding='utf-8') as f:
        protocol = json.load(f)
    train_path = os.path.join(data_dir, protocol.get('training_file', 'train.csv'))
    pred_path = os.path.join(data_dir, protocol.get('prediction_file', 'predict.csv'))
    out_path = os.path.join(base, protocol.get('output_file', 'predictions.csv'))
    train = pd.read_csv(train_path)
    predict = pd.read_csv(pred_path)
    features = protocol.get('features', ['text'])
    target_cols = protocol.get('target_columns', ['target'])
    target_col = target_cols[0]
    if target_col not in train.columns:
        for cand in ['target', 'author', 'label', 'class']:
            if cand in train.columns:
                target_col = cand
                break
    if target_col not in train.columns:
        raise ValueError('target column not found')
    row_id = protocol.get('row_id', 'row_id')
    if row_id not in predict.columns:
        if 'id' in predict.columns:
            predict[row_id] = predict['id']
        else:
            predict[row_id] = np.arange(len(predict))
    feature_cols = [c for c in features if c in train.columns and c in predict.columns]
    if not feature_cols:
        for cand in ['text', 'sentence', 'content']:
            if cand in train.columns and cand in predict.columns:
                feature_cols = [cand]
                break
    if not feature_cols:
        raise ValueError('feature column not found')
    def make_text(df):
        if len(feature_cols) == 1:
            return df[feature_cols[0]].fillna('').astype(str)
        return df[feature_cols].fillna('').astype(str).agg(' '.join, axis=1)
    X_text = make_text(train)
    X_pred_text = make_text(predict)
    y_raw = train[target_col].astype(str).values
    le = LabelEncoder()
    y = le.fit_transform(y_raw)
    out_cols = protocol.get('output_columns', ['row_id', 'EAP', 'HPL', 'MWS'])
    prob_cols = [c for c in out_cols if c != row_id]
    class_to_idx = {str(c): i for i, c in enumerate(le.classes_)}
    word_tfidf = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=2, lowercase=True)
    char_tfidf = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 5), sublinear_tf=True, min_df=2, lowercase=True)
    feature_union = FeatureUnion([('word', word_tfidf), ('char', char_tfidf)])
    clf = LogisticRegression(solver='lbfgs', class_weight='balanced', random_state=SEED, max_iter=2000)
    pipe = Pipeline([('features', feature_union), ('clf', clf)])
    n_splits = 5
    if len(np.unique(y)) > 1:
        n_splits = min(5, int(np.min(np.bincount(y))))
    if n_splits < 2:
        n_splits = 2
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=SEED)
    param_grid = {'clf__C': [0.5, 1.0, 2.0, 4.0]}
    try:
        grid = GridSearchCV(pipe, param_grid, scoring='neg_log_loss', cv=cv, n_jobs=1, refit=True, error_score='raise')
        grid.fit(X_text, y)
        best = grid.best_estimator_
    except Exception:
        best_C = 1.0
        best_score = None
        for C in [0.5, 1.0, 2.0, 4.0]:
            pipe.set_params(clf__C=C)
            scores = []
            for tr, va in cv.split(X_text, y):
                try:
                    pipe.fit(X_text.iloc[tr], y[tr])
                    prob = pipe.predict_proba(X_text.iloc[va])
                    scores.append(-log_loss(y[va], prob, labels=np.arange(len(le.classes_))))
                except Exception:
                    scores.append(-1e9)
            sc = float(np.mean(scores))
            if best_score is None or sc > best_score:
                best_score = sc
                best_C = C
        pipe.set_params(clf__C=best_C)
        pipe.fit(X_text, y)
        best = pipe
    prob = best.predict_proba(X_pred_text)
    out = pd.DataFrame()
    out[row_id] = predict[row_id].values
    for j, col in enumerate(prob_cols):
        if col in class_to_idx:
            idx = class_to_idx[col]
        else:
            idx = j if j < prob.shape[1] else prob.shape[1] - 1
        out[col] = prob[:, idx]
    vals = out[prob_cols].values.astype(float)
    vals = np.nan_to_num(vals, nan=1.0 / len(prob_cols), posinf=0.0, neginf=0.0)
    vals = np.clip(vals, 0.0, 1.0)
    s = vals.sum(axis=1, keepdims=True)
    s[s <= 0] = 1.0
    vals = vals / s
    out[prob_cols] = vals
    out = out[out_cols]
    out.to_csv(out_path, index=False)

if __name__ == '__main__':
    main()
