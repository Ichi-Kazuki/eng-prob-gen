# ITP Problem Generation Pipeline

TOEFL ITP Grammar の Generator → Reviewer → blind Solver pipeline と、その
validation / provenance / regression tooling を収録しています。Orchestrator は
英文法や問題品質を独自判断せず、Reviewer PASS と3者独立一致を機械的に確認します。

## Requirements

- Python 3.12–3.14
- dependencies in `requirements.lock`

```powershell
python -m pip install -r requirements.lock
```

## Tests

全 unit / contract regression:

```powershell
python -m unittest discover -s tests -v
```

Orchestrator regressions（すべて一時ディレクトリへ出力）:

```powershell
python orchestrator/scripts/run_smoke_test.py "$env:TEMP/itp-smoke.json"
python orchestrator/scripts/run_adversarial_test.py "$env:TEMP/itp-adversarial.json"
python orchestrator/scripts/run_reject_path_test.py "$env:TEMP/itp-reject.json"
python orchestrator/scripts/run_acceptance_tests.py
python agents/toefl_itp_grammar_reviewer/scripts/run_p0_hardening_regression.py "$env:TEMP/itp-prompt-hardening.json"
```

Validator CLI の終了コードは `0=valid`、`1=content/schema/semantic failure`、
`2以上=validator runtime/system failure` です。
