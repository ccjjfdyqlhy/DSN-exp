# Wiring W7: the learn loop's second half. learn -> finetune -> promote ->
# active slot, all reachable from the CLI; a gate report is a valid promotion
# evidence (the layered-judge score has no framework producer -- that path
# deadlocked the whole promotion flow).

import json
from pathlib import Path

from aicf.harness.cli.main import main as cli_main


def _seed_succeeded_job(db: Path):
    from aicf.infra.finetune.base import TrainJob, TrainSpec
    from aicf.infra.finetune.runner import JobState
    from aicf.infra.finetune.store import FinetuneStore

    store = FinetuneStore(str(db))
    spec = TrainSpec(base_model='stub-8b', dataset_path='sft/train.jsonl',
                     output_dir='out/adapter')
    job = TrainJob(id='job-w7', spec=spec, state=JobState.SUCCEEDED,
                   adapter_path='out/adapter/adapter.safetensors')
    store.save_job(job)
    return job.id


def test_finetune_status_lists_jobs(tmp_path: Path):
    db = tmp_path / 'finetune.db'
    job_id = _seed_succeeded_job(db)
    code = cli_main(['finetune', 'status', '--db', str(db)])
    assert code == 0


def test_promote_with_gate_report_reaches_active_slot(tmp_path: Path):
    db = tmp_path / 'finetune.db'
    job_id = _seed_succeeded_job(db)
    gate_report = {'passed': True, 'outcomes': [
        {'name': 'quality', 'verdict': 'pass'},
        {'name': 'safety', 'verdict': 'pass'}]}
    report_path = tmp_path / 'gate.json'
    report_path.write_text(json.dumps(gate_report), encoding='utf-8')

    code = cli_main(['finetune', 'promote', '--job', job_id, '--slot', 'default',
                     '--gate-report', str(report_path), '--db', str(db)])
    assert code == 0

    active_path = tmp_path / 'active.json'
    code = cli_main(['finetune', 'active', '--slot', 'default',
                     '--db', str(db), '--json'])
    assert code == 0  # active() reads back the slot the promote wrote


def test_promote_with_failing_gate_report_is_refused(tmp_path: Path):
    db = tmp_path / 'finetune.db'
    job_id = _seed_succeeded_job(db)
    report_path = tmp_path / 'gate.json'
    report_path.write_text(json.dumps({'passed': False}), encoding='utf-8')
    code = cli_main(['finetune', 'promote', '--job', job_id, '--slot', 'default',
                     '--gate-report', str(report_path), '--db', str(db)])
    assert code == 2  # the policy refused: gate not passed


def test_promote_without_evidence_still_demands_score_or_gate(tmp_path: Path):
    db = tmp_path / 'finetune.db'
    job_id = _seed_succeeded_job(db)
    code = cli_main(['finetune', 'promote', '--job', job_id, '--slot', 'default',
                     '--db', str(db)])
    assert code == 2  # no score, no gate report: no promotion


def test_rollback_restores_the_previous_slot(tmp_path: Path):
    db = tmp_path / 'finetune.db'
    job_id = _seed_succeeded_job(db)
    report_path = tmp_path / 'gate.json'
    report_path.write_text(json.dumps({'passed': True}), encoding='utf-8')
    cli_main(['finetune', 'promote', '--job', job_id, '--slot', 'default',
              '--gate-report', str(report_path), '--db', str(db)])
    code = cli_main(['finetune', 'rollback', '--slot', 'default', '--db', str(db)])
    assert code == 1  # single promotion: no previous version to roll back to
    import json as _json
    from aicf.infra.finetune.store import FinetuneStore

    assert FinetuneStore(str(db)).active('default') == job_id  # slot unchanged
