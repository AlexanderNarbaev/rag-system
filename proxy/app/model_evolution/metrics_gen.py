"""Generation evaluation metrics: BLEU, ROUGE-L, BertScore, hallucination rate."""

from dataclasses import dataclass, field


@dataclass
class GenerationMetrics:
    bleu_1: float = 0.0
    bleu_4: float = 0.0
    rouge_l_f1: float = 0.0
    rouge_l_precision: float = 0.0
    rouge_l_recall: float = 0.0
    bertscore_f1: float | None = None
    hallucination_rate: float = 0.0
    perplexity: float | None = None
    extra: dict = field(default_factory=dict)


def compute_bleu(
    references: list[str],
    hypotheses: list[str],
    max_n: int = 4,
) -> dict:
    import math
    from collections import Counter

    matches = [0] * max_n
    total = [0] * max_n
    ref_len_total = 0
    hyp_len_total = 0

    for ref, hyp in zip(references, hypotheses, strict=False):
        ref_tokens = ref.lower().split()
        hyp_tokens = hyp.lower().split()
        ref_len_total += len(ref_tokens)
        hyp_len_total += len(hyp_tokens)

        for n in range(1, max_n + 1):
            ref_ngrams = Counter(tuple(ref_tokens[i : i + n]) for i in range(len(ref_tokens) - n + 1))
            hyp_ngrams = Counter(tuple(hyp_tokens[i : i + n]) for i in range(len(hyp_tokens) - n + 1))
            matches[n - 1] += sum((ref_ngrams & hyp_ngrams).values())
            total[n - 1] += max(1, sum(hyp_ngrams.values()))

    precisions = []
    for i in range(max_n):
        if total[i] > 0:
            precisions.append(matches[i] / total[i])
        else:
            precisions.append(0.0)

    if all(p == 0.0 for p in precisions):
        return {f"bleu_{n}": 0.0 for n in range(1, max_n + 1)}

    brevity = min(1.0, hyp_len_total / max(1, ref_len_total))
    log_sum = sum(math.log(max(p, 1e-10)) for p in precisions) / max_n
    result = {}
    for n in range(1, max_n + 1):
        result[f"bleu_{n}"] = brevity * math.exp(log_sum)
    return result


def _lcs_len(a: list[str], b: list[str]) -> int:
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a)):
        for j in range(len(b)):
            dp[i + 1][j + 1] = dp[i][j] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    return dp[len(a)][len(b)]


def compute_rouge_l(
    references: list[str],
    hypotheses: list[str],
) -> dict:
    precisions = []
    recalls = []
    for ref, hyp in zip(references, hypotheses, strict=False):
        ref_tokens = ref.lower().split()
        hyp_tokens = hyp.lower().split()
        lcs = _lcs_len(ref_tokens, hyp_tokens)
        p = lcs / max(1, len(hyp_tokens))
        r = lcs / max(1, len(ref_tokens))
        precisions.append(p)
        recalls.append(r)
    avg_p = sum(precisions) / max(1, len(precisions))
    avg_r = sum(recalls) / max(1, len(recalls))
    f1 = 2 * avg_p * avg_r / max(1e-10, avg_p + avg_r)
    return {"rouge_l_precision": avg_p, "rouge_l_recall": avg_r, "rouge_l_f1": f1}


def compute_bertscore(
    references: list[str],
    hypotheses: list[str],
    model: str = "bert-base-uncased",
) -> dict:
    try:
        from bert_score import score

        P, R, F1 = score(hypotheses, references, model_type=model, verbose=False)  # noqa: N806
        return {
            "bertscore_precision": float(P.mean()),
            "bertscore_recall": float(R.mean()),
            "bertscore_f1": float(F1.mean()),
        }  # noqa: E501
    except ImportError:
        return {"bertscore_precision": 0.0, "bertscore_recall": 0.0, "bertscore_f1": 0.0}


def compute_generation_metrics(
    references: list[str],
    hypotheses: list[str],
    compute_bertscore_flag: bool = False,
) -> GenerationMetrics:
    bleu = compute_bleu(references, hypotheses)
    rouge = compute_rouge_l(references, hypotheses)
    bs = compute_bertscore(references, hypotheses) if compute_bertscore_flag else {"bertscore_f1": None}
    return GenerationMetrics(
        bleu_1=bleu.get("bleu_1", 0.0),
        bleu_4=bleu.get("bleu_4", 0.0),
        rouge_l_f1=rouge.get("rouge_l_f1", 0.0),
        rouge_l_precision=rouge.get("rouge_l_precision", 0.0),
        rouge_l_recall=rouge.get("rouge_l_recall", 0.0),
        bertscore_f1=bs.get("bertscore_f1"),
    )


def compute_all_gen_metrics(
    references: list[str],
    hypotheses: list[str],
) -> GenerationMetrics:
    m = compute_generation_metrics(references, hypotheses, compute_bertscore_flag=True)
    m.hallucination_rate = compute_hallucination_rate(references, hypotheses)
    return m


def compute_hallucination_rate(
    references: list[str],
    hypotheses: list[str],
) -> float:
    total_words = 0
    novel_words = 0
    for ref, hyp in zip(references, hypotheses, strict=False):
        ref_words = set(ref.lower().split())
        hyp_words = hyp.lower().split()
        if not hyp_words:
            continue
        total_words += len(hyp_words)
        novel_words += sum(1 for w in hyp_words if w not in ref_words)
    return novel_words / max(1, total_words)


def compute_perplexity(
    log_likelihoods: list[float],
) -> float:
    import math

    if not log_likelihoods:
        return float("inf")
    avg_ll = sum(log_likelihoods) / len(log_likelihoods)
    return math.exp(-avg_ll)
