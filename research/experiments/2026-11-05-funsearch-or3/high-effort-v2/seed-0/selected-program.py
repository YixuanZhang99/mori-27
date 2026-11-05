def priority(item, bins):
    feasible = bins >= item
    scores = -(bins - item)
    return np.where(feasible, scores, np.finfo(float).min)