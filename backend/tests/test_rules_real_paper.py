"""Rule-engine regressions from a real paper.

Every sentence below is copied from the RECOVERY dexamethasone report (NEJM
2021;384:693-704), including the PDF artefacts a real upload produces: a
running "Primary Outcome" heading fused onto the next sentence, a funder
disclaimer spliced onto a population phrase by column reordering, and a
Kaplan-Meier panel flattened into prose.

Each test pins one error the engine made on the first real-paper run.  The
synthetic gold set could not catch any of them: its sentences were written for
the rules.
"""

from __future__ import annotations

from app.extraction import rules
from app.extraction.rules import Sentence

ABSTRACT_METHODS = (
    "In this controlled, open-label trial comparing a range of possible treatments in "
    "patients who were hospitalized with Covid-19, we randomly assigned patients to "
    "receive oral or intravenous dexamethasone (at a dose of 6 mg once daily) for up to "
    "10 days or to receive usual care alone."
)
PRIMARY_DEF = "The primary outcome was 28-day mortality."
TWO_ARM = (
    "A total of 2104 patients were assigned to receive dexamethasone and 4321 to "
    "receive usual care."
)
ABSTRACT_RESULT = (
    "Overall, 482 patients (22.9%) in the dexamethasone group and 1110 patients (25.7%) "
    "in the usual care group died within 28 days after randomization (age-adjusted rate "
    "ratio, 0.83; 95% confidence interval [CI], 0.75 to 0.93; P<0.001)."
)
SUBGROUPS = (
    "In the dexamethasone group, the incidence of death was lower than that in the usual "
    "care group among patients receiving invasive mechanical ventilation (29.3% vs. "
    "41.4%; rate ratio, 0.64; 95% CI, 0.51 to 0.81) and among those receiving oxygen "
    "without invasive mechanical ventilation (23.3% vs. 26.2%; rate ratio, 0.82; 95% CI, "
    "0.72 to 0.94) but not among those who were receiving no respiratory support at "
    "randomization (17.8% vs. 14.0%; rate ratio, 1.19; 95% CI, 0.91 to 1.55)."
)
MAIN_PRIMARY = (
    "Primary Outcome Mortality at 28 days was significantly lower in the dexamethasone "
    "group than in the usual care group, with deaths reported in 482 of 2104 patients "
    "(22.9%) and in 1110 of 4321 patients (25.7%), respectively (rate ratio, 0.83; 95% "
    "confidence interval [CI], 0.75 to 0.93; P<0.001) (Fig. 2A)."
)
FIGURE_NOISE = (
    "Patients who were receiving invasive mechan- Dexamethasone in Hospitalized Patients "
    "with Covid-19 Invasive Mechanical Ventilation (N=1007) A All Participants (N=6425) "
    "B 50 Rate ratio, 0.83 (95% CI, 0.75–0.93) P<0.001 40 Mortality (%) 30 Usual care 20 "
    "Dexamethasone 10 0 0 7 14 21 28 Days since Randomization No. at Risk Usual care "
    "Dexamethasone 4321 2104 3754 1903 3427 1725 3271 1659 3205 1621"
)
SPLICED_DISCLAIMER = (
    "Patients with Covid-19 had no role in the analysis of the data, in the preparation "
    "or approval of the manuscript, or in the decision to submit the manuscript for "
    "publication."
)
POWER = (
    "We estimated that 2000 patients in the dexamethasone group and 4000 in the usual "
    "care group would provide a power of at least 90% at a two-sided P value of 0.01 to "
    "detect a proportional reduction in 28-day mortality of 20%."
)
AGE_DIFFERENCE = (
    "The mean age was 1.1 years older among patients in the dexamethasone group than "
    "among those in the usual care group."
)
ELIGIBILITY = (
    "Patients were eligible for the trial if they had clinically suspected or "
    "laboratory-confirmed SARS-CoV-2 infection and no medical history that might put "
    "the patient at substantial risk if they were to participate in the trial."
)
PROTOCOL_LIMIT = (
    "Initially, recruitment was limited to patients who were at least 18 years of age, "
    "but the age limit was removed starting on May 9, 2020."
)
ABSTRACT_CONCLUSION = (
    "In patients hospitalized with Covid-19, the use of dexamethasone resulted in lower "
    "28-day mortality among those who were receiving either invasive mechanical "
    "ventilation or oxygen alone at randomization but not among those receiving no "
    "respiratory support."
)
INTRO_TAIL = (
    "Here, we report the preliminary results of the controlled, open-label Randomized "
    "Evaluation of Covid-19 Therapy (RECOVERY) trial of dexamethasone in patients "
    "hospitalized with Covid-19."
)

