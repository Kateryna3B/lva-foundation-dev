# Картка задачі
- task_id:
- role / actual_model / prompt_version:
- base_commit (повний Git hash):
- mode: review | implement
- branch / worktree:
- goal:
- inputs (paths + hashes за потреби):
- allowed_paths:
- forbidden_changes:
- contract_versions:
- dependencies:
- acceptance_criteria:
- required_tests:
- context_budget: target + justification (estimate, not measured quota)
- output_budget: summary/findings limits; code in patch/files
- retry_policy: collect minimal reproduction after repeated same failure
- checkpoint: files/commit/tests/open findings if interrupted
- usage_evidence: source/value | unknown
- expected_output:
- reviewer / integrator:
- status: PLANNED | RUNNING | BLOCKED | BLOCKED_QUOTA | REVIEW | CHANGES_REQUIRED | ACCEPTED

Незаповнений шаблон не є призначеною задачею. Дозвіл на впровадження конкретних файлів надає інтегратор.
