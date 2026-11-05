import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss

def make_model(C, seed):
    try:
        clf = LogisticRegression(C=C, solver='lbfgs', max_iter=5000, random_state=seed, multi_class='multinomial')
    except TypeError:
        clf = LogisticRegression(C=C, solver='lbfgs', max_iter=5000, random_state=seed)
    return make_pipeline(StandardScaler(), clf)

def main():
    np.random.seed(7)
    with open('data/protocol.json', 'r') as f:
        proto = json.load(f)
    seed = int(proto.get('seed', 7))
    features = list(proto['features'])
    target_col = proto.get('target_columns', ['target'])[0]
    output_cols = list(proto['output_columns'])
    row_id_col = proto.get('row_id', 'row_id')
    train = pd.read_csv('data/train.csv')
    predict = pd.read_csv('data/predict.csv')
    X = train[features].to_numpy(dtype=np.float64)
    y = train[target_col].astype(str).to_numpy()
    Xp = predict[features].to_numpy(dtype=np.float64)
    min_count = int(pd.Series(y).value_counts().min())
    if min_count >= 2:
        n_splits = max(2, min(5, min_count))
    else:
        n_splits = 0
    Cs = [0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]
    best_c = 1.0
    best_loss = float('inf')
    if n_splits >= 2:
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        for C in Cs:
            losses = []
            for tr, va in skf.split(X, y):
                model = make_model(C, seed)
                model.fit(X[tr], y[tr])
                proba = model.predict_proba(X[va])
                clf = model.steps[-1][1]
                losses.append(log_loss(y[va], proba, labels=clf.classes_))
            loss = float(np.mean(losses))
            if loss < best_loss:
                best_loss = loss
                best_c = C
    model = make_model(best_c, seed)
    model.fit(X, y)
    proba = model.predict_proba(Xp)
    final_clf = model.steps[-1][1]
    classes = list(final_clf.classes_)
    class_to_idx = {c: i for i, c in enumerate(classes)}
    prob_cols = [c for c in output_cols if c != row_id_col]
    mat = np.zeros((len(predict), len(prob_cols)), dtype=np.float64)
    for j, col in enumerate(prob_cols):
        if col in class_to_idx:
            mat[:, j] = proba[:, class_to_idx[col]]
    row_sums = mat.sum(axis=1)
    for i in range(mat.shape[0]):
        if row_sums[i] > 0:
            mat[i, :] = mat[i, :] / row_sums[i]
        elif mat.shape[1] > 0:
            mat[i, 0] = 1.0
    out = pd.DataFrame(mat, columns=prob_cols)
    out.insert(0, row_id_col, predict[row_id_col].to_numpy())
    out = out[output_cols]
    out.to_csv('predictions.csv', index=False)

if __name__ == '__main__':
    main()
