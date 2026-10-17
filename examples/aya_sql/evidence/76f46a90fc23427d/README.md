# Actual SQL workflow experiment

Run `76f46a90fc23427d` used the adapter at `9d2f8ac91fc115bcf78ecb5b08d750e68676cb52`.
The controller ran native Hermes episodes in OpenShell and scored their SQL with a fixed independent evaluator.
The model was Crusoe-hosted `deepseek-ai/DeepSeek-V4-Pro`.

| Stage | Measured result |
| --- | --- |
| Bare baseline | 36/36 development checks |
| Initial workflow v0 | 36/36 development checks |
| Proposed workflow v1 | 36/36 development checks |
| Actual RHI comparisons | Both ties; no workflow beat the bare reference |
| Independent selection | Retained v0 |
| Final held-out evaluation | Selected v0 passed 36/36 |
| Separate supervised training test | Crusoe reported success and 10,568 trained tokens |

There is no demonstrated accuracy improvement. The run proves a real proposal,
execution, comparison, and rejection path. Both development native audits recorded
one session and zero child sessions. The proposed workflow requested parallel
specialists despite the fixed execution boundary; its text alone is not evidence
that those agents ran.

The actual RHI proposal used response `37998c5e287748c4b0a56a3d08434f76`.
Its two comparison responses were `e4cc7180d3584ca999553fb146a3662e` and
`d8f2cb37f4ab4d14967ae3c943826ffd`. The three calls used 14,673 tokens.
Provider cost was not estimated; it is recorded as `null`.

The controller then submitted a separate supervised integration test for
`Qwen/Qwen3.5-9B`: ten verified development training rows, two development
validation rows, and one epoch. Langfuse API readback verified the source records.
The receipt identifies successful job `ftjob-d9d6409d3a2b4c67adebb74d0398064c`
and checkpoint `ftmodel-cee03aea-b639-4bd6-bd18-40412f3713ac`.

This is final-answer distillation from a different teacher model. It is not a
MASS winning-teacher training round: `beats_reference` was false. It does not
reproduce full trajectory ranking or the paper's same-model weight cycle.
No deployment or evaluation of the trained checkpoint is claimed here.

The snapshot includes public task inputs, actual development queries and scores,
workflow versions, RHI prompts and final model outputs, independent selection,
and provider training receipts. It excludes held-out question content, private
reasoning, credentials, and native raw transcripts.
Host paths were replaced with placeholders. `SHA256SUMS.json` hashes these public
copies; the original runtime hashes remain in the preserved receipts.

Related work: [factory request](https://github.com/Ali-Maq/aya/issues/2),
[SQL component and CI](https://github.com/Ali-Maq/crusoe-developer-hub/pull/2),
[controller](https://github.com/Ali-Maq/aya/pull/1), and
[MASS adapter CI](https://github.com/Ali-Maq/mass/actions/runs/39076469052).
