def smoothstep(progress: float) -> float:
    value = max(0.0, min(1.0, progress))
    return value * value * (3 - 2 * value)
