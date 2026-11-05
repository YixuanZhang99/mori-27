import json
import os

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline


def main():
    data_dir = "data"
    with open(os.path.join(data_dir, "protocol.json"), "r", encoding="utf-8") as f:
        protocol = json.load(f)

    train_path = os.path.join(data_dir, protocol.get("training_file", "train.csv"))
    pred_path = os.path.join(data_dir, protocol.get("prediction_file", "predict.csv"))
    out_path = protocol.get("output_file", "predictions.csv")
    row_id_col = protocol.get("row_id", "row_id")
    features = protocol.get("features", ["text"])
    target_cols = protocol.get("target_columns", ["target"])
    output_cols = protocol.get("output_columns", [row_id_col, "EAP", "HPL", "MWS"])
    seed = int(protocol.get("seed", 7))

    train = pd.read_csv(train_path)
    pred = pd.read_csv(pred_path)

    text_col = features[0]
    target_col = target_cols[0]

    X_train_text = train[text_col].fillna("").astype(str)
    X_pred_text = pred[text_col].fillna("").astype(str)
    y = train[target_col].astype(str)

    word_vectorizer = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        min_df=3,
        max_df=0.95,
        sublinear_tf=True,
        strip_accents="unicode",
        lowercase=True,
    )
    char_vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 5),
        min_df=3,
        max_df=0.95,
        sublinear_tf=True,
        strip_accents="unicode",
        lowercase=True,
    )
    vectorizer = FeatureUnion([
        ("word", word_vectorizer),
        ("char", char_vectorizer),
    ])

    base_clf = LogisticRegression(
        solver="lbfgs",
        random_state=seed,
        max_iter=3000,
        C=1.0,
        class_weight=None,
    )
    base_pipeline = Pipeline([
        ("features", vectorizer),
        ("clf", base_clf),
    ])

    try:
        calibrated_clf = CalibratedClassifierCV(
            estimator=base_pipeline,
            method="sigmoid",
            cv=3,
            n_jobs=1,
        )
        calibrated_clf.fit(X_train_text, y)
    except TypeError:
        calibrated_clf = CalibratedClassifierCV(
            base_estimator=base_pipeline,
            method="sigmoid",
            cv=3,
            n_jobs=1,
        )
        calibrated_clf.fit(X_train_text, y)

    proba = calibrated_clf.predict_proba(X_pred_text)
    classes = list(calibrated_clf.classes_)

    out = pd.DataFrame({row_id_col: pred[row_id_col].values})
    for col in output_cols:
        if col == row_id_col:
            continue
        if col in classes:
            out[col] = proba[:, classes.index(col)]
        else:
            out[col] = 0.0

    out = out[output_cols]

    prob_cols = [c for c in output_cols if c != row_id_col]
    vals = out[prob_cols].to_numpy(dtype=float)
    vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
    vals = np.clip(vals, 0.0, 1.0)

    sums = vals.sum(axis=1, keepdims=True)
    zero_mask = sums[:, 0] <= 0.0
    if np.any(zero_mask):
        vals[zero_mask, :] = 1.0 / len(prob_cols)
        sums = vals.sum(axis=1, keepdims=True)

    vals = vals / sums
    out[prob_cols] = vals
    out.to_csv(out_path, index=False)


if __name__ == "__main__":
    main()
