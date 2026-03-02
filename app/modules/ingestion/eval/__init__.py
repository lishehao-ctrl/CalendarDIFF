from app.modules.ingestion.eval.contracts import (
    EvalDataset,
    EvalSummary,
    IcsEvalPair,
    IcsEvalResult,
    MailEvalResult,
    MailEvalSample,
    ThresholdDecision,
)
from app.modules.ingestion.eval.dataset_loader import DatasetLoadError, load_eval_dataset
from app.modules.ingestion.eval.ics_runner import infer_ics_diff, run_ics_eval
from app.modules.ingestion.eval.mail_runner import predict_mail_from_records, run_mail_eval
from app.modules.ingestion.eval.scoring import (
    DEFAULT_THRESHOLDS,
    compute_ics_metrics,
    compute_mail_metrics,
    evaluate_thresholds,
    summarize_eval_results,
    summary_to_dict,
)

__all__ = [
    "DatasetLoadError",
    "EvalDataset",
    "EvalSummary",
    "IcsEvalPair",
    "IcsEvalResult",
    "MailEvalResult",
    "MailEvalSample",
    "ThresholdDecision",
    "DEFAULT_THRESHOLDS",
    "load_eval_dataset",
    "run_mail_eval",
    "run_ics_eval",
    "predict_mail_from_records",
    "infer_ics_diff",
    "compute_mail_metrics",
    "compute_ics_metrics",
    "evaluate_thresholds",
    "summarize_eval_results",
    "summary_to_dict",
]
