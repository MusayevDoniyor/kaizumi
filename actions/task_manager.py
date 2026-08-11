# actions/task_manager.py
# Kaizumi — Agent Task Status & Control

from agent.task_queue import get_queue


def task_manager(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Query or control background agent tasks.
    actions: status | list | cancel"""
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()
    queue  = get_queue()

    if action in ("status", "check"):
        task_id = str(params.get("task_id", "")).strip()
        if not task_id:
            return "Please provide a task_id, sir."
        info = queue.get_status(task_id)
        if not info:
            return f"No task found with ID {task_id}, sir."
        status = info["status"]
        if status == "completed" and info.get("result"):
            return f"Task {task_id} completed. Result: {info['result']}"
        if status == "failed":
            return f"Task {task_id} failed. {info.get('error', '')}"
        if status == "cancelled":
            return f"Task {task_id} was cancelled."
        return f"Task {task_id} is {status}. Goal: {info['goal']}"

    if action in ("cancel", "stop", "abort"):
        task_id = str(params.get("task_id", "")).strip()
        if not task_id:
            return "Please provide a task_id to cancel, sir."
        if queue.cancel(task_id):
            return f"Task {task_id} cancelled."
        return f"Could not cancel task {task_id}. It may be already finished."

    if action in ("list", "all", "tasks"):
        tasks = queue.get_all_statuses()
        if not tasks:
            return "No background tasks, sir."
        lines = []
        for t in tasks[-8:]:
            lines.append(f"{t['task_id']}: {t['status']} — {t['goal']}")
        return "Tasks: " + " | ".join(lines)

    return f"Unknown task action: {action}, sir."