PAPER = [
    Sentence("abstract", ABSTRACT_METHODS),
    Sentence("abstract", PRIMARY_DEF),
    Sentence("abstract", TWO_ARM),
    Sentence("abstract", ABSTRACT_RESULT),
    Sentence("abstract", SUBGROUPS),
    # NEJM's abstract CONCLUSIONS heading opens a section that runs on into the
    # unheaded introduction -- the shape that made "conclusion" quote the intro.
    Sentence("conclusion", ABSTRACT_CONCLUSION),
    Sentence("conclusion", INTRO_TAIL),
    Sentence("methods", SPLICED_DISCLAIMER),
    Sentence("methods", ELIGIBILITY),
    Sentence("methods", PROTOCOL_LIMIT),
    Sentence("methods", POWER),
    Sentence("results", AGE_DIFFERENCE),
    Sentence("results", MAIN_PRIMARY),
    Sentence("results", FIGURE_NOISE),
]


def test_population_is_the_trial_population_not_a_disclaimer():
    hit = rules.extract_population(PAPER)
    assert hit is not None
    assert hit.value == "patients who were hospitalized with Covid-19"
    assert "no role" not in hit.quote


def test_intervention_stops_at_the_comparator():
    hit = rules.extract_intervention(PAPER)
    assert hit is not None
    assert hit.value.startswith("oral or intravenous dexamethasone")
    assert "usual care" not in hit.value
    assert "4321" not in hit.value


def test_comparison_comes_from_the_allocation_sentence_not_the_power_calculation():
    hit = rules.extract_comparison(PAPER)
    assert hit is not None
    assert hit.value == "usual care alone"
    assert "power" not in hit.quote


def test_two_arm_sample_size_is_summed():
    hit = rules.extract_sample_size(PAPER)
    assert hit is not None
    assert hit.value.startswith("6425")


def test_between_group_age_difference_is_not_an_age():
    assert rules.extract_age(PAPER) is None


def test_eligible_for_the_trial_if_is_an_inclusion_criterion():
    hit = rules.extract_inclusion(PAPER)
    assert hit is not None
    assert "SARS-CoV-2" in hit.value


def test_protocol_age_limit_is_not_a_limitation():
    assert rules.extract_limitations(PAPER) is None


def test_conclusion_section_contributes_its_first_sentence():
    hit = rules.extract_conclusion(PAPER)
    assert hit is not None
    assert hit.quote == ABSTRACT_CONCLUSION


def test_outcomes_parse_ci_with_bracketed_abbreviation():
    outcomes = rules.extract_outcomes(PAPER)
    primary = [o for o in outcomes if o["kind"] == "primary"]
    assert len(primary) == 1
    assert primary[0]["effect_size"] == "0.83"
    assert primary[0]["confidence_interval"] == "95% CI 0.75 to 0.93"


def test_one_result_reported_three_times_is_one_row():
    outcomes = rules.extract_outcomes(PAPER)
    assert sum(1 for o in outcomes if o["effect_size"] == "0.83") == 1


def test_figure_axis_text_never_becomes_a_quote():
    outcomes = rules.extract_outcomes(PAPER)
    assert all("No. at Risk" not in o["quote"] for o in outcomes)


