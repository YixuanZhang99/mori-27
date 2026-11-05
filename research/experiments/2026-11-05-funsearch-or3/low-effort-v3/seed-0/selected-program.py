def priority(item, bins):
    scores = []
    threshold = item * 0.25
    penalty = item * 0.1
    for b in bins:
        if b < item:
            scores.append(float('-inf'))
        elif b == item:
            scores.append(1e18)
        else:
            r = b - item
            score = -r
            if r < threshold:
                score -= penalty
            scores.append(score)
    return scores