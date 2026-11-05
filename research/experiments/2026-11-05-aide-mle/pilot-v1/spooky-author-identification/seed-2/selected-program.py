import json
import os
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.naive_bayes import MultinomialNB
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss
from sklearn.preprocessing import LabelEncoder


def main():
    with open('data/protocol.json', 'r', encoding='utf-8') as f:
        protocol = json.load(f)
    seed = int(protocol.get('seed', 7))
    np.random.seed(seed)
    features = protocol.get('features', ['text'])
    id_out_col = protocol.get('row_id', 'row_id')
    target_cols = protocol.get('target_columns', ['target'])
    output_cols = protocol.get('output_columns', ['row_id', 'EAP', 'HPL', 'MWS'])
    pred_file = protocol.get('prediction_file', 'predict.csv')
    out_file = protocol.get('output_file', 'predictions.csv')
    train_path = os.path.join('data', os.path.basename(protocol.get('training_file', 'train.csv')))
    pred_path = os.path.join('data', os.path.basename(pred_file))
    train = pd.read_csv(train_path)
    pred = pd.read_csv(pred_path)
    target_col = None
    for c in target_cols:
        if c in train.columns:
            target_col = c
            break
    if target_col is None:
        for c in ['target', 'author']:
            if c in train.columns:
                target_col = c
                break
    if target_col is None:
        target_col = train.columns[-1]
    input_id_col = id_out_col
    if input_id_col not in pred.columns:
        if 'id' in pred.columns:
            input_id_col = 'id'
        else:
            input_id_col = pred.columns[0]
    def build_text(df):
        parts = []
        feature_cols = [c for c in features if c in df.columns]
        if not feature_cols:
            feature_cols = [c for c in df.columns if c not in (input_id_col, target_col) and df[c].dtype == object]
        for c in feature_cols:
            parts.append(df[c].fillna('').astype(str))
        if not parts:
            return pd.Series([''] * len(df), index=df.index)
        out = parts[0]
        for s in parts[1:]:
            out = out.str.cat(s, sep=' ')
        return out
    X_train_text = build_text(train)
    X_pred_text = build_text(pred)
    le = LabelEncoder()
    y = le.fit_transform(train[target_col].astype(str).values)
    classes = list(le.classes_)
    n_classes = len(classes)
    label_order = [c for c in output_cols if c != id_out_col]
    if not label_order:
        label_order = [str(c) for c in classes]
    word_vec = TfidfVectorizer(analyzer='word', ngram_range=(1, 3), min_df=2, sublinear_tf=True, strip_accents='unicode', lowercase=True, max_features=200000)
    char_vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 6), min_df=2, sublinear_tf=True, lowercase=True, max_features=400000)
    features_union = FeatureUnion([('word', word_vec), ('char', char_vec)])
    X_train = features_union.fit_transform(X_train_text)
    X_pred = features_union.transform(X_pred_text)
    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=seed)
    folds = list(skf.split(X_train, y))
    best_c = 1.0
    best_loss = np.inf
    for c in [0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]:
        losses = []
        for tr_idx, val_idx in folds:
            clf = LogisticRegression(C=c, solver='lbfgs', max_iter=3000, random_state=seed)
            clf.fit(X_train[tr_idx], y[tr_idx])
            proba = clf.predict_proba(X_train[val_idx])
            losses.append(log_loss(y[val_idx], proba, labels=clf.classes_))
        mean_loss = float(np.mean(losses))
        if mean_loss < best_loss:
            best_loss = mean_loss
            best_c = c
    best_alpha = 0.1
    best_alpha_loss = np.inf
    for alpha in [0.01, 0.03, 0.1, 0.3, 1.0, 3.0]:
        losses = []
        for tr_idx, val_idx in folds:
            clf = MultinomialNB(alpha=alpha)
            clf.fit(X_train[tr_idx], y[tr_idx])
            proba = clf.predict_proba(X_train[val_idx])
            losses.append(log_loss(y[val_idx], proba, labels=clf.classes_))
        mean_loss = float(np.mean(losses))
        if mean_loss < best_alpha_loss:
            best_alpha_loss = mean_loss
            best_alpha = alpha
    best_sgd_alpha = 1e-5
    best_sgd_loss = np.inf
    for alpha in [1e-6, 3e-6, 1e-5, 3e-5, 1e-4, 3e-4]:
        losses = []
        for tr_idx, val_idx in folds:
            clf = SGDClassifier(loss='log_loss', alpha=alpha, max_iter=2000, tol=1e-3, random_state=seed, learning_rate='optimal')
            clf.fit(X_train[tr_idx], y[tr_idx])
            proba = clf.predict_proba(X_train[val_idx])
            losses.append(log_loss(y[val_idx], proba, labels=clf.classes_))
        mean_loss = float(np.mean(losses))
        if mean_loss < best_sgd_loss:
            best_sgd_loss = mean_loss
            best_sgd_alpha = alpha
    oof_lr = np.zeros((X_train.shape[0], n_classes))
    oof_nb = np.zeros((X_train.shape[0], n_classes))
    oof_sgd = np.zeros((X_train.shape[0], n_classes))
    for tr_idx, val_idx in folds:
        clf_lr = LogisticRegression(C=best_c, solver='lbfgs', max_iter=5000, random_state=seed)
        clf_lr.fit(X_train[tr_idx], y[tr_idx])
        proba_lr = clf_lr.predict_proba(X_train[val_idx])
        for j, cls in enumerate(clf_lr.classes_):
            oof_lr[val_idx, cls] = proba_lr[:, j]
        clf_nb = MultinomialNB(alpha=best_alpha)
        clf_nb.fit(X_train[tr_idx], y[tr_idx])
        proba_nb = clf_nb.predict_proba(X_train[val_idx])
        for j, cls in enumerate(clf_nb.classes_):
            oof_nb[val_idx, cls] = proba_nb[:, j]
        clf_sgd = SGDClassifier(loss='log_loss', alpha=best_sgd_alpha, max_iter=2000, tol=1e-3, random_state=seed, learning_rate='optimal')
        clf_sgd.fit(X_train[tr_idx], y[tr_idx])
        proba_sgd = clf_sgd.predict_proba(X_train[val_idx])
        for j, cls in enumerate(clf_sgd.classes_):
            oof_sgd[val_idx, cls] = proba_sgd[:, j]
    best_w = (1.0, 0.0, 0.0)
    best_blend_loss = np.inf
    for w1 in np.arange(0.0, 1.01, 0.05):
        for w2 in np.arange(0.0, 1.01 - w1, 0.05):
            w3 = 1.0 - w1 - w2
            if w3 < -1e-12:
                continue
            p = w1 * oof_lr + w2 * oof_nb + w3 * oof_sgd
            p = np.clip(p, 1e-15, 1.0)
            p = p / p.sum(axis=1, keepdims=True)
            loss = log_loss(y, p, labels=np.arange(n_classes))
            if loss < best_blend_loss:
                best_blend_loss = loss
                best_w = (float(w1), float(w2), float(w3))
    clf_lr = LogisticRegression(C=best_c, solver='lbfgs', max_iter=5000, random_state=seed)
    clf_lr.fit(X_train, y)
    proba_lr = clf_lr.predict_proba(X_pred)
    clf_nb = MultinomialNB(alpha=best_alpha)
    clf_nb.fit(X_train, y)
    proba_nb = clf_nb.predict_proba(X_pred)
    clf_sgd = SGDClassifier(loss='log_loss', alpha=best_sgd_alpha, max_iter=2000, tol=1e-3, random_state=seed, learning_rate='optimal')
    clf_sgd.fit(X_train, y)
    proba_sgd = clf_sgd.predict_proba(X_pred)
    proba = best_w[0] * proba_lr + best_w[1] * proba_nb + best_w[2] * proba_sgd
    proba = np.clip(proba, 1e-15, 1.0)
    proba = proba / proba.sum(axis=1, keepdims=True)
    prob_df = pd.DataFrame(0.0, index=np.arange(len(pred)), columns=label_order)
    for j, cls in enumerate(classes):
        name = str(cls)
        if name in prob_df.columns:
            prob_df[name] = proba[:, j]
        else:
            if len(label_order) == n_classes:
                prob_df[label_order[j]] = proba[:, j]
    probs = np.clip(prob_df.values, 1e-15, 1.0)
    row_sums = probs.sum(axis=1, keepdims=True)
    zero_mask = row_sums[:, 0] <= 0
    if zero_mask.any():
        probs[zero_mask, :] = 1.0 / len(label_order)
        row_sums = probs.sum(axis=1, keepdims=True)
    probs = probs / row_sums
    prob_df = pd.DataFrame(probs, columns=label_order)
    out = pd.DataFrame()
    out[id_out_col] = pred[input_id_col].values
    for c in label_order:
        out[c] = prob_df[c].values
    final_cols = [c for c in output_cols if c in out.columns]
    out = out[final_cols]
    out.to_csv(out_file, index=False)


if __name__ == '__main__':
    main()
