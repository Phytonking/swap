def clamp(value, lo, hi):
    """Clamp value into the inclusive [lo, hi] range."""
    return max(lo, min(hi, value))
