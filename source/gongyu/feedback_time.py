"""Do not relabel an old map transform with a newer odometry timestamp."""
def sample_time(odom_ms,transform_ms):
    return transform_ms if 0<=odom_ms-transform_ms<=200 else None


def aligned_sample(history,now):
    return next((s for s in reversed(history) if 0<=now-s['t']<=.2),None)