def test_every_subgroup_in_one_sentence_is_kept_and_labelled():
    outcomes = rules.extract_outcomes(PAPER, limit=10)
    subgroup = {o["effect_size"]: o for o in outcomes if o["kind"] == "subgroup"}
    assert set(subgroup) == {"0.64", "0.82", "1.19"}
    assert "invasive mechanical ventilation" in subgroup["0.64"]["name"]
    assert subgroup["1.19"]["direction"] == "no_difference"
    assert not any(o["name"].lower() in {"however", "overall"} for o in outcomes)


# ------------------------------------------------------------- sectioniser
NEJM_FRONT = """Dexamethasone in Hospitalized Patients with Covid-19
The RECOVERY Collaborative Group*
ABSTRACT
BACKGROUND
Coronavirus disease 2019 (Covid-19) is associated with diffuse lung damage.
METHODS
In this controlled, open-label trial, we randomly assigned patients to receive dexamethasone or usual care alone. The primary outcome was 28-day mortality.
RESULTS
A total of 2104 patients were assigned to receive dexamethasone and 4321 to receive usual care.
CONCLUSIONS
In patients hospitalized with Covid-19, the use of dexamethasone resulted in lower 28-day mortality among those receiving invasive mechanical ventilation. (Funded by the Medical Research Council; ClinicalTrials.gov number, NCT04381936.)
The members of the writing committee assume responsibility for the overall content.
Glucocorticoids have been widely used in syndromes closely related to Covid-19. Here, we report the preliminary results of the RECOVERY trial.
Methods
Trial Design and Oversight
The RECOVERY trial is an investigator-initiated, open-label trial.
Results
Patients were recruited at 176 NHS hospitals.
Discussion
Our trial has several limitations.
"""


def test_structured_abstract_does_not_swallow_the_introduction():
    from app.ingest.sectioniser import detect_sections

    sections = {s.name: s for s in detect_sections(NEJM_FRONT)}
    conclusion = [s for s in detect_sections(NEJM_FRONT) if s.name == "conclusion"]
    assert len(conclusion) == 1
    assert "resulted in lower 28-day mortality" in conclusion[0].text
    assert "Glucocorticoids have been widely used" not in conclusion[0].text
    assert "Glucocorticoids have been widely used" in sections["background"].text
    methods = [s for s in detect_sections(NEJM_FRONT) if s.name == "methods"]
    assert len(methods) == 1 and "investigator-initiated" in methods[0].text


# ------------------------------------------------- abstract-only record
# The same trial imported as an abstract (e.g. from PubMed): no "Primary
# Outcome" heading in the results, no "randomised" anywhere.
ABSTRACT_ONLY = [
    Sentence("abstract", ABSTRACT_METHODS),
    Sentence("abstract", PRIMARY_DEF),
    Sentence("abstract", TWO_ARM),
    Sentence("abstract", ABSTRACT_RESULT),
    Sentence("abstract", SUBGROUPS),
]


def test_randomly_assigned_trial_is_an_rct_without_the_word_randomised():
    design = rules.extract_design(ABSTRACT_ONLY)
    assert design is not None and design.value == "randomised controlled trial"
    assert rules.extract_randomised(ABSTRACT_ONLY) is not None


def test_primary_outcome_value_drops_the_sentence_frame():
    hit = rules.extract_primary_outcome(ABSTRACT_ONLY)
    assert hit is not None and hit.value == "28-day mortality"


def test_headline_result_is_primary_when_no_result_says_primary():
    outcomes = rules.extract_outcomes(ABSTRACT_ONLY, limit=10)
    primary = [o for o in outcomes if o["kind"] == "primary"]
    assert len(primary) == 1
    assert primary[0]["effect_size"] == "0.83"
    assert primary[0]["name"] == "Mortality within 28 days"
    assert primary[0]["confidence"] <= 0.7


def test_subgroup_rows_are_named_by_the_subgroup_alone():
    outcomes = rules.extract_outcomes(ABSTRACT_ONLY, limit=10)
    names = {o["effect_size"]: o["name"] for o in outcomes if o["kind"] == "subgroup"}
    assert names["0.64"] == "Receiving invasive mechanical ventilation"
    assert "lower than" not in " ".join(names.values())
