"""Frozen public-training splits for the explicitly supported CSV MLE pilot tasks.

Official private labels, leaderboard files and graders are never read here. The
only candidate-visible data are a training subset and a shuffled, anonymous
prediction table. Local held-out labels stay in this trusted Python process.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from pathlib import Path

PROTOCOL = "mle-public-train-composed-v1"
TASK_SPECS = {
    "spooky-author-identification": {"kind": "classification", "target": "author"},
    "leaf-classification": {"kind": "classification", "target": "species"},
    "nomad2018-predict-transparent-conductors": {
        "kind": "regression", "targets": ["formation_energy_ev_natom", "bandgap_energy_ev"]},
}
SPLITS = ("dev", "calibration", "admission", "final_audit")


def digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_digest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("public input must be a regular, non-symlink file")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    file_digest(path)
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        if not columns or len(set(columns)) != len(columns):
            raise ValueError("CSV must contain unique columns")
        rows = list(reader)
    if not rows or any(set(row) != set(columns) or any(value is None for value in row.values())
                       for row in rows):
        raise ValueError("CSV must contain complete rows")
    return columns, rows


def write_csv(path, columns, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


class PublicTrainBundle:
    def __init__(self, public_root, output_root, task_id, seed):
        if task_id not in TASK_SPECS:
            raise ValueError("composed MLE pilot supports only the three declared CSV tasks")
        if type(seed) is not int or seed < 0:
            raise ValueError("split seed must be a nonnegative integer")
        self.task_id, self.seed = task_id, seed
        self.spec = TASK_SPECS[task_id]
        self.public_root, self.output_root = Path(public_root).resolve(), Path(output_root).resolve()
        if self.output_root == self.public_root or self.public_root in self.output_root.parents:
            raise ValueError("derived inputs must be stored outside original public data")
        self.source_hashes = {name: file_digest(self.public_root / name)
                              for name in ("train.csv", "test.csv", "sample_submission.csv")}
        train_columns, train = read_csv(self.public_root / "train.csv")
        test_columns, test = read_csv(self.public_root / "test.csv")
        sample_columns, self.sample = read_csv(self.public_root / "sample_submission.csv")
        if "id" not in train_columns or "id" not in test_columns or sample_columns[0] != "id":
            raise ValueError("supported CSV tasks require an id column")
        for rows in (train, test, self.sample):
            if len({row["id"] for row in rows}) != len(rows):
                raise ValueError("CSV row IDs must be unique")
        if [row["id"] for row in test] != [row["id"] for row in self.sample]:
            raise ValueError("sample and public test row ordering/identity must match")
        self.output_columns = sample_columns[1:]
        targets = ([self.spec["target"]] if self.spec["kind"] == "classification"
                   else self.spec["targets"])
        self.features = [name for name in train_columns if name not in {"id", *targets}]
        if not self.features or set(test_columns) != {"id", *self.features} or not set(targets) <= set(train_columns):
            raise ValueError("unexpected training/test schema")
        if {"row_id", "target"} & set(self.features):
            raise ValueError("public feature names collide with the prediction protocol")
        if self.spec["kind"] == "classification":
            if set(row[targets[0]] for row in train) != set(self.output_columns):
                raise ValueError("sample output classes differ from public training labels")
        elif self.output_columns != targets:
            raise ValueError("sample regression columns differ from the declared task")
        self.labels = {}
        for index, row in enumerate(train):
            self.labels[index] = (row[targets[0]] if self.spec["kind"] == "classification" else
                                  [float(row[name]) for name in targets])
            if self.spec["kind"] == "regression" and any(
                    not math.isfinite(value) or value < 0 for value in self.labels[index]):
                raise ValueError("RMSLE labels must be finite and nonnegative")
        groups = {}
        for index, label in self.labels.items():
            groups.setdefault(label if type(label) is str else "all", []).append(index)
        rng = random.Random(seed)
        self.indices = {split: [] for split in ("train", *SPLITS)}
        for group in sorted(groups):
            indices = groups[group]
            if len(indices) < 5:
                raise ValueError("each class needs at least five public rows for disjoint splits")
            rng.shuffle(indices)
            count = max(1, len(indices) // 10)
            for offset, split in enumerate(SPLITS):
                self.indices[split].extend(indices[offset * count:(offset + 1) * count])
            self.indices["train"].extend(indices[4 * count:])
        # Interleave every held-out subset and official public test; neither IDs
        # nor order reveal which local score each row contributes to.
        mixed = [("local", index) for split in SPLITS for index in self.indices[split]]
        mixed += [("official", index) for index in range(len(test))]
        rng.shuffle(mixed)
        self.local_ids, self.test_ids, evaluation_rows = {}, {}, []
        for number, (origin, index) in enumerate(mixed):
            row_id = f"r{number:08d}"
            original = train[index] if origin == "local" else test[index]
            evaluation_rows.append({"row_id": row_id, **{name: original[name] for name in self.features}})
            (self.local_ids if origin == "local" else self.test_ids)[index] = row_id
        training_rows = []
        for number, index in enumerate(self.indices["train"]):
            values = {"target": self.labels[index]} if self.spec["kind"] == "classification" else dict(
                zip(self.output_columns, self.labels[index]))
            training_rows.append({"row_id": f"t{number:08d}",
                **{name: train[index][name] for name in self.features}, **values})
        self.protocol = {"protocol": PROTOCOL, "task": task_id, "kind": self.spec["kind"],
            "training_file": "train.csv", "prediction_file": "predict.csv",
            "output_file": "predictions.csv", "row_id": "row_id", "features": self.features,
            "target_columns": ["target"] if self.spec["kind"] == "classification" else self.output_columns,
            "output_columns": ["row_id", *self.output_columns], "seed": seed}
        self.output_root.mkdir(parents=True, exist_ok=True)
        expected = {"train.csv", "predict.csv", "protocol.json"}
        if set(path.name for path in self.output_root.iterdir()) - expected:
            raise ValueError("derived input directory contains unexpected files")
        # Reconstructing a finished run is allowed only when exact input bytes
        # agree. Do not silently overwrite modified inputs.
        import io
        for name, columns, rows in (("train.csv", ["row_id", *self.features, *self.protocol["target_columns"]], training_rows),
                                    ("predict.csv", ["row_id", *self.features], evaluation_rows)):
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader(); writer.writerows(rows)
            self._create_exact(self.output_root / name, stream.getvalue().encode())
        self._create_exact(self.output_root / "protocol.json", (json.dumps(self.protocol, sort_keys=True) + "\n").encode())
        self.input_hashes = {name: file_digest(self.output_root / name) for name in sorted(expected)}
        self.contexts = {split: digest({"protocol": PROTOCOL, "source": self.source_hashes,
            "inputs": self.input_hashes, "rows": [(self.local_ids[index], self.labels[index])
            for index in self.indices[split]]}) for split in SPLITS}
        self.manifest = {"protocol": PROTOCOL, "task_id": task_id, "seed": seed,
            "features": "CSV only; image/geometry auxiliary files excluded", "source_sha256": self.source_hashes,
            "input_sha256": self.input_hashes, "split_contexts": self.contexts,
            "split_counts": {key: len(value) for key, value in self.indices.items()},
            "official_test_rows": len(test), "scoring": "accuracy/negative_log_loss" if self.spec["kind"] == "classification"
            else "negative_mean_absolute_log_error/negative_mean_target_RMSLE"}
        self.identity = digest(self.manifest)
        self.expected_ids = {row["row_id"] for row in evaluation_rows}

    @staticmethod
    def _create_exact(path, content):
        if path.exists():
            if path.is_symlink() or path.read_bytes() != content:
                raise ValueError("derived public inputs changed")
        else:
            with path.open("xb") as stream:
                stream.write(content)

    def validate(self):
        if any(file_digest(self.public_root / name) != sha for name, sha in self.source_hashes.items()) \
                or any(file_digest(self.output_root / name) != sha for name, sha in self.input_hashes.items()):
            raise ValueError("public dataset content changed")

    def predictions(self, path):
        columns, rows = read_csv(path)
        if columns != ["row_id", *self.output_columns] or len(rows) != len(self.expected_ids):
            raise ValueError("prediction schema/row count differs from the frozen protocol")
        result = {}
        for row in rows:
            row_id = row["row_id"]
            if row_id not in self.expected_ids or row_id in result:
                raise ValueError("prediction IDs must exactly cover the anonymous input")
            values = [float(row[name]) for name in self.output_columns]
            if any(not math.isfinite(value) or value < 0 for value in values):
                raise ValueError("predictions must be finite and nonnegative")
            if self.spec["kind"] == "classification" and (
                    any(value > 1 for value in values) or abs(sum(values) - 1) > 1e-6):
                raise ValueError("class probabilities must be normalized")
            result[row_id] = values
        return result

    def score(self, predictions, split):
        indices = self.indices[split]
        if self.spec["kind"] == "classification":
            positions = {name: index for index, name in enumerate(self.output_columns)}
            pairs = [(predictions[self.local_ids[index]], positions[self.labels[index]]) for index in indices]
            if split == "dev":
                return sum(max(range(len(values)), key=values.__getitem__) == target for values, target in pairs) / len(pairs)
            return sum(math.log(max(values[target], 1e-15)) for values, target in pairs) / len(pairs)
        errors = [[math.log1p(actual) - math.log1p(predicted) for actual, predicted in
                   zip(self.labels[index], predictions[self.local_ids[index]])] for index in indices]
        if split == "dev":
            return -sum(abs(value) for row in errors for value in row) / (len(errors) * len(self.output_columns))
        return -sum(math.sqrt(sum(row[column] ** 2 for row in errors) / len(errors))
                    for column in range(len(self.output_columns))) / len(self.output_columns)

    def submission(self, predictions, destination):
        self.validate()
        rows = [{"id": sample["id"], **dict(zip(self.output_columns, predictions[self.test_ids[index]]))}
                for index, sample in enumerate(self.sample)]
        write_csv(destination, ["id", *self.output_columns], rows)
