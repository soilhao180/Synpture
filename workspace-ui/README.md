# workspace-ui

`workspace-ui/` is the official frontend shell for Synpture after the start page.

It is no longer a pure mock preview:

- it boots from `/api/bootstrap`
- it opens real local project history from `/api/runs`
- it starts real pipeline tasks through `/api/tasks/*`
- it polls task progress from `/api/tasks/{task_id}/status`
- it reads and saves supported settings through `/api/settings`

The recommended way to run it is through the main backend:

```powershell
python app.py
```

Then open:

- `http://127.0.0.1:8000`
