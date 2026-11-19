"""Score all registered tasks, including those left incomplete."""


def summarize_tasks(expected_task_ids, task_completed):
    expected = sorted(set(expected_task_ids))
    unexpected = set(task_completed).difference(expected)
    if unexpected:
        raise ValueError(f"Unexpected completed tasks: {sorted(unexpected)}")
    missing = [task for task in expected if task not in task_completed]
    late = [
        task for task in expected
        if task in task_completed and not task_completed[task]["on_time"]
    ]
    return {
        "expected_task_ids": expected,
        "completed": len(task_completed),
        "on_time": len(task_completed) - len(late),
        "total": len(expected),
        "missing_task_ids": missing,
        "late_task_ids": late,
    }
