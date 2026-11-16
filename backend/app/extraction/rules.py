"""Rule-based extractors -- the offline engine, and the LLM's safety net.

This module exists for three reasons, and only the first is obvious:

1. **The project runs with no API key.**  Clone, install, ``pytest`` -- the full
   pipeline executes and the evaluation harness produces real numbers.
2. **It is the baseline the LLM is measured against.**  "The model scores 0.71
   F1" means nothing without a floor.  ``evaluation/runner.py`` can score both
   engines on the same gold set, and the gap is the actual value the LLM adds.
3. **It backfills.**  When the LLM abstains on a field that a deterministic
   pattern *can* answer (registration IDs, sample sizes, p-values -- exactly the
   fields where regex beats generation), the pipeline can fill the gap and mark
   the provenance as ``rule``.

Every extractor returns the **whole sentence** as the quote.  Sentences come
from the source text unmodified, so a rule hit is grounded by construction.

Precision over recall throughout: a rule that fires on a cue phrase it is not
sure about is worse than no rule, because the abstain policy is what the whole
system's credibility rests on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from app.text_utils import split_sentences


class Sentence(NamedTuple):
    section: str
    text: str


@dataclass
class RuleHit:
    value: str
    quote: str
    confidence: float
    rule: str = ""


def sentences_from(pieces: Sequence[tuple]) -> list[Sentence]:
    """Flatten ``[(section_name, text), ...]`` into labelled sentences."""
    out: list[Sentence] = []
    for section_name, text in pieces:
        for _start, _end, sentence in split_sentences(text):
            cleaned = sentence.strip()
            if len(cleaned) > 15:
                out.append(Sentence(section_name, cleaned))
    return out


def _ordered(sentences: Sequence[Sentence], preferred: Sequence[str]) -> list[Sentence]:
    """Preferred sections first, in the order given, then everything else."""
    rank = {name: index for index, name in enumerate(preferred)}
    return sorted(sentences, key=lambda s: rank.get(s.section, len(preferred)))


def _first_match(
    sentences: Sequence[Sentence],
    patterns: Sequence[re.Pattern],
    preferred: Sequence[str],
    *,
    confidence: float,
    rule: str,
    render: Callable[[re.Match], str] | None = None,
    restrict_to: Sequence[str] | None = None,
) -> RuleHit | None:
    """First hit, scanning **patterns outermost**.

    Pattern order encodes specificity, and specificity should beat document
    position: "mean age was 63.4 years" is the answer to *age* even when an
    eligibility range ("aged 45 to 80 years") appears earlier in Methods.
    Scanning sentences outermost would return whichever pattern happened to
    appear first in the text, which is not a ranking at all.
    """
    pool = list(sentences)
    if restrict_to:
        scoped = [s for s in pool if s.section in set(restrict_to)]
        # Only apply the restriction if it leaves something to search; an
        # abstract-only record has no Methods section to scope to.
        if scoped:
            pool = scoped
    ordered = _ordered(pool, preferred)

    for pattern in patterns:
        for sentence in ordered:
            match = pattern.search(sentence.text)
            if not match:
                continue
            value = render(match) if render else match.group(0)
            value = re.sub(r"\s+", " ", value).strip(" ,;:.")
            if value:
                boost = 0.05 if sentence.section in preferred[:1] else 0.0
                return RuleHit(
                    value=value,
                    quote=sentence.text,
                    confidence=min(0.95, confidence + boost),
                    rule=rule,
                )
    return None


#: A noun phrase like "patients with stage 2 chronic kidney disease" ends where
#: the clause's verb begins.  Regex captures run to the sentence end, so without
#: this cut a population comes back as "... disease were randomly assigned (1:1)
#: to receive ...", which is the right sentence but the wrong answer.
_CLAUSE_VERB = re.compile(
    # Not after "who"/"that": "patients who were hospitalized" is one phrase.
    r"(?<!\bwho)(?<!\bthat)\s+(?:were|was|are|is|had|have|has|would|will|received|underwent|"
    r"completed|provided|did|who\s+were\s+randomi[sz]ed)\b",
    re.IGNORECASE,
)


def _trim_clause(value: str) -> str:
    match = _CLAUSE_VERB.search(value)
    if match and match.start() >= 8:
        value = value[: match.start()]
    return value.strip(" ,;:.")


METHODS_FIRST = ("methods", "abstract", "results", "body")
RESULTS_FIRST = ("results", "abstract", "methods", "body")
ABSTRACT_FIRST = ("abstract", "methods", "results", "body")


# ----------------------------------------------------------------- sample size
_SAMPLE_PATTERNS = [
    re.compile(
        r"\b(?:a\s+total\s+of\s+)?(\d{1,3}(?:,\d{3})*|\d+)\s+"
        r"(?:eligible\s+|consecutive\s+|adult\s+)?"
        r"(patients|participants|subjects|women|men|adults|children|individuals)\b"
        r"[^.]{0,60}?\b(?:were|was)\s+(?:randomly\s+|consecutively\s+)?"
        r"(randomi[sz]ed|enrolled|included|recruited|assigned|analy[sz]ed)",
        re.IGNORECASE,
    ),
    re.compile(r"\bn\s*=\s*(\d{1,3}(?:,\d{3})*|\d+)\b(?!\s*%)", re.IGNORECASE),
    re.compile(
        r"\bwe\s+(randomi[sz]ed|enrolled|recruited|included)\s+"
        r"(\d{1,3}(?:,\d{3})*|\d+)\b",
        re.IGNORECASE,
    ),
]


#: "A total of 2104 patients were assigned to receive dexamethasone and 4321 to
#: receive usual care" states the trial size only as two arms.  Reporting the
#: first number alone halves the trial, so the two-arm form is tried first and
#: summed.  The quote still carries both numbers, so the sum is checkable.
_TWO_ARM_SAMPLE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})+|\d+)\s+(?:patients|participants|subjects|adults|"
    r"women|men|children|individuals)\s+(?:were\s+)?(?:randomly\s+)?"
    r"(?:assigned|allocated|randomi[sz]ed)\s+to\s+(?:receive\s+)?[^.;]{2,80}?"
    r"\s+and\s+(\d{1,3}(?:,\d{3})+|\d+)\s+(?:patients\s+|participants\s+)?"
    r"(?:were\s+)?(?:assigned\s+)?to\b",
    re.IGNORECASE,
)


def _as_int(text: str) -> int:
    return int(text.replace(",", ""))


def extract_sample_size(sentences: Sequence[Sentence]) -> RuleHit | None:
    for sentence in _ordered(sentences, RESULTS_FIRST + ("methods",)):
        match = _TWO_ARM_SAMPLE.search(sentence.text)
        if match:
            first, second = _as_int(match.group(1)), _as_int(match.group(2))
            return RuleHit(
                value=f"{first + second} ({first} + {second})",
                quote=sentence.text,
                confidence=0.80,
                rule="sample_size_two_arm",
            )

    def render(match: re.Match) -> str:
        for group in match.groups():
            if group and re.fullmatch(r"[\d,]+", group):
                return group
        return match.group(0)

    hit = _first_match(
        sentences,
        _SAMPLE_PATTERNS,
        METHODS_FIRST,
        confidence=0.78,
        rule="sample_size",
        render=render,
    )
    # A three-digit "n = 95" inside a confidence interval is a false friend;
    # require the sentence to actually be about people.
    if hit and not re.search(
        r"patients|participants|subjects|women|men|adults|children|"
        r"individuals|randomi|enrol|recruit|includ",
        hit.quote,
        re.IGNORECASE,
    ):
        return None
    return hit


# ------------------------------------------------------------------------ age
_AGE_PATTERNS = [
    re.compile(
        r"\b(?:mean|median|average)\s+age[^.]{0,25}?"
        # "mean age was 1.1 years older among patients in the ... group" is a
        # between-group difference, not the cohort's age.
        r"(\d{1,3}(?:\.\d+)?)(?![\d.])\s*(?:years?)?(?!\s*(?:older|younger|higher|lower))\s*"
        r"(?:\(|±|\[|,)?\s*(?:SD|IQR|range)?[^.]{0,25}",
        re.IGNORECASE,
    ),
    re.compile(r"\baged\s+(\d{1,3})\s*(?:to|-|–|—)\s*(\d{1,3})\s*years?", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})\s*(?:to|-|–|—)\s*(\d{1,3})\s*years\s+of\s+age", re.IGNORECASE),
    re.compile(r"\baged\s+(?:≥|>=|over|at least)\s*(\d{1,3})\s*years?", re.IGNORECASE),
]


#: A sentence comparing the arms' ages ("1.1 years older among patients in
#: the dexamethasone group") contains an age-shaped number that is not an age.
_AGE_COMPARISON = re.compile(
    r"\b(?:years?\s+)?(?:older|younger)\s+(?:among|than|in)\b|\bage\s+difference\b",
    re.IGNORECASE,
)


def extract_age(sentences: Sequence[Sentence]) -> RuleHit | None:
    usable = [s for s in sentences if not _AGE_COMPARISON.search(s.text)]
    return _first_match(
        usable, _AGE_PATTERNS, METHODS_FIRST, confidence=0.74, rule="age"
    )


# --------------------------------------------------------------------- sex mix
_SEX_PATTERNS = [
    re.compile(
        r"\b(\d{1,3}(?:\.\d+)?)\s*%\s*(?:of\s+(?:whom\s+)?)?"
        r"(?:were\s+)?(female|male|women|men)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{1,4})\s*(?:\([\d.]+\s*%\))?\s*(female|male|women|men)\b", re.IGNORECASE
    ),
]


def extract_sex(sentences: Sequence[Sentence]) -> RuleHit | None:
    return _first_match(
        sentences, _SEX_PATTERNS, METHODS_FIRST, confidence=0.72, rule="sex"
    )


# ------------------------------------------------------------------ study design
_DESIGN_TERMS = [
    # Order matters: a review *of* randomised trials is a review, not an RCT,
    # and its abstract contains the phrase "randomised trials". The most
    # specific label has to win before the generic trial pattern is tried.
    (r"\b(?:systematic\s+review|meta-?analys[ie]s)\b", "systematic review / meta-analysis", 0.86),
    (r"\bcluster[-\s]randomi[sz]ed\b[\w\s-]{0,20}trial", "cluster-randomised trial", 0.88),
    (r"\brandomi[sz]ed\s+clinical\s+trial\b", "randomised clinical trial", 0.88),
    (r"randomi[sz]ed[,\s\w-]{0,40}?(?:controlled\s+)?trial", "randomised controlled trial", 0.88),
    (r"\bprospective\s+cohort\s+study\b", "prospective cohort study", 0.86),
    (r"\bretrospective\s+cohort\s+study\b", "retrospective cohort study", 0.86),
    (r"\bcohort\s+study\b", "cohort study", 0.80),
    (r"\bcase[-\s]control\s+study\b", "case-control study", 0.85),
    (r"\bcross[-\s]sectional\s+(?:study|survey)\b", "cross-sectional study", 0.85),
    (r"\b(?:non-?)?randomi[sz]ed\s+controlled\s+study\b", "controlled study", 0.78),
    (r"\bpilot\s+study\b", "pilot study", 0.70),
    (r"\bobservational\s+study\b", "observational study", 0.75),
    (r"\bcase\s+series\b", "case series", 0.78),
]
#: An RCT that never uses the word "randomised": "In this controlled,
#: open-label trial ... we randomly assigned patients". Tried after the
#: specific labels above, so a review or cluster trial still wins.
_IMPLICIT_RCT = re.compile(
    r"\btrial\b[^.]{0,240}\brandomly\s+(?:assigned|allocated)\b|"
    r"\brandomly\s+(?:assigned|allocated)\b[^.]{0,240}\btrial\b",
    re.IGNORECASE,
)

_DESIGN_COMPILED = [
    (re.compile(pattern, re.IGNORECASE), label, confidence)
    for pattern, label, confidence in _DESIGN_TERMS
]


def extract_design(sentences: Sequence[Sentence]) -> RuleHit | None:
    ordered = _ordered(sentences, ABSTRACT_FIRST)
    for sentence in ordered:
        for pattern, label, confidence in _DESIGN_COMPILED:
            if pattern.search(sentence.text):
                return RuleHit(label, sentence.text, confidence, rule="design")
    for sentence in ordered:
        if sentence.section in ("abstract", "methods", "body") and _IMPLICIT_RCT.search(sentence.text):
            return RuleHit("randomised controlled trial", sentence.text, 0.82, rule="design_implicit")
    return None


#: The word "randomised" is not evidence that *this* study randomised anything.
#: A cohort paper says "a randomised trial is required"; a meta-analysis says
#: "trials were eligible if they randomised adults". Both would be false
#: positives, and a fabricated "randomised: yes" misleads a reviewer about the
#: level of evidence -- so this rule demands an active statement about the
#: study's own participants, and only looks in Methods/Abstract.
_RANDOMISED_PATTERNS = [
    re.compile(
        r"\b(?:were|was)\s+random(?:ly|i[sz]ed)\s+(?:assigned|allocated)\b", re.IGNORECASE
    ),
    re.compile(r"\bwe\s+randomi[sz]ed\b", re.IGNORECASE),
    re.compile(r"\bwe\s+randomly\s+(?:assigned|allocated)\b", re.IGNORECASE),
    re.compile(
        r"\brandomi[sz]ation\s+(?:was|were|sequence|list|schedule|ratio)\b", re.IGNORECASE
    ),
    re.compile(
        r"\brandomi[sz]ed\s*\(?\s*\d\s*:\s*\d\s*\)?\s*to\b", re.IGNORECASE
    ),
    re.compile(
        r"\brandomly\s+assigned\s*\(?\s*\d\s*:\s*\d\s*\)?\s*to\b", re.IGNORECASE
    ),
]


def extract_randomised(sentences: Sequence[Sentence]) -> RuleHit | None:
    hit = _first_match(
        sentences,
        _RANDOMISED_PATTERNS,
        METHODS_FIRST,
        confidence=0.82,
        rule="randomised",
        restrict_to=("methods", "abstract"),
    )
    if hit is None:
        return None
    return RuleHit("yes", hit.quote, hit.confidence, rule=hit.rule)


_BLINDING_TERMS = [
    (r"\bquadruple[-\s]blind", "quadruple-blind"),
    (r"\btriple[-\s]blind", "triple-blind"),
    (r"\bdouble[-\s]blind", "double-blind"),
    (r"\bsingle[-\s]blind", "single-blind"),
    (r"\bopen[-\s]label", "open-label"),
    (r"\bassessor[-\s]blind", "assessor-blinded"),
    (r"\bunblinded\b", "unblinded"),
]
_BLINDING_COMPILED = [
    (re.compile(pattern, re.IGNORECASE), label) for pattern, label in _BLINDING_TERMS
]


def extract_blinding(sentences: Sequence[Sentence]) -> RuleHit | None:
    for sentence in _ordered(sentences, ABSTRACT_FIRST):
        for pattern, label in _BLINDING_COMPILED:
            if pattern.search(sentence.text):
                return RuleHit(label, sentence.text, 0.85, rule="blinding")
    return None


_SETTING_PATTERNS = [
    re.compile(
        r"\b(?:at|in|across|from)\s+(\d{1,4})\s+(?:[A-Z]{2,5}\s+)?(?:\w+\s+)?"
        r"(?:hospitals?|cent(?:re|er)s?|sites?|clinics?|villages?|practices)\b[^.;]{0,60}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(multi-?cent(?:re|er)|single-?cent(?:re|er))\b[^.]{0,80}", re.IGNORECASE
    ),
    re.compile(
        r"\b(?:conducted|performed|carried\s+out)\s+(?:in|at)\s+[^.]{5,90}",
        re.IGNORECASE,
    ),
]


def extract_setting(sentences: Sequence[Sentence]) -> RuleHit | None:
    return _first_match(
        sentences, _SETTING_PATTERNS, METHODS_FIRST, confidence=0.66, rule="setting"
    )


_DURATION_PATTERNS = [
    re.compile(
        r"\b(?:median|mean)\s+follow-?up\s+(?:of|was|period[^.]{0,15})?\s*"
        r"([\d.]+)\s*(days?|weeks?|months?|years?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfollowed\s+(?:up\s+)?for\s+(?:a\s+(?:median|mean)\s+of\s+)?"
        r"([\d.]+)\s*(days?|weeks?|months?|years?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:over|during|for)\s+(?:a\s+period\s+of\s+)?([\d.]+)\s*"
        r"(days?|weeks?|months?|years?)\b",
        re.IGNORECASE,
    ),
]


def extract_duration(sentences: Sequence[Sentence]) -> RuleHit | None:
    return _first_match(
        sentences,
        _DURATION_PATTERNS,
        METHODS_FIRST,
        confidence=0.70,
        rule="duration",
        render=lambda m: f"{m.group(1)} {m.group(2)}",
    )


_REGISTRATION_PATTERNS = [
    re.compile(r"\bNCT\d{8}\b"),
    re.compile(r"\bISRCTN\s?\d{8}\b", re.IGNORECASE),
    re.compile(r"\bChiCTR[-\w]*\d{6,}\b", re.IGNORECASE),
    re.compile(r"\b(?:PROSPERO\s+)?CRD4?2?\d{9,}\b", re.IGNORECASE),
    re.compile(r"\bEudraCT\s?\d{4}-\d{6}-\d{2}\b", re.IGNORECASE),
    re.compile(r"\bACTRN\d{14}\b", re.IGNORECASE),
    re.compile(r"\bUMIN\d{9}\b", re.IGNORECASE),
]


def extract_registration(sentences: Sequence[Sentence]) -> RuleHit | None:
    # Registration IDs are unambiguous, so this is the one rule allowed to be
    # very confident and to ignore section.
    return _first_match(
        sentences,
        _REGISTRATION_PATTERNS,
        ("methods", "abstract", "supplementary", "body"),
        confidence=0.94,
        rule="registration",
    )


# --------------------------------------------------------------------- PICO
_POPULATION_PATTERNS = [
    # The trial's own framing: "in patients who were hospitalized with Covid-19".
    re.compile(
        r"\b(?:patients?|participants?|adults?|children|women|men)\s+who\s+were\s+"
        r"(?:hospitali[sz]ed|admitted|diagnosed|undergoing|receiving)\s+[^.,;]{3,100}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:patients?|participants?|adults?|children|women|men|subjects?)\s+"
        r"with\s+[^.]{5,110}",
        re.IGNORECASE,
    ),
    # "adults undergoing elective hip arthroplasty", "patients admitted to ICU"
    re.compile(
        r"\b(?:patients?|participants?|adults?|children|women|men|subjects?)\s+"
        r"(?:undergoing|receiving|admitted|presenting|scheduled|referred|aged)\s+[^.]{5,110}",
        re.IGNORECASE,
    ),
    re.compile(r"\beligible\s+(?:patients?|participants?)\s+[^.]{5,110}", re.IGNORECASE),
    # Last resort for abstract-only records that only name the group in passing.
    re.compile(
        r"\b(?:in|among)\s+(?:older|elderly|adult|young|paediatric|pediatric|"
        r"critically\s+ill|hospitali[sz]ed|community-dwelling)\s+[^.]{3,90}",
        re.IGNORECASE,
    ),
]


#: Sentences that mention patients without describing who was studied: funder
#: disclaimers, power calculations, consent boilerplate.
_NOT_A_POPULATION = re.compile(
    r"\bno\s+role\b|\bpower\b|\bsample\s+size\b|\binformed\s+consent\b|"
    r"\bethics\b|\bfunder|\bguidelines?\b",
    re.IGNORECASE,
)


def extract_population(sentences: Sequence[Sentence]) -> RuleHit | None:
    usable = [s for s in sentences if not _NOT_A_POPULATION.search(s.text)]
    hit = _first_match(
        usable or sentences,
        _POPULATION_PATTERNS,
        METHODS_FIRST,
        confidence=0.66,
        rule="population",
        render=lambda m: _trim_clause(m.group(0)),
    )
    return hit


_INTERVENTION_PATTERNS = [
    # Only a *random* assignment defines the arm; "a total of 2104 patients were
    # assigned to receive X and 4321 to receive Y" is a result sentence.
    re.compile(
        r"\b(?:randomly\s+(?:assigned|allocated)|randomi[sz]ed)\s+"
        r"(?:(?:patients|participants)\s+)?(?:\(\d:\d\)\s*)?(?:in\s+a\s+\d:\d\s+ratio\s+)?"
        r"to\s+(?:receive\s+)?([^.]{3,140})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:assigned|allocated)\s+(?:\(\d:\d\)\s*)?to\s+(?:receive\s+)?([^.]{3,110})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:intervention|treatment|experimental)\s+group\s+received\s+[^.]{3,110}",
        re.IGNORECASE,
    ),
    re.compile(r"\btreated\s+with\s+[^.]{3,110}", re.IGNORECASE),
]


#: Where the experimental arm's description stops and the comparator begins.
#: Bare " or " is deliberately absent: "oral or intravenous dexamethasone" is
#: one arm.
_ARM_BOUNDARY = re.compile(
    r"\s+(?:or\s+to\s+(?:receive\s+)?|or\s+(?:a\s+)?(?:matching\s+)?placebo\b|"
    r"or\s+(?:usual|standard)\s+care\b|versus\s+|vs\.?\s+|compared\s+with\s+|"
    r"and\s+[\d,]+\s+(?:patients\s+)?(?:were\s+)?(?:assigned\s+)?to\b)",
    re.IGNORECASE,
)


def _arm(match: re.Match) -> str:
    text = match.group(1) if match.groups() and match.group(1) else match.group(0)
    cut = _ARM_BOUNDARY.search(text)
    if cut:
        text = text[: cut.start()]
    return text.strip(" ,;:.")


def extract_intervention(sentences: Sequence[Sentence]) -> RuleHit | None:
    return _first_match(
        sentences,
        _INTERVENTION_PATTERNS,
        METHODS_FIRST,
        confidence=0.68,
        rule="intervention",
        render=_arm,
        restrict_to=("methods", "abstract", "body"),
    )


_COMPARISON_PATTERNS = [
    # The comparator named in the allocation sentence itself:
    # "... assigned to receive X or to receive usual care alone".
    re.compile(
        r"\b(?:assigned|allocated|randomi[sz]ed)\b[^.]{3,200}?\bor\s+to\s+receive\s+"
        r"([^.,;()]{3,60})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:assigned|allocated|randomi[sz]ed)\b[^.]{3,200}?\bor\s+"
        r"((?:a\s+)?(?:matching\s+)?placebo|(?:usual|standard)\s+care(?:\s+alone)?)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:matching\s+)?placebo\b[^.]{0,80}", re.IGNORECASE),
    re.compile(
        r"\b(?:control|comparator|usual\s+care|standard\s+care|sham)\s+"
        r"(?:group|arm|condition|treatment)\b[^.]{0,70}",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:matched\s+)?controls?\s+who\s+[^.]{3,80}", re.IGNORECASE),
    # "versus" is last and refuses a numeric right-hand side, because in Results
    # it almost always introduces two rates ("14.0 % versus 19.6 %") rather than
    # the comparator arm.
    re.compile(
        r"\b(?:versus|compared\s+with|compared\s+to|vs\.?)\s+"
        r"(?![\d.]+\s*(?:%|ng|mg|g|ml|mmol|points?|days?|weeks?|months?|years?))"
        r"[^.]{3,90}",
        re.IGNORECASE,
    ),
]


#: A sample-size paragraph names the control arm too ("the usual care group
#: would provide a power of 90%") without defining it.
_NOT_A_COMPARATOR = re.compile(
    r"\bpower\b|\bsample\s+size\b|\bP\s+value\b|\bwould\s+provide\b",
    re.IGNORECASE,
)


def extract_comparison(sentences: Sequence[Sentence]) -> RuleHit | None:
    usable = [s for s in sentences if not _NOT_A_COMPARATOR.search(s.text)]
    return _first_match(
        usable or sentences,
        _COMPARISON_PATTERNS,
        METHODS_FIRST,
        confidence=0.66,
        rule="comparison",
        render=lambda m: (m.group(1) if m.groups() and m.group(1) else m.group(0)),
        # A comparator is defined in Methods; a "versus" in Results is a result.
        restrict_to=("methods", "abstract", "body"),
    )


_OUTCOME_PATTERNS = [
    re.compile(
        r"\b(?:the\s+)?(?:co-?)?primary\s+(?:outcome|endpoint|end\s+point)s?\s+"
        r"(?:measures?\s+)?(?:was|were|is|are)\s+(?:the\s+)?([^.]{3,140})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bprimary\s+(?:outcome|endpoint|end\s+point)s?\b[^.]{0,140}", re.IGNORECASE
    ),
]


def extract_primary_outcome(sentences: Sequence[Sentence]) -> RuleHit | None:
    return _first_match(
        sentences,
        _OUTCOME_PATTERNS,
        METHODS_FIRST,
        confidence=0.80,
        rule="primary_outcome",
        render=lambda m: m.group(1) if m.groups() and m.group(1) else m.group(0),
    )


_INCLUSION_PATTERNS = [
    re.compile(r"\binclusion\s+criteria[^.]{0,160}", re.IGNORECASE),
    re.compile(r"\bwere\s+eligible\s+if\s+[^.]{5,140}", re.IGNORECASE),
    re.compile(
        r"\beligible\s+(?:for\s+(?:inclusion|enrol?ment|(?:the\s+)?(?:trial|study))\s+)"
        r"if\s+[^.]{5,160}",
        re.IGNORECASE,
    ),
    re.compile(r"\beligible\s+if\s+they\s+[^.]{5,140}", re.IGNORECASE),
]
_EXCLUSION_PATTERNS = [
    re.compile(r"\bexclusion\s+criteria[^.]{0,160}", re.IGNORECASE),
    re.compile(r"\bwere\s+excluded\s+if\s+[^.]{5,140}", re.IGNORECASE),
    re.compile(r"\bexcluded\s+(?:patients?|participants?)\s+(?:with|who)\s+[^.]{5,140}", re.IGNORECASE),
]


def extract_inclusion(sentences: Sequence[Sentence]) -> RuleHit | None:
    return _first_match(
        sentences, _INCLUSION_PATTERNS, METHODS_FIRST, confidence=0.72, rule="inclusion"
    )


def extract_exclusion(sentences: Sequence[Sentence]) -> RuleHit | None:
    return _first_match(
        sentences, _EXCLUSION_PATTERNS, METHODS_FIRST, confidence=0.72, rule="exclusion"
    )


#: Two cue tiers. Tier 1 states a limitation directly; tier 2 only *announces*
#: that limitations follow ("Our study has several limitations.") and is
#: therefore useless as a quote on its own -- see the look-ahead below.
_LIMITATION_SUBSTANCE = re.compile(
    r"\b(limitations?|should\s+be\s+interpreted\s+with\s+caution|"
    r"residual\s+confounding|cannot\s+be\s+(?:excluded|ruled\s+out)|"
    r"limits?\s+generalisabilit|limits?\s+generalizabilit|"
    r"we\s+(?:could\s+not|were\s+unable\s+to)|small\s+sample\s+size|"
    r"may\s+not\s+(?:be\s+)?generali[sz]e)\b",
    re.IGNORECASE,
)
_LIMITATION_ANNOUNCEMENT = re.compile(
    r"^\W*(?:our|this|the)\s+(?:study|trial|review|analysis)\s+(?:has|had)\s+"
    r"(?:several|some|a\s+number\s+of|certain)\s+limitations\W*$",
    re.IGNORECASE,
)


def extract_limitations(sentences: Sequence[Sentence]) -> RuleHit | None:
    # Limitations are the authors' own appraisal, which lives in Discussion. A
    # "limitation" word in Methods is almost always protocol detail.
    pool = [s for s in sentences if s.section not in ("methods", "results", "references")]
    ordered = _ordered(pool, ("discussion", "conclusion", "body", "abstract"))
    for position, sentence in enumerate(ordered):
        if not _LIMITATION_SUBSTANCE.search(sentence.text):
            continue
        # "Our review has several limitations." is a heading in disguise. Quote
        # the sentence that actually names a limitation instead.
        if _LIMITATION_ANNOUNCEMENT.match(sentence.text.strip()):
            for follower in ordered[position + 1 : position + 3]:
                if follower.section == sentence.section and len(follower.text) > 40:
                    return RuleHit(
                        follower.text, follower.text, 0.68, rule="limitations_next"
                    )
            continue
        return RuleHit(sentence.text, sentence.text, 0.70, rule="limitations")
    return None


_CONCLUSION_CUES = re.compile(
    r"\b(in conclusion|we conclude|these (?:findings|results) (?:suggest|show|indicate)|"
    r"this (?:study|trial) (?:shows|demonstrates|found)|taken together|"
    r"further\s+\w*\s*(?:work|research|studies|trials?|investigation)\s+"
    r"(?:is|are)\s+(?:required|needed|warranted))\b",
    re.IGNORECASE,
)


def extract_conclusion(sentences: Sequence[Sentence]) -> RuleHit | None:
    for sentence in _ordered(sentences, ("conclusion", "abstract", "discussion", "body")):
        if _CONCLUSION_CUES.search(sentence.text):
            return RuleHit(sentence.text, sentence.text, 0.76, rule="conclusion")
    # Fall back to the *first* sentence of an explicit conclusion section: a
    # conclusion leads with its claim.  The last sentence is where a section
    # that ran on past its end (an abstract's CONCLUSIONS bleeding into an
    # unheaded introduction) is most wrong.
    conclusion_sentences = [s for s in sentences if s.section == "conclusion"]
    if conclusion_sentences:
        first = conclusion_sentences[0]
        return RuleHit(first.text, first.text, 0.58, rule="conclusion_section")
    return None


_FUNDING_PATTERNS = [
    re.compile(
        r"\b(?:funded|supported|sponsored)\s+by\s+[^.]{3,120}", re.IGNORECASE
    ),
    re.compile(r"\bfunding[:\s]+[^.]{3,120}", re.IGNORECASE),
    re.compile(r"\bgrant\s+(?:no\.?|number)\s*[^.]{3,80}", re.IGNORECASE),
]


def extract_funding(sentences: Sequence[Sentence]) -> RuleHit | None:
    return _first_match(
        sentences,
        _FUNDING_PATTERNS,
        ("supplementary", "methods", "body", "abstract"),
        confidence=0.74,
        rule="funding",
    )


# ------------------------------------------------------------------- outcomes
_EFFECT = re.compile(
    r"\b(hazard\s+ratio|risk\s+ratio|rate\s+ratio|odds\s+ratio|mean\s+difference|"
    r"relative\s+risk|HR|RR|OR|MD|SMD)\b\s*[,:=]?\s*"
    r"(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_CI = re.compile(
    r"\b95\s*%\s*(?:CI|confidence\s+interval)\s*(?:\[\s*CI\s*\]|\(\s*CI\s*\))?[,:\s]*"
    r"[\[(]?\s*(-?\d+(?:\.\d+)?)\s*(?:to|-|–|—|,)\s*(-?\d+(?:\.\d+)?)\s*[\])]?",
    re.IGNORECASE,
)
_P_VALUE = re.compile(r"\bp\s*(<|>|=|≤|≥)\s*(0?\.\d+|\d+\.\d+(?:e-?\d+)?)", re.IGNORECASE)
_PERCENT_PAIR = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(?:vs\.?|versus|compared\s+with)\s*(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_PRIMARY_CUE = re.compile(r"\bprimary\b", re.IGNORECASE)
_SAFETY_CUE = re.compile(
    r"\b(adverse\s+events?|serious\s+adverse|safety|toxicit|side\s+effects?|harms?)\b",
    re.IGNORECASE,
)
#: "among patients receiving invasive mechanical ventilation", "in the subgroup
#: of women" -- a result restricted to part of the trial.
_SUBGROUP = re.compile(
    r"\b(?:among|in)\s+(?:those|patients|participants|the\s+subgroup\s+of)\s+"
    r"(?:who\s+were\s+)?([^,;()]{4,80}?)(?=\s*\(|,|;|\s+and\s+among|\s+but\b|$)",
    re.IGNORECASE,
)
_SUBGROUP_WORD = re.compile(r"\bsubgroups?\b", re.IGNORECASE)

#: Discourse openers that were being promoted to outcome names ("However",
#: "Overall", "In addition").
_OPENER = re.compile(
    r"^(?:however|overall|in\s+addition|additionally|moreover|furthermore|"
    r"similarly|in\s+contrast|by\s+contrast|notably|importantly|thus|therefore)\b[,\s]*",
    re.IGNORECASE,
)
_OUTCOME_NOUN = re.compile(
    r"\b(?:\d+-day\s+|all-cause\s+|in-hospital\s+|cardiovascular\s+)?"
    r"(mortality|death|survival|incidence\s+of\s+[^,.;()]{3,50}|risk\s+of\s+[^,.;()]{3,50}|"
    r"rate\s+of\s+[^,.;()]{3,50}|hospitali[sz]ation|readmission|recurrence|"
    r"remission|response|stroke|myocardial\s+infarction|infection|relapse)"
    r"(?:\s+(?:at|within|by)\s+\d+\s+(?:days?|weeks?|months?|years?))?",
    re.IGNORECASE,
)


def _is_figure_noise(text: str) -> bool:
    """Figure axes and at-risk tables flattened into prose.

    A Kaplan-Meier panel extracts as a long run of bare numbers ("4321 2104 3754
    1903 3427 ..."), and it often contains the panel's own "Rate ratio, 0.83
    (95% CI ...)" label -- so it passes every statistics test while being the
    worst possible quote.  Real result sentences are mostly words.
    """
    tokens = text.split()
    if len(tokens) < 12:
        return False
    numeric = sum(1 for token in tokens if re.fullmatch(r"[\d.,%()=–\-]+", token))
    if numeric / len(tokens) > 0.35:
        return True
    return bool(
        re.search(r"\bNo\.\s+at\s+Risk\b|\bdays\s+since\s+randomi[sz]ation\b", text, re.I)
    )


def _outcome_name(text: str) -> str:
    """Best-effort label for a result sentence."""
    match = re.search(
        r"\b(?:primary|secondary|safety)\s+(?:outcome|endpoint|end\s+point)s?\b"
        r"(?:\s*(?:of|was|were|,|:))?\s*([^,.;()]{3,80})",
        text,
        re.IGNORECASE,
    )
    if match and match.group(1).strip():
        return _trim_clause(_OPENER.sub("", match.group(1).strip())) or match.group(1).strip()
    died = re.search(r"\bdied\s+(within|by|at)\s+(\d+\s+(?:days?|weeks?|months?|years?))", text, re.I)
    if died:
        return f"Mortality {died.group(1).lower()} {died.group(2)}"
    noun = _OUTCOME_NOUN.search(text)
    if noun:
        return noun.group(0).strip()
    match = re.search(
        r"\b(?:incidence|rate|risk|frequency|prevalence|mortality|survival|"
        r"change|reduction|improvement)\s+(?:of|in)\s+([^,.;()]{3,70})",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(0).strip()
    clause = re.split(r"[,;(]", _OPENER.sub("", text), maxsplit=1)[0]
    return clause.strip()[:90] or "reported outcome"


def _measure_key(measure: str | None) -> str:
    if not measure:
        return ""
    lowered = measure.lower()
    for short, long in (("hr", "hazard ratio"), ("rr", "risk ratio"), ("or", "odds ratio"),
                        ("md", "mean difference")):
        if lowered == short:
            return long
    return lowered


def extract_outcomes(sentences: Sequence[Sentence], limit: int = 6) -> list[dict]:
    """Pull statistically-reported results out of Results/Abstract.

    One result is reported up to three times in a paper -- abstract, results
    text, figure label -- so rows are keyed on the statistic itself (measure,
    estimate, interval) and merged: the merged row keeps the most informative
    label (primary beats secondary) and the cleanest quote.
    """
    rows: dict[tuple, dict] = {}
    order: list[tuple] = []

    for sentence in _ordered(sentences, RESULTS_FIRST):
        if _is_figure_noise(sentence.text):
            continue
        for text in _result_fragments(sentence.text):
            _absorb_result(text, sentence.text, rows, order)

    found = [rows[key] for key in order][: limit]
    # CONSORT abstracts report the primary outcome first and often never use
    # the word "primary" beside it. When nothing is labelled primary, the first
    # whole-trial result (not a subgroup, not safety) takes the label -- with a
    # confidence cap, since this is a convention rather than a statement.
    if found and not any(item["kind"] == "primary" for item in found):
        headline = next((item for item in found if item["kind"] == "secondary"), None)
        if headline is not None:
            headline["kind"] = "primary"
            headline["confidence"] = min(headline["confidence"], 0.7)
    priority = {"primary": 0, "safety": 1, "secondary": 2, "subgroup": 3}
    found.sort(key=lambda item: priority.get(item["kind"], 4))
    return found


def _result_fragments(text: str) -> list[str]:
    """One sentence, several results: "... among A (rate ratio, 0.64; ...) and
    among B (rate ratio, 0.82; ...) but not among C (rate ratio, 1.19; ...)".

    Splitting on the clause joins keeps each estimate with its own subgroup and
    interval; the row's quote stays the whole sentence, which is what grounds.
    """
    if len(_EFFECT.findall(text)) < 2:
        return [text]
    parts = re.split(r"\)\s*,?\s+(?:and|but(?:\s+not)?)\s+(?=among|in\b)", text)
    return parts if len(parts) > 1 else [text]


def _absorb_result(text: str, quote: str, rows: dict, order: list) -> None:
    """Score one result fragment and merge it into ``rows`` (keyed on the statistic)."""
    effect = _EFFECT.search(text)
    ci = _CI.search(text)
    p_value = _P_VALUE.search(text)
    percent = _PERCENT_PAIR.search(text)

    signals = sum(bool(x) for x in (effect, ci, p_value, percent))
    if signals < 2:
        return  # one lonely number is not a reported result

    subgroup = None
    subgroup_match = _SUBGROUP.search(text)
    if _SUBGROUP_WORD.search(text) or (subgroup_match and not _PRIMARY_CUE.search(text)):
        subgroup = subgroup_match.group(1).strip() if subgroup_match else "subgroup"

    if _SAFETY_CUE.search(text):
        kind = "safety"
    elif _PRIMARY_CUE.search(text):
        kind = "primary"
    elif subgroup:
        kind = "subgroup"
    else:
        kind = "secondary"

    direction = None
    if p_value:
        try:
            threshold = float(p_value.group(2))
            operator = p_value.group(1)
            if operator in ("<", "≤") and threshold <= 0.05:
                direction = "favours_intervention"
            elif operator in (">", "≥") or threshold > 0.05:
                direction = "no_difference"
        except ValueError:
            pass
    if re.search(r"\bno\s+(?:significant\s+)?difference\b|\bno\s+clear\s+effect\b", text, re.I):
        direction = "no_difference"
    if ci and direction is None and effect and _measure_key(effect.group(1)).endswith("ratio"):
        low, high = float(ci.group(1)), float(ci.group(2))
        if low <= 1.0 <= high:
            direction = "no_difference"

    measure = effect.group(1) if effect else ("percentage" if percent else None)
    estimate = (
        effect.group(2)
        if effect
        else (f"{percent.group(1)}% vs {percent.group(2)}%" if percent else None)
    )
    interval = f"95% CI {ci.group(1)} to {ci.group(2)}" if ci else None
    name = _outcome_name(text)
    if kind == "subgroup" and subgroup:
        name = subgroup[:1].upper() + subgroup[1:]

    row = {
        "name": name,
        "kind": kind,
        "measure": measure,
        "effect_size": estimate,
        "confidence_interval": interval,
        "p_value": f"p {p_value.group(1)} {p_value.group(2)}" if p_value else None,
        "direction": direction,
        "quote": quote,
        "confidence": min(0.9, 0.45 + 0.15 * signals),
    }

    key = (_measure_key(measure), estimate, ci.group(1) if ci else None)
    existing = rows.get(key)
    if existing is None:
        # Same estimate, but one copy lost its interval to a line break:
        # still the same result.
        loose = next(
            (k for k in order if k[0] == key[0] and k[1] == key[1]
             and (k[2] is None or key[2] is None)),
            None,
        )
        if loose is not None:
            key, existing = loose, rows[loose]
    if existing is None:
        rows[key] = row
        order.append(key)
        return

    # Merge into the copy we already hold.
    rank = {"primary": 0, "safety": 1, "subgroup": 2, "secondary": 3}
    if rank[row["kind"]] < rank[existing["kind"]]:
        # The better-labelled copy also carries the quote that justifies
        # the label.
        existing["kind"] = row["kind"]
        existing["name"] = row["name"]
        existing["quote"] = row["quote"]
    elif row["kind"] == existing["kind"] and len(row["quote"]) < len(existing["quote"]):
        existing["quote"] = row["quote"]
    for field in ("confidence_interval", "p_value", "direction"):
        if not existing.get(field) and row.get(field):
            existing[field] = row[field]
    existing["confidence"] = max(existing["confidence"], row["confidence"])



#: Field path -> extractor.  ``pipeline`` walks this table for both the offline
#: engine and the LLM backfill pass.
FIELD_EXTRACTORS: dict[str, Callable[[Sequence[Sentence]], RuleHit | None]] = {
    "pico.population": extract_population,
    "pico.intervention": extract_intervention,
    "pico.comparison": extract_comparison,
    "pico.outcome": extract_primary_outcome,
    "design.design": extract_design,
    "design.randomised": extract_randomised,
    "design.blinding": extract_blinding,
    "design.setting": extract_setting,
    "design.duration": extract_duration,
    "design.registration_id": extract_registration,
    "population.sample_size": extract_sample_size,
    "population.age": extract_age,
    "population.sex_distribution": extract_sex,
    "population.inclusion_criteria": extract_inclusion,
    "population.exclusion_criteria": extract_exclusion,
    "limitations": extract_limitations,
    "conclusion": extract_conclusion,
    "funding": extract_funding,
}

#: Fields where a deterministic pattern is at least as reliable as generation.
#: These are the ones the LLM path is allowed to backfill from.
HIGH_PRECISION_FIELDS = frozenset(
    {
        "design.registration_id",
        "design.blinding",
        "design.design",
        "population.sample_size",
        "population.age",
        "population.sex_distribution",
        "funding",
    }
)
