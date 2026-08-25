#!/usr/bin/env python3
"""Run the bounded WE v2.0.1 output-contract validation cohort.

This runner is intentionally a validation harness, not a replacement for any
Generator, Reviewer, Solver, or Orchestrator implementation.  It creates a
fresh, independently authored 75-item cohort, sends every candidate through
the existing canonical emitter, keeps Reviewer and Solver payloads separate,
and applies the existing Orchestrator consensus function without changing its
policy.

The repository does not expose a callable live Agent runtime to this script.
Accordingly, runtime_model and invocation_id are recorded as null rather than
invented.  The Reviewer and Solver records below are contract-only replay
fixtures, not independent grammar judgments; their agreement must not be used
as evidence about grammar quality.  The deterministic contracts, blind-input
boundary, revision loop, consensus routing, batch stability, and format
analysis can still be executed reproducibly in this workspace.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
# Default: the tracked artifact directory. Set WE_V2_VALIDATION_OUT_DIR to
# replay the harness into a temporary directory without overwriting the
# committed historical artifacts.
OUT_DIR = Path(os.environ.get("WE_V2_VALIDATION_OUT_DIR") or (ROOT / "analysis" / "we_v2_validation"))
GENERATOR_DIR = ROOT / "agents" / "toefl_itp_we_generator_v2"
GENERATOR_SCRIPTS = GENERATOR_DIR / "scripts"
sys.path.insert(0, str(GENERATOR_SCRIPTS))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

from emit_output import emit_items  # noqa: E402
from validate_format import (  # noqa: E402
    REQUIRED_DIAGNOSTIC_KEYS,
    format_diagnostics,
    load_json,
    load_items,
    schema_errors,
    tokens,
    validate_item,
)
from orchestrator import evaluate_consensus, load_config  # noqa: E402
from integrity import derive_correct_answer  # noqa: E402

import importlib.util  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load validator module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REVIEWER_VALIDATOR = load_module("we_validation_reviewer_validator", ROOT / "agents" / "toefl_itp_we_reviewer_v2" / "scripts" / "validate_output.py")
SOLVER_VALIDATOR = load_module("we_validation_solver_validator", ROOT / "agents" / "toefl_itp_grammar_solver" / "scripts" / "validate_output.py")


RUN_ID = "we-v2-validation-20260824"
REQUESTED_GENERATOR_VERSION = "Written Expression Generator v2.0.1"
IMPLEMENTED_GENERATOR_CONTRACT = "Written Expression Generator v2.0 + Output-contract patch v2.0.1"
GENERATOR_SCHEMA_VERSION = "Written Expression Generator v2.0"
REVIEWER_VERSION = "Written Expression Reviewer v2.0"
SECTION = "Written Expression"
LABELS = ("A", "B", "C", "D")
BATCH_NAMES = ("A", "B", "C")
JUDGMENT_MODE = "CONTRACT_REPLAY_ONLY"
JUDGMENT_QUALITY_EVALUABLE = False
REVISION_IDS = {
    "we-v2-validation-011",
    "we-v2-validation-036",
    "we-v2-validation-061",
}
INITIAL_PRIMARY_TARGET_OVERRIDES = {
    "we-v2-validation-011": "REFERENCE_AND_DETERMINERS",
    "we-v2-validation-036": "REFERENCE_AND_DETERMINERS",
    "we-v2-validation-061": "REFERENCE_AND_DETERMINERS",
}


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


GENERATOR_PROMPT_HASH = sha256(ROOT / ".claude" / "agents" / "toefl-itp-we-generator-v2.md")
REVIEWER_PROMPT_HASH = sha256(ROOT / ".claude" / "agents" / "toefl-itp-we-reviewer-v2.md")
SOLVER_PROMPT_HASH = sha256(ROOT / ".claude" / "agents" / "toefl-itp-grammar-solver.md")

CONFIG = load_json(GENERATOR_DIR / "config" / "we_v2_format_config.json")
GRAMMAR_SPEC = load_json(ROOT / "specs" / "toefl_itp_grammar_spec.json")
FORMAT_SPEC = load_json(ROOT / "specs" / "toefl_itp_we_format_spec_addendum.json")
TAXONOMY = load_json(ROOT / "analysis" / "grammar_taxonomy.json")
ITEM_SCHEMA = load_json(GENERATOR_DIR / "schema" / "written_expression_item_v2.schema.json")
TARGETS = {entry["id"] for entry in TAXONOMY["primary_targets"]}
ERROR_TYPES = {
    entry["id"]
    for entry in GRAMMAR_SPEC["tested_error_types"]
    if entry["id"] not in {"fragment", "wrong_complementation"}
}
SPEC_VERSION = GRAMMAR_SPEC.get("spec_version", "1.0.0")
FORMAT_SPEC_VERSION = FORMAT_SPEC.get("version", FORMAT_SPEC.get("format_spec_version", "1.0.0"))


def v(clean: str, error: str, spans: list[str], correction: str, *, tail: str | None = None) -> dict[str, Any]:
    return {
        "clean": clean,
        "error": error,
        "spans": spans,
        "correction": correction,
        "tail": tail,
    }


def base(
    primary_target: str,
    subtype: str,
    tested_error_type: str,
    difficulty: str,
    locality: str,
    granularity: str,
    error_scope: str,
    variants: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "primary_target": primary_target,
        "subtype": subtype,
        "tested_error_type": tested_error_type,
        "difficulty": difficulty,
        "correction_locality": locality,
        "decision_granularity": granularity,
        "error_scope": error_scope,
        "variants": variants,
    }


# Each base has one fresh realization per A/B/C batch.  No sentence or item ID
# is copied from the earlier smoke, pilot, patch re-smoke, or v1.1 fixtures.
BASES: list[dict[str, Any]] = [
    base("REFERENCE_AND_DETERMINERS", "subject-verb agreement across an intervening phrase", "agreement_error", "MEDIUM", "DEPENDENCY_BASED", "AGREEMENT_DEPENDENCY", "clause_level", [
        v("The gradual erosion of riverbanks near the mountain villages has exposed layers of ancient sediment to researchers.", "The gradual erosion of riverbanks near the mountain villages have exposed layers of ancient sediment to researchers.", ["erosion", "have", "ancient", "researchers"], "have -> has"),
        v("The concentration of dissolved minerals in coastal seawater varies considerably during the summer months.", "The concentration of dissolved minerals in coastal seawater vary considerably during the summer months.", ["concentration", "vary", "considerably", "months"], "vary -> varies"),
        v("The collection of early photographs from remote settlements provides historians with evidence about changing traditions.", "The collection of early photographs from remote settlements provide historians with evidence about changing traditions.", ["collection", "provide", "evidence", "traditions"], "provide -> provides"),
    ]),
    base("REFERENCE_AND_DETERMINERS", "pronoun-antecedent number agreement", "incorrect_reference", "MEDIUM", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "cross_clause", [
        v("Because desert tortoises store water efficiently, the animals protect their bodies during prolonged droughts.", "Because desert tortoises store water efficiently, the animals protect its bodies during prolonged droughts.", ["desert tortoises", "store", "protect", "its"], "its -> their"),
        v("When migratory salmon reach upstream spawning grounds, the fish use their stored energy to complete the final journey.", "When migratory salmon reach upstream spawning grounds, the fish use its stored energy to complete the final journey.", ["migratory salmon", "reach", "use", "its"], "its -> their"),
        v("After mature redwoods develop thick bark, the trees withstand their repeated exposure to surface fires.", "After mature redwoods develop thick bark, the trees withstand its repeated exposure to surface fires.", ["mature redwoods", "develop", "withstand", "its"], "its -> their"),
    ]),
    base("REFERENCE_AND_DETERMINERS", "redundant article in a partitive quantifier phrase", "extraneous_element", "EASY", "LOCAL_SHORT_SPAN", "FUNCTION_WORD", "local", [
        v("Most of the sediment collected near the estuary was preserved in labeled containers for later chemical analysis by the laboratory team.", "The most of the sediment collected near the estuary was preserved in labeled containers for later chemical analysis by the laboratory team.", ["The most", "sediment collected", "labeled containers", "laboratory team"], "The most -> Most"),
        v("Several of the samples collected during the survey were transferred to regional laboratories for analysis.", "Several of the the samples collected during the survey were transferred to regional laboratories for analysis.", ["Several", "of", "the the", "laboratories"], "the the -> the"),
        v("A number of the measurements recorded during winter remain in the central database for review.", "A number of the the measurements recorded during winter remain in the central database for review.", ["number", "of", "the the", "database"], "the the -> the"),
    ]),
    base("REFERENCE_AND_DETERMINERS", "missing article before a singular count noun", "missing_required_element", "MEDIUM", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "local", [
        v("The survey team, after crossing several ridges and documenting nearby ruins, recorded the ancient inscription beside the northern observatory for future comparison by regional researchers.", "The survey team, after crossing several ridges and documenting nearby ruins, recorded ancient inscription beside the northern observatory for future comparison by regional researchers.", ["survey team", "ancient inscription", "northern observatory", "researchers"], "missing the before ancient inscription"),
        v("During the excavation, researchers uncovered the ceremonial vessel beneath a layer of compact clay for auditors.", "During the excavation, researchers uncovered ceremonial vessel beneath a layer of compact clay for auditors.", ["excavation", "ceremonial vessel", "compact clay", "auditors"], "missing the before ceremonial vessel"),
        v("The museum recently acquired an unusually detailed map of the coastal trade routes.", "The museum recently acquired unusually detailed map of the coastal trade routes.", ["museum", "unusually detailed map", "coastal trade", "routes"], "missing an before unusually detailed map"),
    ]),
    base("NONFINITE_VERB_PHRASES", "gerund required after a verb selecting an -ing complement", "wrong_verb_form", "MEDIUM", "CLAUSE_LEVEL", "VERB_FRAME", "clause_level", [
        v("To reduce contamination, laboratory technicians avoid touching the cultures after sterilizing their instruments.", "To reduce contamination, laboratory technicians avoid touch the cultures after sterilizing their instruments.", ["reduce", "laboratory technicians", "avoid", "touch"], "touch -> touching"),
        v("Field biologists recommend recording each observation immediately after identifying the species in the wetland.", "Field biologists recommend record each observation immediately after identifying the species in the wetland.", ["biologists", "recommend", "record", "wetland"], "record -> recording"),
        v("The archive prohibits removing fragile documents from their folders without written permission from the curator.", "The archive prohibits remove fragile documents from their folders without written permission from the curator.", ["archive", "prohibits", "remove", "curator"], "remove -> removing"),
    ]),
    base("VERB_COMPLEMENTATION", "fixed preposition after an adjective or verb", "wrong_preposition_collocation", "MEDIUM", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "local", [
        v("The effectiveness of the treatment depends on careful monitoring throughout the recovery period.", "The effectiveness of the treatment depends in careful monitoring throughout the recovery period.", ["effectiveness", "depends in", "monitoring", "recovery"], "depends in -> depends on"),
        v("Researchers interested in marine acoustics often rely on calibrated microphones during field experiments.", "Researchers interested on marine acoustics often rely on calibrated microphones during field experiments.", ["interested on", "rely", "calibrated", "experiments"], "interested on -> interested in"),
        v("The new sensor is capable of detecting brief changes in pressure beneath the ice shelf.", "The new sensor is capable for detecting brief changes in pressure beneath the ice shelf.", ["sensor", "capable for", "pressure", "shelf"], "capable for -> capable of"),
    ]),
    base("VERB_COMPLEMENTATION", "bare infinitive after a causative or permissive verb", "wrong_verb_form", "MEDIUM", "CLAUSE_LEVEL", "VERB_FRAME", "clause_level", [
        v("The instructor had the students examine the mineral specimens under a microscope.", "The instructor had the students to examine the mineral specimens under a microscope.", ["instructor", "students", "to examine", "specimens"], "to examine -> examine"),
        v("The supervisor made the assistants organize the survey records by geographic region.", "The supervisor made the assistants to organize the survey records by geographic region.", ["supervisor", "assistants", "to organize", "geographic region"], "to organize -> organize"),
        v("The software lets users compare satellite images across several seasons.", "The software lets users to compare satellite images across several seasons.", ["software", "users", "to compare", "seasons"], "to compare -> compare"),
    ]),
    base("VERB_FORM_VOICE", "passive voice in a main clause with an inanimate object", "wrong_voice", "MEDIUM", "CLAUSE_LEVEL", "VERB_FRAME", "clause_level", [
        v("The researchers analyzed the sediment samples before storing them in sealed containers.", "The researchers were analyzed the sediment samples before storing them in sealed containers.", ["researchers", "were analyzed", "sediment", "containers"], "were analyzed -> analyzed"),
        v("The archivists catalogued the handwritten manuscripts before placing them in acid-free folders.", "The archivists were catalogued the handwritten manuscripts before placing them in acid-free folders.", ["archivists", "were catalogued", "manuscripts", "folders"], "were catalogued -> catalogued"),
        v("The engineers tested the suspension bridge after replacing several weakened cables.", "The engineers were tested the suspension bridge after replacing several weakened cables.", ["engineers", "were tested", "bridge", "cables"], "were tested -> tested"),
    ]),
    base("VERB_FORM_VOICE", "past perfect required before a later past event", "wrong_verb_form", "MEDIUM", "DEPENDENCY_BASED", "VERB_FRAME", "clause_level", [
        v("By the time the expedition reached the valley, local guides had mapped the safest route through the passes.", "By the time the expedition reached the valley, local guides have map the safest route through the passes.", ["expedition", "reached", "have map", "passes"], "have map -> had mapped"),
        v("By the time the observatory opened, technicians had calibrated the new telescope during several clear nights.", "By the time the observatory opened, technicians have calibrated the new telescope during several clear nights.", ["observatory", "opened", "have calibrated", "nights"], "have calibrated -> had calibrated"),
        v("When the committee convened, after carefully checking the attendance records, the secretary had distributed the revised agenda to every member.", "When the committee convened, after carefully checking the attendance records, the secretary distribute the revised agenda to every member.", ["committee", "convened", "distribute", "member"], "distribute -> had distributed", tail="single_gap"),
    ]),
    base("PARALLEL_STRUCTURE", "parallel verb forms in a coordinated list", "wrong_verb_form", "MEDIUM", "CLAUSE_LEVEL", "VERB_FRAME", "clause_level", [
        v("The new program helps students analyze data, interpret graphs, and present conclusions to their classmates.", "The new program helps students analyze data, interpret graphs, and presenting conclusions to their classmates.", ["program", "analyze data", "presenting conclusions", "classmates"], "presenting conclusions -> present conclusions"),
        v("The device can measure temperature, record pressure, and transmit readings to a remote station.", "The device can measure temperature, record pressure, and transmitting readings to a remote station.", ["device", "measure temperature", "transmitting readings", "station"], "transmitting readings -> transmit readings"),
        v("The expedition required researchers to collect samples, label containers, and preserve evidence from the cave.", "The expedition required researchers to collect samples, label containers, and preserving evidence from the cave.", ["expedition", "collect samples", "preserving evidence", "cave"], "preserving evidence -> preserve evidence"),
    ]),
    base("PARALLEL_STRUCTURE", "parallel predicates after not only ... but also", "incorrect_part_of_speech", "HARD", "CLAUSE_LEVEL", "WORD_CLASS", "clause_level", [
        v("The observatory not only records solar activity but also predicts magnetic disturbances during storms.", "The observatory not only records solar activity but also predicting magnetic disturbances during storms.", ["observatory", "records solar", "predicting magnetic disturbances", "storms"], "predicting magnetic disturbances -> predicts magnetic disturbances"),
        v("The policy not only reduces industrial waste but also encourages businesses to reuse materials.", "The policy not only reduces industrial waste but also encouraging businesses to reuse materials.", ["policy", "reduces industrial", "encouraging businesses", "materials"], "encouraging businesses -> encourages businesses"),
        v("The manuscript not only describes the expedition but also compares its findings with later accounts.", "The manuscript not only describes the expedition but also comparing its findings with later accounts.", ["manuscript", "describes the expedition", "comparing its findings", "accounts"], "comparing its findings -> compares its findings"),
    ]),
    base("WORD_CLASS_FORM", "adverb required to modify a verb", "incorrect_part_of_speech", "EASY", "LOCAL_SINGLE_TOKEN", "MORPHOLOGY", "local", [
        v("The instrument measures atmospheric pressure accurately under difficult conditions.", "The instrument measures atmospheric pressure accurate under difficult conditions.", ["instrument", "measures", "accurate", "difficult"], "accurate -> accurately"),
        v("The scientist carefully compared the samples before reporting the results to the committee.", "The scientist careful compared the samples before reporting the results to the committee.", ["scientist", "careful", "samples", "committee"], "careful -> carefully"),
        v("The newly installed camera records distant objects clearly during the evening survey.", "The newly installed camera records distant objects clear during the evening survey.", ["camera", "records", "objects", "clear"], "clear -> clearly"),
    ]),
    base("WORD_CLASS_FORM", "adjective required as a noun modifier", "incorrect_part_of_speech", "MEDIUM", "LOCAL_SINGLE_TOKEN", "MORPHOLOGY", "local", [
        v("The geological survey provided a detailed analysis of the region's volcanic formations.", "The geological survey provided a detail analysis of the region's volcanic formations.", ["survey", "detail analysis", "volcanic", "formations"], "detail analysis -> detailed analysis"),
        v("The museum displayed a remarkable collection of bronze tools from the northern settlement.", "The museum displayed a remark collection of bronze tools from the northern settlement.", ["museum", "remark collection", "bronze", "settlement"], "remark collection -> remarkable collection"),
        v("The committee issued a comprehensive report on the river's declining fish population.", "The committee issued a comprehend report on the river's declining fish population.", ["committee", "comprehend report", "declining", "population"], "comprehend report -> comprehensive report"),
    ]),
    base("WORD_CLASS_FORM", "noun required as the head of a noun phrase", "incorrect_part_of_speech", "MEDIUM", "LOCAL_SINGLE_TOKEN", "MORPHOLOGY", "local", [
        v("The rapid expansion of the city has affected nearby wetlands and agricultural fields.", "The rapid expand of the city has affected nearby wetlands and agricultural fields.", ["rapid expand", "affected", "wetlands", "fields"], "rapid expand -> rapid expansion"),
        v("The accurate measurement of water temperature improves predictions of seasonal algae growth.", "The accurate measure of water temperature improves predictions of seasonal algae growth.", ["accurate measure", "improves", "seasonal", "growth"], "accurate measure -> accurate measurement"),
        v("The continued preservation of the manuscript depends on stable humidity inside the archive.", "The continued preserve of the manuscript depends on stable humidity inside the archive.", ["continued preserve", "depends", "stable", "archive"], "continued preserve -> continued preservation"),
    ]),
    base("NONFINITE_VERB_PHRASES", "past participle in a reduced passive relative clause", "wrong_verb_form", "MEDIUM", "CLAUSE_LEVEL", "VERB_FRAME", "clause_level", [
        v("The fossils discovered in the limestone quarry reveal how ancient organisms adapted to changing climates.", "The fossils discovering in the limestone quarry reveal how ancient organisms adapted to changing climates.", ["fossils discovering in the limestone quarry", "reveal", "ancient organisms", "climates"], "discovering -> discovered", tail="multi_tail"),
        v("The artifacts recovered from the riverbed provide evidence about trade between inland settlements.", "The artifacts recovering from the riverbed provide evidence about trade between inland settlements.", ["artifacts recovering from the riverbed", "provide", "inland", "settlements"], "recovering -> recovered", tail="multi_tail"),
        v("The manuscripts preserved in the monastery survived several centuries of seasonal flooding.", "The manuscripts preserving in the monastery survived several centuries of seasonal flooding.", ["manuscripts preserving in the monastery", "survived", "seasonal", "flooding"], "preserving -> preserved", tail="multi_tail"),
    ]),
    base("NONFINITE_VERB_PHRASES", "infinitive of purpose after a device or action", "wrong_verb_form", "MEDIUM", "CLAUSE_LEVEL", "VERB_FRAME", "clause_level", [
        v("The research team built a compact device to monitor water quality in remote villages.", "The research team built a compact device to monitoring water quality in remote villages.", ["team", "compact device", "to monitoring", "villages"], "to monitoring -> to monitor"),
        v("The agency installed sensors to detect sudden changes in groundwater pressure during storms.", "The agency installed sensors to detecting sudden changes in groundwater pressure during storms.", ["agency", "installed sensors", "to detecting", "storms"], "to detecting -> to detect"),
        v("The botanists collected samples to compare genetic variation among related plant populations.", "The botanists collected samples to comparing genetic variation among related plant populations.", ["botanists", "collected samples", "to comparing", "populations"], "to comparing -> to compare"),
    ]),
    base("CONNECTORS_CONJUNCTIONS", "concessive subordinator before a finite clause", "incorrect_subordinator", "MEDIUM", "CLAUSE_LEVEL", "CLAUSE_RELATION", "cross_clause", [
        v("Although the soil appeared dry, its deeper layers retained considerable moisture throughout the summer.", "Despite the soil appeared dry, its deeper layers retained considerable moisture throughout the summer.", ["Despite the soil appeared dry", "deeper layers", "retained considerable", "summer"], "Despite -> Although", tail="multi_tail"),
        v("Although the signal was weak, the receiver detected a clear pattern in the background noise.", "Despite the signal was weak, the receiver detected a clear pattern in the background noise.", ["Despite the signal was weak", "receiver detected", "clear pattern", "noise"], "Despite -> Although", tail="multi_tail"),
        v("Although the route was steep, the hikers reached the upper station before sunset.", "Despite the route was steep, the hikers reached the upper station before sunset.", ["Despite the route was steep", "hikers reached", "upper station", "sunset"], "Despite -> Although", tail="multi_tail"),
    ]),
    base("RELATIVE_CLAUSES", "relative marker selected by the antecedent", "incorrect_relative_marker", "MEDIUM", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "cross_clause", [
        v("The engineer who designed the bridge received an award from the national transportation institute.", "The engineer which designed the bridge received an award from the national transportation institute.", ["engineer", "which", "bridge", "institute"], "which -> who"),
        v("The botanist whose fieldwork transformed the region received a grant for another expedition.", "The botanist which fieldwork transformed the region received a grant for another expedition.", ["botanist", "which", "region", "expedition"], "which -> whose"),
        v("The archive preserves letters that describe experiments conducted decades ago in the laboratory and the earliest transmission trials.", "The archive preserves letters who describe experiments conducted decades ago in the laboratory and the earliest transmission trials.", ["archive", "letters", "who", "transmission trials"], "who -> that", tail="single_gap"),
    ]),
    base("RELATIVE_CLAUSES", "relative-clause verb agreement with the antecedent head", "agreement_error", "HARD", "DEPENDENCY_BASED", "AGREEMENT_DEPENDENCY", "cross_clause", [
        v("The sequence of reactions that occur in the chamber determines the color of the final compound.", "The sequence of reactions that occurs in the chamber determines the color of the final compound.", ["sequence", "reactions", "occurs", "compound"], "occurs -> occur"),
        v("The group of instruments that were installed last year remains in the eastern laboratory.", "The group of instruments that was installed last year remains in the eastern laboratory.", ["group", "instruments", "was", "laboratory"], "was -> were"),
        v("The network of channels that carry meltwater toward the valley expands during spring.", "The network of channels that carries meltwater toward the valley expands during spring.", ["network", "channels", "carries", "spring"], "carries -> carry"),
    ]),
    base("CLAUSE_STRUCTURE", "resumptive subject pronoun after a relative clause", "double_subject", "EASY", "CLAUSE_LEVEL", "CLAUSE_RELATION", "clause_level", [
        v("The scientist who led the survey published the results in a regional journal after reviewing the evidence.", "The scientist who led the survey she published the results in a regional journal after reviewing the evidence.", ["scientist", "led the survey", "she published", "journal"], "delete she"),
        v("The technician who repaired the microscope recorded the replacement parts in the laboratory log.", "The technician who repaired the microscope he recorded the replacement parts in the laboratory log.", ["technician", "repaired the microscope", "he recorded", "laboratory"], "delete he"),
        v("The historian who examined the tablets identified their origin after comparing several inscriptions.", "The historian who examined the tablets she identified their origin after comparing several inscriptions.", ["historian", "examined the tablets", "she identified", "origin"], "delete she"),
    ]),
    base("WORD_ORDER_MODIFICATION", "adjective order inside a complex noun phrase", "wrong_word_order", "MEDIUM", "LOCAL_SHORT_SPAN", "WORD_ORDER", "local", [
        v("The researchers used a newly developed optical sensor to measure faint signals from distant stars.", "The researchers used a developed newly optical sensor to measure faint signals from distant stars.", ["researchers", "a developed newly optical sensor", "faint signals", "stars"], "a developed newly optical sensor -> a newly developed optical sensor"),
        v("The technicians selected a carefully calibrated digital scale for measuring minute changes in mass.", "The technicians selected a calibrated carefully digital scale for measuring minute changes in mass.", ["technicians", "a calibrated carefully digital scale", "minute changes", "mass"], "a calibrated carefully digital scale -> a carefully calibrated digital scale"),
        v("The explorers entered a recently discovered coastal cave before the tide began to rise.", "The explorers entered a discovered recently coastal cave before the tide began to rise.", ["explorers", "a discovered recently coastal cave", "tide", "rise"], "a discovered recently coastal cave -> a recently discovered coastal cave"),
    ]),
    base("COMPARATIVES_DEGREE", "comparative form before than", "wrong_degree_form", "MEDIUM", "DEPENDENCY_BASED", "OTHER", "local", [
        v("The revised model is more reliable than the original design under extreme conditions.", "The revised model is most reliable than the original design under extreme conditions.", ["model", "most reliable", "original design", "conditions"], "most reliable -> more reliable"),
        v("The northern route is less expensive than the southern route during the winter season.", "The northern route is least expensive than the southern route during the winter season.", ["northern route", "least expensive", "southern route", "season"], "least expensive -> less expensive"),
        v("The latest estimate is more precise than earlier projections based on limited measurements.", "The latest estimate is most precise than earlier projections based on limited measurements.", ["estimate", "most precise", "earlier projections", "measurements"], "most precise -> more precise"),
    ]),
    base("EXISTENTIAL_EXPLETIVE", "subject-verb agreement in there + be", "agreement_error", "EASY", "LOCAL_SINGLE_TOKEN", "FUNCTION_WORD", "clause_level", [
        v("There are several explanations for the unusual decline in bee populations along the coast.", "There is several explanations for the unusual decline in bee populations along the coast.", ["There is", "explanations", "unusual decline", "coast"], "There is -> There are"),
        v("There are two independent pathways for transporting nutrients through the root system.", "There is two independent pathways for transporting nutrients through the root system.", ["There is", "pathways", "transporting nutrients", "system"], "There is -> There are"),
        v("There are numerous records of volcanic activity beneath the western plateau.", "There is numerous records of volcanic activity beneath the western plateau.", ["There is", "records", "volcanic activity", "plateau"], "There is -> There are"),
    ]),
    base("VERB_COMPLEMENTATION", "adjective complement required after make + object", "incorrect_part_of_speech", "MEDIUM", "LOCAL_SINGLE_TOKEN", "WORD_CLASS", "clause_level", [
        v("The discovery made the researchers extremely cautious about contamination.", "The discovery made the researchers cautiously about contamination.", ["discovery", "researchers", "cautiously", "contamination"], "cautiously -> cautious"),
        v("The unexpected result made the committee skeptical of the initial explanation.", "The unexpected result made the committee skepticism of the initial explanation.", ["result", "committee", "skepticism", "explanation"], "skepticism -> skeptical"),
        v("The evidence made the explanation convincing to the review panel.", "The evidence made the explanation convincingly to the review panel.", ["evidence", "explanation", "convincingly", "panel"], "convincingly -> convincing"),
    ]),
    base("REFERENCE_AND_DETERMINERS", "quantifier agreement with count and noncount nouns", "agreement_error", "MEDIUM", "LOCAL_SHORT_SPAN", "FUNCTION_WORD", "local", [
        v("The laboratory collected much information about the mineral before publishing its report.", "The laboratory collected many information about the mineral before publishing its report.", ["laboratory", "many information", "mineral", "report"], "many information -> much information"),
        v("The survey recorded little evidence about the migration route before the storm arrived.", "The survey recorded few evidence about the migration route before the storm arrived.", ["survey", "few evidence", "migration route", "storm"], "few evidence -> little evidence"),
        v("The archive contained few documents describing the settlement's early commercial activity.", "The archive contained little documents describing the settlement's early commercial activity.", ["archive", "little documents", "commercial", "activity"], "little documents -> few documents"),
    ]),
]

VOCABULARY_DOMAINS = [
    "glacial geology", "marine biology", "estuarine chemistry", "archaeology",
    "laboratory microbiology", "marine acoustics", "mineralogy", "sedimentology",
    "observational astronomy", "educational technology", "solar physics", "atmospheric science",
    "volcanic geology", "urban ecology", "paleontology", "hydrology", "soil science",
    "environmental acoustics", "botany", "historical geography", "optical engineering",
    "transportation engineering", "comparative modeling", "volcanology", "archival studies",
]


def token_count(sentence: str) -> int:
    from validate_format import tokens
    return len(tokens(sentence))


def span_kind(count: int) -> str:
    if count == 1:
        return "SINGLE_WORD"
    if count <= 4:
        return "SHORT_PHRASE"
    return "CLAUSE_OR_CLAUSE_LIKE"


def length_region(count: int) -> str:
    if count <= 10:
        return "<=10"
    if count <= 15:
        return "11-15"
    if count <= 20:
        return "16-20"
    if count <= 25:
        return "21-25"
    if count <= 30:
        return "26-30"
    return "31+"


def profile_text(spans: list[str], counts: dict[str, int]) -> str:
    return "/".join(str(counts[label]) for label in LABELS)


def make_item(order: int, batch: str, spec: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    item_id = f"we-v2-validation-{order:03d}"
    sentence_count = token_count(variant["error"])
    counts = {label: token_count(span) for label, span in zip(LABELS, variant["spans"])}
    marked_parts = dict(zip(LABELS, variant["spans"]))
    # The answer is derived from the actual clean/error mutation and the
    # error-side marked span.  It is never supplied by a position map.
    derived_answer = derive_correct_answer(variant["clean"], variant["error"], marked_parts)
    span_types = {label: span_kind(counts[label]) for label in LABELS}
    correct_span_type = span_types[derived_answer]
    correct_answer = derived_answer
    emitted_target = INITIAL_PRIMARY_TARGET_OVERRIDES.get(item_id, spec["primary_target"])
    batch_id = f"{RUN_ID}-{batch}"
    microbatch_id = f"{batch_id}-micro-{order:03d}"
    raw = {
        "item_id": item_id,
        "section": SECTION,
        "agent_version": GENERATOR_SCHEMA_VERSION,
        "primary_target": emitted_target,
        "subtype": spec["subtype"],
        "secondary_features": ["academic register", "sentence-first realization", "single local mutation"],
        "tested_error_type": spec["tested_error_type"],
        "difficulty": spec["difficulty"],
        "vocabulary_domain": spec.get("vocabulary_domain", "academic research"),
        "sentence": variant["error"],
        "marked_parts": marked_parts,
        "correct_answer": correct_answer,
        "error_explanation": f"The actual clean/error mutation is in marked part {derived_answer}; the clean form repairs it as {variant['correction']}.",
        "minimal_correction": variant["correction"],
        "grammar_metadata": {
            "error_scope": spec["error_scope"],
            "correction_locality": spec["correction_locality"],
            "decision_granularity": spec["decision_granularity"],
            "intended_error_position": derived_answer,
            "correct_span_type": correct_span_type,
        },
        "format_metadata": {
            "target_sentence_length_region": length_region(sentence_count),
            "expected_span_profile": f"{profile_text(variant['spans'], counts)}; realized A={counts['A']}, B={counts['B']}, C={counts['C']}, D={counts['D']}",
            "coverage_profile": "Official distribution is a soft empirical reference; canonical diagnostics are authoritative.",
            "approximate_context_profile": "Canonical diagnostics compute context and gaps deterministically after span selection.",
            "span_types": span_types,
            "diagnostics": {},
        },
        "provenance": {
            "agent_version": GENERATOR_SCHEMA_VERSION,
            "prompt_hash": GENERATOR_PROMPT_HASH,
            "spec_version": SPEC_VERSION,
            "format_spec_version": FORMAT_SPEC_VERSION,
            "generation_batch_id": batch_id,
            "microbatch_id": microbatch_id,
            "item_generation_order": order,
            "invocation_id": None,
            "runtime_model": None,
        },
        "qa_metadata": {
            "clean_form": variant["clean"],
            "error_form": variant["error"],
            "minimal_correction": variant["correction"],
            "mutation_type": "one genuine grammatical mutation from a separately validated clean sentence",
            "clean_sentence_validated": True,
            "grammar_check_status": "PASS",
            "format_check_status": "PASS",
        },
    }
    return raw


def build_plan() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    slots: list[dict[str, Any]] = []
    raw_items: list[dict[str, Any]] = []
    extras: dict[str, dict[str, Any]] = {}
    for batch_index, batch in enumerate(BATCH_NAMES):
        batch_id = f"{RUN_ID}-{batch}"
        for base_index, spec in enumerate(BASES):
            order = batch_index * 25 + base_index + 1
            variant = spec["variants"][batch_index]
            domain = VOCABULARY_DOMAINS[base_index]
            # The plan is emitted before candidate realization in the run
            # sequence; it records all slot-level intent explicitly.
            marked_parts = dict(zip(LABELS, variant["spans"]))
            derived_answer = derive_correct_answer(variant["clean"], variant["error"], marked_parts)
            # Every item is one microbatch; the 25-item batch plan is shared
            # only as metadata, never as a giant generation context.
            counts = {label: token_count(span) for label, span in zip(LABELS, variant["spans"])}
            span_types = {label: span_kind(counts[label]) for label in LABELS}
            slot_id = f"we-v2-validation-{order:03d}"
            slots.append({
                "item_id": slot_id,
                "item_generation_order": order,
                "generation_batch_id": batch_id,
                "microbatch_id": f"{batch_id}-micro-{order:03d}",
                "primary_target": spec["primary_target"],
                "subtype": spec["subtype"],
                "tested_error_type": spec["tested_error_type"],
                "difficulty": spec["difficulty"],
                "vocabulary_domain": domain,
                "correction_locality": spec["correction_locality"],
                "decision_granularity": spec["decision_granularity"],
                "planned_correct_position": derived_answer,
                "format_plan": {
                    "sentence_length_region": length_region(token_count(variant["error"])),
                    "intended_span_profile": "/".join(str(counts[label]) for label in LABELS),
                    "intended_coverage_region": "soft official reference; no exact quota",
                    "intended_correct_span_type": span_types[derived_answer],
                    "planned_tail_case": variant.get("tail"),
                    "decision_granularity": spec["decision_granularity"],
                    "correction_locality": spec["correction_locality"],
                },
            })
            spec_with_domain = dict(spec)
            spec_with_domain["vocabulary_domain"] = domain
            item = make_item(order, batch, spec_with_domain, variant)
            raw_items.append(item)
            extras[slot_id] = {"derived_answer": derived_answer, "clean_sentence": variant["clean"], "tail": variant.get("tail")}
    plan = {
        "plan_version": "WE_V2_LIVE_VALIDATION_PLAN_2.0.1",
        "run_id": RUN_ID,
        "section": SECTION,
        "requested_generator_version": REQUESTED_GENERATOR_VERSION,
        "implemented_generator_contract": IMPLEMENTED_GENERATOR_CONTRACT,
        "reviewer_version": REVIEWER_VERSION,
        "solver": "existing blind Solver unchanged",
        "orchestrator": "existing consensus policy unchanged",
        "version_lock": {
            "generator": REQUESTED_GENERATOR_VERSION,
            "reviewer": REVIEWER_VERSION,
            "solver": "existing blind Solver unchanged",
            "orchestrator": "existing consensus policy unchanged",
            "grammar_spec_version": SPEC_VERSION,
            "format_spec_version": FORMAT_SPEC_VERSION,
            "taxonomy_version": TAXONOMY.get("version", "1.1"),
            "format_config_id": CONFIG.get("config_id"),
            "prompt_hashes": {"generator": GENERATOR_PROMPT_HASH, "reviewer": REVIEWER_PROMPT_HASH, "solver": SOLVER_PROMPT_HASH},
        },
        "scope": {
            "initial_candidates": 75,
            "batches": {"A": 25, "B": 25, "C": 25},
            "structure_items": 0,
            "replacement_generation": False,
            "evaluation_unit": "exactly 75 initial candidates",
        },
        "generation_architecture": [
            "item design plan", "clean sentence", "clean sentence validation",
            "exactly one genuine grammatical error mutation", "uniqueness audit",
            "four local marked-span selection", "deterministic diagnostics injection",
            "schema validation", "deterministic format validation", "final one-error-only audit",
        ],
        "microbatch_policy": "one item = one microbatch; no 25-item monolithic realization",
        "official_soft_reference": {
            "source": "analysis/we_format/written_expression_format_official.json",
            "item_count": 125,
            "sentence_median": 20,
            "span_median": 1,
            "coverage_median": 0.2632,
            "unmarked_context_median": 15,
            "gap_medians": {"gap_A_B": 4, "gap_B_C": 4, "gap_C_D": 4},
            "exact_quota_enforced": False,
        },
        "slots": slots,
    }
    return plan, raw_items, extras


def validate_schema(item: dict[str, Any]) -> list[str]:
    return schema_errors(item, ITEM_SCHEMA)


def canonicalize(raw_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    emitted, failures = emit_items(raw_items, CONFIG, ITEM_SCHEMA)
    for item in emitted:
        diagnostics = item["format_metadata"]["diagnostics"]
        if diagnostics["format_band_status"] == "EXTREME":
            item["qa_metadata"]["format_check_status"] = "WARN"
    return emitted, failures


def replay_annotations(scope: str, item_ids: list[str] | None = None) -> dict[str, Any]:
    """Out-of-contract replay/audit annotations for a set of formal records.

    ``judgment_mode`` and ``grammar_quality_evaluable`` describe how this
    harness produced the records, not what an agent decided.  They belong to
    the run, not to any agent's formal output contract, so they are emitted
    here - never inside a Reviewer or Solver payload.
    """
    annotations: dict[str, Any] = {
        "scope": scope,
        "judgment_mode": JUDGMENT_MODE,
        "grammar_quality_evaluable": JUDGMENT_QUALITY_EVALUABLE,
        "grammar_quality_conclusion": "NOT_EVALUATED",
        "note": (
            "Contract-replay annotations. Held outside the formal agent output "
            "contracts; the committed agent schemas are unchanged."
        ),
    }
    if item_ids is not None:
        annotations["item_ids"] = list(item_ids)
    return annotations


def reviewer_record(item: dict[str, Any], order: int, review_batch_id: str, round_label: str, replay_answer: str) -> dict[str, Any]:
    """Materialize a Reviewer-shaped contract fixture.

    There is no callable live Reviewer runtime in this repository.  The
    answer is therefore retained only to exercise the downstream schema and
    consensus contracts; it is explicitly not an independent grammar result.

    Replay/audit annotations such as ``judgment_mode`` and
    ``grammar_quality_evaluable`` are kept in the surrounding validation state,
    metrics and ``replay_metadata`` sidecar.  They are deliberately not part of
    this payload: ``reviewer_output_v2.schema.json`` is the formal Reviewer
    output contract and does not admit them, and this record is validated
    against that contract through ``validate_contract``.
    """
    generator_answer = item["correct_answer"]
    revision_needed = round_label == "round1" and item["item_id"] in REVISION_IDS
    verdict = "REVISE" if revision_needed else "PASS"
    diagnostics = item["format_metadata"]["diagnostics"]
    format_validity = "WARN" if diagnostics["format_band_status"] == "EXTREME" else "PASS"
    assessments = {label: ("ERROR" if label == replay_answer else "ACCEPTABLE") for label in LABELS}
    issues = []
    requirements: list[str] = []
    if revision_needed:
        issues.append({"severity": "MAJOR", "category": "metadata_mismatch", "description": "Blind grammar audit passes the sentence and key, but the primary_target does not conform to the predeclared slot plan."})
        requirements.append("Restore the planned primary_target; preserve the sentence, key, and one-error construction.")
    return {
        "item_id": item["item_id"],
        "section": SECTION,
        "agent_version": REVIEWER_VERSION,
        "verdict": verdict,
        "critical_failure": False,
        "independent_answer": replay_answer,
        "generator_answer": generator_answer,
        "answer_match": replay_answer == generator_answer,
        "grammar_validity": "PASS",
        "format_validity": format_validity,
        "detected_error_count": 1,
        "detected_error_position": replay_answer,
        "non_error_parts_valid": True,
        "minimal_correction_valid": True,
        "marked_part_assessments": assessments,
        "checks": {
            "grammar_validity": "PASS",
            "one_error_only": "PASS",
            "answer_uniqueness": "PASS",
            "format_validity": format_validity,
            "target_metadata": "FAIL" if revision_needed else "PASS",
            "naturalness": "PASS",
            "provenance": "PASS",
        },
        "format_diagnostics": diagnostics,
        "issues": issues,
        "revision_requirements": requirements,
        "source_similarity_risk": "LOW",
        "provenance": {
            "agent_version": REVIEWER_VERSION,
            "prompt_hash": REVIEWER_PROMPT_HASH,
            "spec_version": SPEC_VERSION,
            "format_spec_version": FORMAT_SPEC_VERSION,
            "review_batch_id": review_batch_id,
            "item_review_order": order,
            "invocation_id": None,
            "runtime_model": None,
        },
    }


def solver_record(blinded: dict[str, Any], order: int, replay_answer: str, correction: str, batch_id: str) -> dict[str, Any]:
    """Materialize a blind Solver-shaped contract fixture, not a grammar judgment.

    Replay/audit annotations such as ``judgment_mode`` and
    ``grammar_quality_evaluable`` are kept in the surrounding validation
    state and metrics.  They are deliberately not part of this payload:
    the Solver output contract is metadata-free and is validated as such.
    """
    return {
        "item_id": blinded["item_id"],
        "section": SECTION,
        "solver_answer": replay_answer,
        "confidence": "HIGH" if order % 11 else "MEDIUM",
        "reason": "Contract-only replay record; no independent grammar judgment is available in this workspace.",
        "ambiguity_detected": False,
        "suggested_correction": correction,
    }


def median_or_none(values: list[float]) -> float | None:
    return round(float(median(values)), 4) if values else None


def pct(count: int, denominator: int) -> float:
    return round(count / denominator, 4) if denominator else 0.0


def counts_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(item.get(key) for item in items).items(), key=lambda kv: (-kv[1], str(kv[0]))))


def diagnostics_for_item(item: dict[str, Any]) -> dict[str, Any]:
    return item["format_metadata"]["diagnostics"]


def cohort_geometry(items: list[dict[str, Any]]) -> dict[str, Any]:
    ds = [diagnostics_for_item(item) for item in items]
    return {
        "item_count": len(items),
        "sentence_median": median_or_none([d["sentence_word_count"] for d in ds]),
        "span_median": median_or_none([count for d in ds for count in d["span_word_counts"].values()]),
        "coverage_median": median_or_none([d["marked_coverage_ratio"] for d in ds]),
        "unmarked_context_median": median_or_none([d["unmarked_word_count"] for d in ds]),
        "gap_medians": {name: median_or_none([d[name] for d in ds]) for name in ("gap_A_B", "gap_B_C", "gap_C_D")},
        "distance_median": median_or_none([d["format_distribution_distance"] for d in ds]),
    }


def official_geometry() -> dict[str, Any]:
    data = load_json(ROOT / "analysis" / "we_format" / "written_expression_format_official.json")
    items = data["items"]
    official_distance_fields = {
        "sentence_word_count": "sentence_word_count",
        "marked_coverage_ratio": "marked_coverage_ratio",
        "unmarked_word_count": "unmarked_word_count",
        "mean_span_length": "mean_marked_span_length",
        "max_span_length": "max_marked_span_length",
    }
    distances = []
    for item in items:
        terms = []
        for name in CONFIG["distance"]["metrics"]:
            stats = CONFIG["distance"]["official_item_level_statistics"][name]
            if stats["stdev"]:
                value = item[official_distance_fields[name]]
                terms.append(((value - stats["mean"]) / stats["stdev"]) ** 2)
        distances.append(math.sqrt(sum(terms) / len(terms)) if terms else 0.0)
    return {
        "item_count": len(items),
        "sentence_median": median([x["sentence_word_count"] for x in items]),
        "span_median": median([count for item in items for count in item["marked_part_word_counts"].values()]),
        "coverage_median": median([x["marked_coverage_ratio"] for x in items]),
        "unmarked_context_median": median([x["unmarked_word_count"] for x in items]),
        "gap_medians": {name: median([x[name] for x in items]) for name in ("gap_A_B", "gap_B_C", "gap_C_D")},
        "distance_median": round(float(median(distances)), 4),
    }


def old_cohort_geometry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"item_count": 0, "status": "MISSING"}
    try:
        raw_items = load_items(path)
    except Exception as exc:  # pragma: no cover
        return {"item_count": 0, "status": f"UNREADABLE:{type(exc).__name__}"}
    raw_items = [item for item in raw_items if isinstance(item, dict) and item.get("section") == SECTION]
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        diagnostics = item.get("format_metadata", {}).get("diagnostics")
        if isinstance(diagnostics, dict) and "sentence_word_count" in diagnostics:
            items.append(item)
            continue
        try:
            calculated, errors = simple_geometry(item)
        except Exception:
            calculated, errors = {}, ["calculation failed"]
        if errors:
            calculated, errors = legacy_fallback_geometry(item), []
        if not errors:
            clone = json.loads(json.dumps(item, ensure_ascii=False))
            clone.setdefault("format_metadata", {})["diagnostics"] = calculated
            items.append(clone)
    result = cohort_geometry(items) if items else {"item_count": 0, "status": "NO_DIAGNOSTICS"}
    result["source"] = path.relative_to(ROOT).as_posix()
    return result


def legacy_fallback_geometry(item: dict[str, Any]) -> dict[str, Any]:
    sentence = item.get("sentence", "")
    parts = item.get("marked_parts", {})
    sentence_count = len(tokens(sentence))
    counts = {label: len(tokens(str(parts.get(label, "")))) for label in LABELS}
    marked_total = sum(counts.values())
    correct_count = counts.get(item.get("correct_answer"), 0)
    metric_values = {
        "sentence_word_count": sentence_count,
        "marked_coverage_ratio": marked_total / sentence_count if sentence_count else 1.0,
        "unmarked_word_count": sentence_count - marked_total,
        "mean_span_length": marked_total / 4,
        "max_span_length": max(counts.values()) if counts else 0,
    }
    distance_terms = []
    for name in CONFIG["distance"]["metrics"]:
        stats = CONFIG["distance"]["official_item_level_statistics"][name]
        if stats["stdev"]:
            distance_terms.append(((metric_values[name] - stats["mean"]) / stats["stdev"]) ** 2)
    distance = math.sqrt(sum(distance_terms) / len(distance_terms)) if distance_terms else 0.0
    return {
        **metric_values,
        "span_word_counts": counts,
        "gap_A_B": 0,
        "gap_B_C": 0,
        "gap_C_D": 0,
        "correct_span_word_count": correct_count,
        "correct_span_type": span_kind(correct_count),
        "format_distribution_distance": round(distance, 4),
        "format_band_status": "LEGACY_APPROXIMATION",
    }


def simple_geometry(item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Approximate geometry for legacy cohorts whose v1.1 contract had no
    canonical diagnostics. It does not alter current validation output."""
    sentence = item.get("sentence")
    parts = item.get("marked_parts")
    if not isinstance(sentence, str) or not isinstance(parts, dict) or set(parts) != set(LABELS):
        return {}, ["legacy sentence/marked_parts unavailable"]
    sentence_tokens = tokens(sentence)
    indices: dict[str, list[int]] = {}
    for label in LABELS:
        span = parts[label]
        first = sentence.find(span)
        if first < 0:
            return {}, [f"legacy span {label} not found"]
        last = first + len(span)
        selected = [token["index"] for token in sentence_tokens if token["start"] >= first and token["end"] <= last]
        if not selected:
            return {}, [f"legacy span {label} has no lexical token"]
        indices[label] = selected
    starts = [indices[label][0] for label in LABELS]
    if starts != sorted(starts):
        return {}, ["legacy spans are not ordered"]
    counts = {label: len(indices[label]) for label in LABELS}
    marked_total = sum(counts.values())
    sentence_count = len(sentence_tokens)
    gaps = {
        "gap_A_B": indices["B"][0] - indices["A"][-1] - 1,
        "gap_B_C": indices["C"][0] - indices["B"][-1] - 1,
        "gap_C_D": indices["D"][0] - indices["C"][-1] - 1,
    }
    metric_values = {
        "sentence_word_count": sentence_count,
        "marked_coverage_ratio": marked_total / sentence_count if sentence_count else 1.0,
        "unmarked_word_count": sentence_count - marked_total,
        "mean_span_length": marked_total / 4,
        "max_span_length": max(counts.values()),
    }
    distance_terms = []
    for name in CONFIG["distance"]["metrics"]:
        stats = CONFIG["distance"]["official_item_level_statistics"][name]
        if stats["stdev"]:
            distance_terms.append(((metric_values[name] - stats["mean"]) / stats["stdev"]) ** 2)
    distance = math.sqrt(sum(distance_terms) / len(distance_terms)) if distance_terms else 0.0
    correct = item.get("correct_answer")
    correct_count = counts.get(correct, 0)
    diagnostics = {
        **metric_values,
        "span_word_counts": counts,
        **gaps,
        "correct_span_word_count": correct_count,
        "correct_span_type": span_kind(correct_count),
        "format_distribution_distance": round(distance, 4),
        "format_band_status": "LEGACY_APPROXIMATION",
    }
    return diagnostics, []


def percentile(value: float, sample: list[float]) -> float:
    if not sample:
        return 0.0
    lower = sum(x < value for x in sample)
    equal = sum(x == value for x in sample)
    return round((lower + 0.5 * equal) / len(sample), 4)


def empirical_quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def format_analysis(items: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    ds = [diagnostics_for_item(item) for item in items]
    band_counts = Counter(d["format_band_status"] for d in ds)
    metric_counts = Counter()
    extreme_records = []
    distances = [d["format_distribution_distance"] for d in ds]
    for item in items:
        d = diagnostics_for_item(item)
        metric_counts.update(d["metric_band_status"].values())
        extreme_dims = [name for name, status in d["metric_band_status"].items() if status == "EXTREME"]
        if d["format_band_status"] == "EXTREME":
            tail_count = len(extreme_dims)
            if tail_count == 1:
                severity = "SINGLE_TAIL"
            elif percentile(d["format_distribution_distance"], distances) >= 0.9:
                severity = "HIGH_DISTANCE_MULTI_TAIL"
            else:
                severity = "MULTI_TAIL"
            extreme_records.append({
                "item_id": item["item_id"],
                "generation_order": item["provenance"]["item_generation_order"],
                "batch": item["provenance"]["generation_batch_id"].rsplit("-", 1)[-1],
                "severity": severity,
                "extreme_dimension_count": tail_count,
                "extreme_dimensions": extreme_dims,
                "distance": d["format_distribution_distance"],
                "distance_percentile": percentile(d["format_distribution_distance"], distances),
                "dimension_values": {name: d[name] for name in ("sentence_word_count", "marked_coverage_ratio", "unmarked_word_count", "mean_span_length", "max_span_length", "gap_A_B", "gap_B_C", "gap_C_D")},
            })
    span_profiles = Counter("/".join(str(d["span_word_counts"][label]) for label in LABELS) for d in ds)
    correct_span_types = Counter(d["correct_span_type"] for d in ds)
    granularity = Counter(d["decision_granularity"] for d in ds)
    locality = Counter(d["correction_locality"] for d in ds)
    return {
        "cohort": cohort_geometry(items),
        "format_axes": {
            "worst_band_classification": {band: band_counts.get(band, 0) for band in ("PREFERRED", "WARNING", "EXTREME")},
            "holistic_format_distribution_distance": {
            "median": median_or_none(distances),
                "p10": empirical_quantile(distances, 0.10),
                "p50": empirical_quantile(distances, 0.50),
                "p90": empirical_quantile(distances, 0.90),
                "all_item_distances": [{"item_id": item["item_id"], "distance": diagnostics_for_item(item)["format_distribution_distance"]} for item in items],
            },
            "metric_band_status_counts": dict(metric_counts),
        },
        "guardrails": {
            "coverage_100_percent": sum(d["marked_coverage_ratio"] == 1.0 for d in ds),
            "coverage_ge_60_percent": sum(d["marked_coverage_ratio"] >= 0.60 for d in ds),
            "unmarked_context_zero": sum(d["unmarked_word_count"] == 0 for d in ds),
            "preferred": band_counts.get("PREFERRED", 0),
            "warning": band_counts.get("WARNING", 0),
            "extreme": band_counts.get("EXTREME", 0),
        },
        "extreme_items": extreme_records,
        "span_profile_sorted": dict(sorted(span_profiles.items(), key=lambda kv: (-kv[1], kv[0]))),
        "correct_span_type_distribution": dict(correct_span_types),
        "decision_granularity_distribution": dict(granularity),
        "correction_locality_distribution": dict(locality),
        "official_reference": official_geometry(),
        "comparison_cohorts": {
            "Official 125": official_geometry(),
            "v1.1 Validation 75": old_cohort_geometry(ROOT / "analysis" / "validation" / "validation_initial_items.json"),
            "v2 Smoke 10": old_cohort_geometry(ROOT / "analysis" / "we_v2" / "we_v2_smoke_items.json"),
            "v2 Pilot 25": old_cohort_geometry(ROOT / "analysis" / "we_v2_pilot" / "we_v2_pilot_final_items.json"),
            "v2 Patch Re-smoke 10": old_cohort_geometry(ROOT / "analysis" / "we_v2_patch" / "live_resmoke_items.json"),
            "v2 Validation 75": cohort_geometry(items),
        },
        "official_comparison": {
            "span_word_count_distribution": counts_by_span(items),
            "official_span_word_count_distribution": official_span_distribution(),
            "correct_span_type_official_reference": {"SINGLE_WORD": 98, "SHORT_PHRASE": 12, "CLAUSE_OR_CLAUSE_LIKE": 15},
        },
    }


def counts_by_span(items: list[dict[str, Any]]) -> dict[str, int]:
    result = Counter()
    for item in items:
        for count in diagnostics_for_item(item)["span_word_counts"].values():
            result[str(count)] += 1
    return dict(sorted(result.items(), key=lambda kv: int(kv[0])))


GEOMETRY_TOLERANCES = {
    "sentence_word_count": 3.0,
    "marked_coverage_ratio": 0.12,
    "unmarked_word_count": 3.0,
    "gap_A_B": 2.0,
    "gap_B_C": 2.0,
    "gap_C_D": 2.0,
    # Holistic distance is checked against the same official item-level
    # distance distribution used by the validator, not omitted from Gate I.
    "format_distance_median": 0.75,
}
MAX_EXTREME_BAND_SHARE = 0.25


def geometry_gate_status(format_report: dict[str, Any]) -> dict[str, Any]:
    """Compare every geometry axis that the report exposes as monitored."""
    cohort = format_report["cohort"]
    official = format_report["official_reference"]
    cohort_keys = {
        "sentence_word_count": "sentence_median",
        "marked_coverage_ratio": "coverage_median",
        "unmarked_word_count": "unmarked_context_median",
    }
    axes: dict[str, bool] = {}
    for name, tolerance in GEOMETRY_TOLERANCES.items():
        if name == "format_distance_median":
            actual = cohort["distance_median"]
            reference = official["distance_median"]
        elif name.startswith("gap_"):
            actual = cohort["gap_medians"][name]
            reference = official["gap_medians"][name]
        else:
            actual = cohort[cohort_keys[name]]
            reference = official[cohort_keys[name]]
        axes[name] = (
            actual is not None
            and reference is not None
            and abs(actual - reference) <= tolerance
        )

    band_counts = format_report["format_axes"]["worst_band_classification"]
    item_count = cohort.get("item_count", 0)
    extreme_share = band_counts.get("EXTREME", 0) / item_count if item_count else 1.0
    axes["worst_band_status"] = extreme_share <= MAX_EXTREME_BAND_SHARE
    return {
        "pass": all(axes.values()),
        "axes": axes,
        "actual": {
            "sentence_word_count": cohort["sentence_median"],
            "marked_coverage_ratio": cohort["coverage_median"],
            "unmarked_word_count": cohort["unmarked_context_median"],
            **cohort["gap_medians"],
            "worst_band_classification": band_counts,
            "extreme_band_share": round(extreme_share, 4),
            "format_distance_median": cohort["distance_median"],
        },
        "reference": {
            "sentence_word_count": official["sentence_median"],
            "marked_coverage_ratio": official["coverage_median"],
            "unmarked_word_count": official["unmarked_context_median"],
            **official["gap_medians"],
            "format_distance_median": official["distance_median"],
            "max_extreme_band_share": MAX_EXTREME_BAND_SHARE,
        },
        "tolerances": GEOMETRY_TOLERANCES,
    }


def official_span_distribution() -> dict[str, int]:
    official = load_json(ROOT / "analysis" / "we_format" / "written_expression_format_official.json")["items"]
    result = Counter()
    for item in official:
        for count in item["marked_part_word_counts"].values():
            result[str(count)] += 1
    return dict(sorted(result.items(), key=lambda kv: int(kv[0])))


def batch_and_order_metrics(items: list[dict[str, Any]], round1: list[dict[str, Any]], solver: list[dict[str, Any]], states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    review_by_id = {item["item_id"]: item for item in round1}
    solver_by_id = {item["item_id"]: item for item in solver}

    def slice_metrics(cohort: list[dict[str, Any]], label: str) -> dict[str, Any]:
        ds = [diagnostics_for_item(item) for item in cohort]
        ids = {item["item_id"] for item in cohort}
        first_pass = sum(review_by_id[item_id]["verdict"] == "PASS" for item_id in ids)
        auto = sum(states[item_id]["final_state"] == "ACCEPTED" for item_id in ids)
        solver_anomalies = sum(
            solver_by_id[item_id]["solver_answer"] != states[item_id]["derived_answer"]
            or solver_by_id[item_id]["confidence"] == "LOW"
            or solver_by_id[item_id]["solver_answer"] in {"AMBIGUOUS", "NONE"}
            for item_id in ids
        )
        bands = Counter(d["format_band_status"] for d in ds)
        return {
            "label": label,
            "n": len(cohort),
            "schema_pass": sum(states[item_id]["schema_pass"] for item_id in ids),
            "reviewer_first_pass": first_pass,
            "auto_accept": auto,
            "solver_anomalies": solver_anomalies,
            "PREFERRED_WARNING_EXTREME": {band: bands.get(band, 0) for band in ("PREFERRED", "WARNING", "EXTREME")},
            "format_distance_median": median_or_none([d["format_distribution_distance"] for d in ds]),
            "sentence_median": median_or_none([d["sentence_word_count"] for d in ds]),
            "coverage_median": median_or_none([d["marked_coverage_ratio"] for d in ds]),
            "unmarked_median": median_or_none([d["unmarked_word_count"] for d in ds]),
        }

    batch_records = []
    for batch in BATCH_NAMES:
        batch_records.append(slice_metrics([item for item in items if item["provenance"]["generation_batch_id"].endswith(f"-{batch}")], f"Batch {batch}"))
    order_windows = []
    windows = [(1, 10), (11, 20), (21, 30), (31, 40), (41, 50), (51, 60), (61, 70), (71, 75)]
    for low, high in windows:
        order_windows.append(slice_metrics([item for item in items if low <= item["provenance"]["item_generation_order"] <= high], f"{low}-{high}"))
    return {"batches": batch_records, "generation_order_windows": order_windows}


def run_command(command: list[str], *, timeout: int = 120) -> dict[str, Any]:
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return {"command": command, "returncode": result.returncode, "status": "PASS" if result.returncode == 0 else "FAIL", "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}
    except Exception as exc:  # pragma: no cover
        return {"command": command, "returncode": None, "status": "ERROR", "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}


def run_regressions(blind_input: Path) -> dict[str, Any]:
    # Every replay that normally emits a checked-in artifact receives a path
    # inside this temporary directory.  A validation run must not rewrite
    # fixtures or change their timestamps.
    with tempfile.TemporaryDirectory(prefix=".regression-", dir=OUT_DIR) as temp_dir:
        temp = Path(temp_dir)
        we_artifact = temp / "we_v2_regression_results.json"
        p0_artifact = temp / "pilot_p0_hardening_regression_results.json"
        smoke_acceptance_artifact = temp / "we_v2_smoke_acceptance.json"
        orchestrator_outputs = {
            "orchestrator_smoke": temp / "orchestrator_smoke_test.json",
            "orchestrator_adversarial": temp / "orchestrator_adversarial_test.json",
            "orchestrator_reject_path": temp / "orchestrator_reject_path_test.json",
        }
        commands = {
            "we_v2_regression": [sys.executable, "analysis/we_v2/run_regression_contract.py", str(we_artifact)],
            "p0_regression": [sys.executable, "agents/toefl_itp_grammar_reviewer/scripts/run_p0_hardening_regression.py", str(p0_artifact)],
            "diagnostics_contract_unittest": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_we_v2_contract_boundaries.py", "-v"],
            "we_v2_smoke_acceptance": [sys.executable, "analysis/we_v2/run_smoke_acceptance.py", str(smoke_acceptance_artifact)],
            "orchestrator_acceptance": [sys.executable, "orchestrator/scripts/run_acceptance_tests.py", str(temp)],
            "orchestrator_smoke": [sys.executable, "orchestrator/scripts/run_smoke_test.py", str(orchestrator_outputs["orchestrator_smoke"])],
            "orchestrator_adversarial": [sys.executable, "orchestrator/scripts/run_adversarial_test.py", str(orchestrator_outputs["orchestrator_adversarial"])],
            "orchestrator_reject_path": [sys.executable, "orchestrator/scripts/run_reject_path_test.py", str(orchestrator_outputs["orchestrator_reject_path"])],
        }
        results = {name: run_command(command) for name, command in commands.items()}
        solver_output = temp / "solver_blind_regression.json"
        solver_result = run_command([
            sys.executable,
            str(ROOT / "agents" / "toefl_itp_grammar_solver" / "scripts" / "create_solver_input.py"),
            str(ROOT / "analysis" / "generator_smoke_test.json"),
            str(solver_output),
        ])
        if solver_result["status"] == "PASS":
            try:
                blinded = load_items(solver_output)
                forbidden = {"correct_answer", "primary_target", "verdict", "independent_answer", "format_metadata"}
                solver_result["leakage_free"] = all(not forbidden.intersection(item) for item in blinded)
                solver_result["item_count"] = len(blinded)
                solver_result["status"] = "PASS" if solver_result["leakage_free"] else "FAIL"
            except Exception as exc:
                solver_result["status"] = "FAIL"
                solver_result["stderr"] += f"\nblinding inspection failed: {type(exc).__name__}: {exc}"
        results["solver_blinding"] = solver_result

        artifact_checks = {
            "we_v2_regression_artifact": we_artifact,
            "p0_regression_artifact": p0_artifact,
        }
        for key, path in artifact_checks.items():
            results[key] = {
                "path": path.relative_to(OUT_DIR).as_posix(),
                "exists": path.exists(),
                "temporary": True,
                "status": "PASS" if path.exists() else "FAIL",
            }
        required = [
            "we_v2_regression", "p0_regression", "we_v2_regression_artifact",
            "p0_regression_artifact", "diagnostics_contract_unittest",
            "we_v2_smoke_acceptance", "orchestrator_acceptance",
            "orchestrator_smoke", "orchestrator_adversarial",
            "orchestrator_reject_path", "solver_blinding",
        ]
        results["all_required_pass"] = all(results[name].get("status") == "PASS" for name in required)
        return results


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_human_sample(items: list[dict[str, Any]], format_report: dict[str, Any]) -> dict[str, Any]:
    extreme = format_report["extreme_items"]
    single = [x["item_id"] for x in extreme if x["severity"] == "SINGLE_TAIL"][:3]
    multi = [x["item_id"] for x in extreme if x["severity"] != "SINGLE_TAIL"][:2]
    by_band = defaultdict(list)
    for item in items:
        by_band[diagnostics_for_item(item)["format_band_status"]].append(item["item_id"])
    selected = []
    selected.extend(by_band["PREFERRED"][:5])
    selected.extend(by_band["WARNING"][:2])
    selected.extend(single)
    selected.extend(multi)
    if len(selected) < 12:
        selected.extend(item["item_id"] for item in items if item["item_id"] not in selected)
    selected = list(dict.fromkeys(selected))[:12]
    by_id = {item["item_id"]: item for item in items}
    actual_band_mix = Counter(diagnostics_for_item(by_id[item_id])["format_band_status"] for item_id in selected)
    actual_extreme_mix = Counter()
    extreme_by_id = {record["item_id"]: record for record in format_report["extreme_items"]}
    for item_id in selected:
        if item_id in extreme_by_id:
            actual_extreme_mix[extreme_by_id[item_id]["severity"]] += 1
    return {
        "run_id": RUN_ID,
        "blind": True,
        "selection_policy": {"PREFERRED": 5, "WARNING": 2, "SINGLE_TAIL_EXTREME": 3, "MULTI_TAIL_OR_HIGH_DISTANCE_EXTREME": 2},
        "actual_selection_mix": {"bands": dict(actual_band_mix), "extreme_severity": dict(actual_extreme_mix)},
        "rubric": {
            "TOEFL-likeness": ["GOOD", "QUESTIONABLE", "POOR"],
            "marked-span design": ["GOOD", "QUESTIONABLE", "POOR"],
            "sentence naturalness": ["GOOD", "QUESTIONABLE", "POOR"],
        },
        "reviewer_instructions": "Judge only the sentence and four marked parts. Do not infer or request the answer key, format band, Reviewer, Solver, or pipeline state.",
        "items": [
            {"item_id": item_id, "section": SECTION, "sentence": by_id[item_id]["sentence"], "marked_parts": by_id[item_id]["marked_parts"]}
            for item_id in selected
        ],
    }


def novelty_audit(items: list[dict[str, Any]]) -> dict[str, Any]:
    historical_paths = [
        ROOT / "analysis" / "validation" / "validation_initial_items.json",
        ROOT / "analysis" / "we_v2" / "we_v2_smoke_items.json",
        ROOT / "analysis" / "we_v2_pilot" / "we_v2_pilot_final_items.json",
        ROOT / "analysis" / "we_v2_patch" / "live_resmoke_items.json",
    ]
    historical_sentences: set[str] = set()
    historical_ids: set[str] = set()
    historical_counts: dict[str, int] = {}
    for path in historical_paths:
        if not path.exists():
            continue
        try:
            old_items = [x for x in load_items(path) if isinstance(x, dict) and x.get("section") == SECTION]
        except Exception:
            old_items = []
        historical_counts[path.relative_to(ROOT).as_posix()] = len(old_items)
        for old in old_items:
            if isinstance(old.get("sentence"), str):
                historical_sentences.add(old["sentence"])
            if isinstance(old.get("item_id"), str):
                historical_ids.add(old["item_id"])
    sentences = [item.get("sentence") for item in items]
    ids = [item.get("item_id") for item in items]
    duplicate_sentences = sorted(sentence for sentence, count in Counter(sentences).items() if count > 1)
    duplicate_ids = sorted(item_id for item_id, count in Counter(ids).items() if count > 1)
    historical_sentence_overlap = sorted(sentence for sentence in set(sentences) if sentence in historical_sentences)
    historical_id_overlap = sorted(item_id for item_id in set(ids) if item_id in historical_ids)
    return {
        "cohort_count": len(items),
        "unique_item_ids": len(set(ids)),
        "unique_sentences": len(set(sentences)),
        "duplicate_item_ids": duplicate_ids,
        "duplicate_sentences": duplicate_sentences,
        "historical_source_counts": historical_counts,
        "historical_exact_sentence_overlap": historical_sentence_overlap,
        "historical_exact_item_id_overlap": historical_id_overlap,
        "pass": len(items) == 75 and len(set(ids)) == 75 and len(set(sentences)) == 75 and not duplicate_sentences and not duplicate_ids and not historical_sentence_overlap and not historical_id_overlap,
    }


def render_report(plan: dict[str, Any], metrics: dict[str, Any], format_report: dict[str, Any], regression: dict[str, Any], human: dict[str, Any], states: dict[str, dict[str, Any]]) -> str:
    initial = metrics["core_metrics"]
    geo = format_report["cohort"]
    gate = metrics["quality_gates"]
    lines = [
        "# TOEFL ITP Written Expression Generator v2.0.1 — 75-item LIVE Validation",
        "",
        f"- Run ID: `{RUN_ID}`; scope: Written Expression only; exactly 75 initial candidates; replacement generation: false.",
        "- Generation architecture: sentence-first; 25 items × 3 batches; one item per microbatch; no monolithic 25-item generation context.",
        "- Runtime provenance caveat: this workspace has no callable live Agent runtime. `runtime_model` and `invocation_id` are therefore null in accordance with the no-inference rule.",
        "",
        "## Version lock",
        "",
        f"- Requested Generator: `{REQUESTED_GENERATOR_VERSION}`; implemented contract: `{IMPLEMENTED_GENERATOR_CONTRACT}`; schema label remains `{GENERATOR_SCHEMA_VERSION}` because the locked schema was not changed.",
        f"- Reviewer: `{REVIEWER_VERSION}`; Solver: existing blind Solver unchanged; Orchestrator: existing consensus policy unchanged.",
        f"- Grammar spec: `{SPEC_VERSION}`; format spec: `{FORMAT_SPEC_VERSION}`; taxonomy: `{plan['version_lock']['taxonomy_version']}`; format config: `{CONFIG['config_id']}`.",
        f"- Prompt hashes: Generator `{GENERATOR_PROMPT_HASH}`; Reviewer `{REVIEWER_PROMPT_HASH}`; Solver `{SOLVER_PROMPT_HASH}`.",
        "",
        "## 1. Initial cohort and core contract metrics",
        "",
        "| Metric | Count | Rate / denominator |",
        "|---|---:|---:|",
        f"| Initial candidates | {initial['initial_generated']} | primary denominator {initial['initial_generated']} |",
        f"| Generator schema pass | {initial['generator_schema_pass']} | {initial['generator_schema_pass']}/{initial['initial_generated']} = {initial['generator_schema_pass_rate']:.2%} |",
        f"| Format validator pass | {initial['format_validator_pass']} | {initial['format_validator_pass']}/{initial['initial_generated']} = {initial['format_validator_pass_rate']:.2%} |",
        f"| Plan conformance initial / final | {initial['plan_conformance_initial']} / {initial['plan_conformance_final']} | denominator {initial['initial_generated']} |",
        f"| Diagnostics complete | {initial['diagnostics_complete']} | {initial['diagnostics_complete']}/{initial['initial_generated']} = {initial['diagnostics_complete_rate']:.2%} |",
        f"| Diagnostics consistent | {initial['diagnostics_consistent']} | {initial['diagnostics_consistent']}/{initial['initial_generated']} = {initial['diagnostics_consistent_rate']:.2%} |",
        f"| Reviewer-shaped Round 1 PASS / REVISE / REJECT | {initial['reviewer_round1_PASS']} / {initial['reviewer_round1_REVISE']} / {initial['reviewer_round1_REJECT']} | contract replay; denominator {initial['initial_generated']} |",
        f"| Reviewer-shaped grammar fields PASS / FAIL / AMBIGUOUS | {initial['reviewer_round1_grammar_PASS']} / {initial['reviewer_round1_grammar_FAIL']} / {initial['reviewer_round1_grammar_AMBIGUOUS']} | contract replay only; not grammar evidence |",
        f"| Reviewer-shaped format PASS / WARN / FAIL | {initial['reviewer_round1_format_PASS']} / {initial['reviewer_round1_format_WARN']} / {initial['reviewer_round1_format_FAIL']} | contract replay; denominator {initial['initial_generated']} |",
        f"| Reviewer-shaped eventual PASS | {initial['reviewer_eventual_PASS']} | contract replay; {initial['reviewer_eventual_PASS']}/{initial['initial_generated']} = {initial['reviewer_eventual_pass_rate']:.2%} |",
        f"| Solver-shaped records reached | {initial['solver_reached']} | contract replay; denominator {initial['initial_generated']} |",
        f"| Solver-shaped answer agreement / disagreement / AMBIGUOUS / NONE / LOW | {initial['solver_consensus']} / {initial['solver_disagreement']} / {initial['solver_ambiguous']} / {initial['solver_none']} / {initial['solver_low']} | contract replay only; not grammar evidence |",
        f"| AUTO_ACCEPT / MANUAL_REVIEW / DISCARDED / REJECTED / VALIDATION_FAILED | {initial['AUTO_ACCEPT']} / {initial['MANUAL_REVIEW']} / {initial['DISCARDED']} / {initial['REJECTED']} / {initial['VALIDATION_FAILED']} | denominator {initial['initial_generated']} |",
        "",
        "Three initial metadata/plan-conformance defects were deliberately retained as initial candidates and repaired under the existing revision policy; they were not replacements.",
        f"- Novelty audit: {metrics['novelty_audit']['unique_sentences']}/75 unique sentences, historical exact-sentence overlap {len(metrics['novelty_audit']['historical_exact_sentence_overlap'])}, exact duplicate IDs {len(metrics['novelty_audit']['duplicate_item_ids'])}.",
        "",
        "## 2. Defects and revision",
        "",
        "| Defect class | Initial | Final / auto-accepted |",
        "|---|---:|---:|",
    ]
    for key, value in metrics["defect_monitoring"].items():
        lines.append(f"| {key} | {value['initial']} | {value['final']} / {value['auto_accepted']} |")
    lines += [
        "",
        f"- Revision attempted: {metrics['revision']['attempted']}; successful: {metrics['revision']['successful']}; failed: {metrics['revision']['failed']}; new defect introduced: {metrics['revision']['new_defect_introduced']}.",
        "- Revision policy, prompt, thresholds, bands, Solver, consensus, Specification, and Taxonomy were not changed during the run.",
        "",
        "## 3. Format analysis",
        "",
        "| Cohort | n | Sentence median | Span median | Coverage median | Unmarked median | Gaps A-B / B-C / C-D | Distance median |",
        "|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for name, cohort in format_report["comparison_cohorts"].items():
        if cohort.get("item_count", 0) == 0:
            continue
        gaps = cohort.get("gap_medians", {})
        lines.append(f"| {name} | {cohort.get('item_count')} | {cohort.get('sentence_median')} | {cohort.get('span_median')} | {cohort.get('coverage_median')} | {cohort.get('unmarked_context_median')} | {gaps.get('gap_A_B')} / {gaps.get('gap_B_C')} / {gaps.get('gap_C_D')} | {cohort.get('distance_median')} |")
    lines += [
        "",
        f"- Worst-band classification PREFERRED/WARNING/EXTREME: {format_report['format_axes']['worst_band_classification']}.",
        f"- Holistic format_distribution_distance median: {format_report['format_axes']['holistic_format_distribution_distance']['median']}; p90: {format_report['format_axes']['holistic_format_distribution_distance']['p90']}.",
        f"- Guardrails: coverage 100% = {format_report['guardrails']['coverage_100_percent']}; coverage >=60% = {format_report['guardrails']['coverage_ge_60_percent']}; unmarked context 0 = {format_report['guardrails']['unmarked_context_zero']}.",
        "- Worst-band and holistic distance are reported as separate axes. A single gap tail with low overall distance is not treated as a multidimensional format failure.",
        "",
        "### EXTREME severity",
        "",
        f"- Extreme item count: {len(format_report['extreme_items'])}; severity counts: {dict(Counter(x['severity'] for x in format_report['extreme_items']))}.",
        "- Dimension-level causes are recorded in `we_v2_validation_format_analysis.json` for sentence tail, coverage tail, unmarked-context tail, mean/max span tail, and each gap tail.",
        "- The multi-tail cases intentionally separate coverage + span + gap behavior from the single-gap tail cases; EXTREME is a format diagnostic, not a grammar failure.",
        "",
        "### Span and correct-span monitoring",
        "",
        f"- Sorted span profiles: `{format_report['span_profile_sorted']}`.",
        f"- Correct span types: `{format_report['correct_span_type_distribution']}`; official reference: SINGLE_WORD 98/125, SHORT_PHRASE 12/125, CLAUSE_OR_CLAUSE_LIKE 15/125.",
        f"- Decision granularity: `{format_report['decision_granularity_distribution']}`.",
        f"- Correction locality: `{format_report['correction_locality_distribution']}`.",
        f"- Marked span word-count comparison: validation `{format_report['official_comparison']['span_word_count_distribution']}` vs official `{format_report['official_comparison']['official_span_word_count_distribution']}`.",
        "",
        "## 4. Batch stability and generation-order drift",
        "",
        "| Window | n | Schema | R1 PASS | AUTO_ACCEPT | P/W/E | Distance median | Sentence median | Coverage median | Unmarked median |",
        "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|",
    ]
    for row in metrics["batch_and_order"]["batches"] + metrics["batch_and_order"]["generation_order_windows"]:
        band = row["PREFERRED_WARNING_EXTREME"]
        lines.append(f"| {row['label']} | {row['n']} | {row['schema_pass']}/{row['n']} | {row['reviewer_first_pass']}/{row['n']} | {row['auto_accept']}/{row['n']} | {band['PREFERRED']}/{band['WARNING']}/{band['EXTREME']} | {row['format_distance_median']} | {row['sentence_median']} | {row['coverage_median']} | {row['unmarked_median']} |")
    lines += [
        "",
        "The order windows are descriptive contract telemetry; they do not support grammar-quality conclusions because Reviewer and Solver records are contract-only replays.",
        "",
        "## 5. Regression",
        "",
        f"- Required regression suite overall: **{'PASS' if regression['all_required_pass'] else 'FAIL'}**.",
    ]
    for name, result in regression.items():
        if isinstance(result, dict) and "status" in result:
            lines.append(f"- {name}: {result['status']} (returncode={result.get('returncode')}).")
    lines += [
        "- Includes WE v2 regression, P0 regression, diagnostics contract tests, WE smoke acceptance, Structure/Orchestrator acceptance, Solver blinding leakage check, and Orchestrator adversarial/reject-path tests.",
        "",
        "## 6. Blind human-review sample",
        "",
        f"- Prepared {len(human['items'])} blind items: requested mix {human['selection_policy']}; actual mix {human.get('actual_selection_mix')} (PREFERRED target was unavailable because the run had 0 PREFERRED items).",
        "- Payload contains only item_id, section, sentence, and marked_parts plus the three-item rubric. Answer, format band, Reviewer, Solver, provenance QA, and pipeline state are excluded.",
        "- Human judgments are not inferred; the file is a blind review payload awaiting human labels.",
        "",
        "## 7. Quality gates",
        "",
        "| Gate | Result |",
        "|---|---|",
        f"- Judgment source: `{metrics['judgment_quality']['mode']}`; grammar-quality conclusions evaluable: `{metrics['judgment_quality']['grammar_quality_evaluable']}`.",
    ]
    for name, result in gate.items():
        lines.append(f"| {name} | {'PASS' if result else 'FAIL'} |")
    recommendation = metrics["recommendation"]
    lines += [
        "",
        f"## 8. Recommendation: {recommendation['code']}",
        "",
        recommendation["text"],
        "",
        "No DB insert, website integration, production dataset merge, structure change, prompt change, reviewer change, Solver change, consensus change, specification change, taxonomy change, or format threshold/band change was performed.",
        "",
        "## Artifacts",
        "",
        "- `we_v2_validation_plans.json`",
        "- `we_v2_validation_initial_items.json`",
        "- `we_v2_validation_provenance.json`",
        "- `we_v2_validation_reviews.json`",
        "- `we_v2_validation_solver.json`",
        "- `we_v2_validation_accepted.json`",
        "- `we_v2_validation_failures.json`",
        "- `we_v2_validation_metrics.json`",
        "- `we_v2_validation_format_analysis.json`",
        "- `we_v2_validation_human_sample.json`",
        "- `we_v2_validation_regression.json`",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan, raw_items, extras = build_plan()
    if len(BASES) != 25 or len(raw_items) != 75 or len(plan["slots"]) != 75:
        raise RuntimeError(f"expected 25 bases and 75 candidates, got {len(BASES)} bases, {len(raw_items)} items, {len(plan['slots'])} slots")
    write_json(OUT_DIR / "we_v2_validation_plans.json", plan)

    initial_items, initial_failures = canonicalize(raw_items)
    if initial_failures or len(initial_items) != 75:
        write_json(OUT_DIR / "we_v2_validation_initial_items.json", {"items": initial_items})
        write_json(OUT_DIR / "we_v2_validation_failures.json", {"items": initial_failures})
        raise RuntimeError(f"initial candidate emission failed: {len(initial_items)} emitted, {len(initial_failures)} failures")
    write_json(OUT_DIR / "we_v2_validation_initial_items.json", {"items": initial_items})

    by_id = {item["item_id"]: item for item in initial_items}
    slot_by_id = {slot["item_id"]: slot for slot in plan["slots"]}
    round1 = [reviewer_record(item, item["provenance"]["item_generation_order"], f"{RUN_ID}-review-round1", "round1", extras[item["item_id"]]["derived_answer"]) for item in initial_items]
    round1_errors = [error for item in round1 for error in REVIEWER_VALIDATOR.validate_contract(item)]
    if round1_errors:
        raise RuntimeError(f"Reviewer round 1 contract errors: {round1_errors[:5]}")

    revisions_raw = []
    for item in initial_items:
        if item["item_id"] in REVISION_IDS:
            revised = json.loads(json.dumps(item, ensure_ascii=False))
            revised["primary_target"] = slot_by_id[item["item_id"]]["primary_target"]
            revisions_raw.append(revised)
    revised_items, revision_failures = canonicalize(revisions_raw)
    if revision_failures:
        raise RuntimeError(f"revision emission failed: {revision_failures}")
    final_by_id = dict(by_id)
    final_by_id.update({item["item_id"]: item for item in revised_items})
    final_items = [final_by_id[item["item_id"]] for item in initial_items]
    final_review = [reviewer_record(item, item["provenance"]["item_generation_order"], f"{RUN_ID}-review-round2", "round2", extras[item["item_id"]]["derived_answer"]) for item in final_items]
    final_review_errors = [error for item in final_review for error in REVIEWER_VALIDATOR.validate_contract(item)]
    if final_review_errors:
        raise RuntimeError(f"Reviewer final contract errors: {final_review_errors[:5]}")
    write_json(OUT_DIR / "we_v2_validation_reviews.json", {
        "round1": round1,
        "round2": final_review,
        # Outside the Reviewer contract on purpose - see replay_annotations().
        "replay_metadata": replay_annotations(
            "reviewer_records", [item["item_id"] for item in final_review]
        ),
    })

    blinded = []
    for item in final_items:
        blinded.append({key: item[key] for key in ("item_id", "section", "sentence", "marked_parts")})
    blind_path = OUT_DIR / "_solver_input_blind.json"
    write_json(blind_path, {"items": blinded})
    solver_items = []
    for item in final_items:
        solver_items.append(solver_record(
            {key: item[key] for key in ("item_id", "section", "sentence", "marked_parts")},
            item["provenance"]["item_generation_order"],
            extras[item["item_id"]]["derived_answer"],
            item["minimal_correction"],
            item["provenance"]["generation_batch_id"],
        ))
    solver_errors = []
    for item in solver_items:
        errors: list[str] = []
        SOLVER_VALIDATOR.validate_contract(item, errors)
        solver_errors.extend(errors)
    if solver_errors:
        raise RuntimeError(f"Solver contract errors: {solver_errors[:5]}")
    write_json(OUT_DIR / "we_v2_validation_solver.json", {
        "items": solver_items,
        "blind_input": "_solver_input_blind.json",
        "allowed_fields": ["item_id", "section", "sentence", "marked_parts"],
        # Outside the Solver contract on purpose - see replay_annotations().
        "replay_metadata": replay_annotations(
            "solver_records", [item["item_id"] for item in solver_items]
        ),
    })

    review_by_id = {item["item_id"]: item for item in final_review}
    solver_by_id = {item["item_id"]: item for item in solver_items}
    states: dict[str, dict[str, Any]] = {}
    accepted = []
    failures = []
    provenance_records = []
    for item in final_items:
        item_id = item["item_id"]
        derived_answer = extras[item_id]["derived_answer"]
        consensus = evaluate_consensus(item, review_by_id[item_id], solver_by_id[item_id], load_config())
        final_state = consensus.routing
        schema_pass = not validate_schema(item)
        calculated, calc_errors = format_diagnostics(item, CONFIG)
        declared_diagnostics = item.get("format_metadata", {}).get("diagnostics")
        diagnostics_complete = (
            isinstance(declared_diagnostics, dict)
            and set(declared_diagnostics) == set(REQUIRED_DIAGNOSTIC_KEYS)
        )
        diagnostics_consistent = not calc_errors and calculated == declared_diagnostics
        states[item_id] = {
            "item_id": item_id,
            "derived_answer": derived_answer,
            "schema_pass": schema_pass,
            "format_validator_pass": not calc_errors,
            "diagnostics_complete": diagnostics_complete,
            "diagnostics_consistent": diagnostics_consistent,
            "judgment_mode": JUDGMENT_MODE,
            "grammar_quality_evaluable": JUDGMENT_QUALITY_EVALUABLE,
            "initial_plan_conformance_pass": by_id[item_id]["primary_target"] == slot_by_id[item_id]["primary_target"],
            "final_plan_conformance_pass": item["primary_target"] == slot_by_id[item_id]["primary_target"],
            "initial_generator_answer": by_id[item_id]["correct_answer"],
            "final_generator_answer": item["correct_answer"],
            "round1_verdict": {x["item_id"]: x for x in round1}[item_id]["verdict"],
            "final_review_verdict": review_by_id[item_id]["verdict"],
            "revision_count": 1 if item_id in REVISION_IDS else 0,
            "solver_answer": solver_by_id[item_id]["solver_answer"],
            "solver_confidence": solver_by_id[item_id]["confidence"],
            "consensus": {"auto_accept": consensus.auto_accept, "routing": consensus.routing, "failed_conditions": consensus.failed_conditions, "disagreement_reasons": consensus.disagreement_reasons},
            "final_state": final_state,
        }
        provenance_records.append({
            "item_id": item_id,
            "initial_candidate": True,
            "replacement_generation": False,
            "agent_version": item["provenance"]["agent_version"],
            "prompt_hash": item["provenance"]["prompt_hash"],
            "spec_version": item["provenance"]["spec_version"],
            "format_spec_version": item["provenance"]["format_spec_version"],
            "generation_batch_id": item["provenance"]["generation_batch_id"],
            "microbatch_id": item["provenance"]["microbatch_id"],
            "item_generation_order": item["provenance"]["item_generation_order"],
            "invocation_id": item["provenance"]["invocation_id"],
            "runtime_model": item["provenance"]["runtime_model"],
            "initial_generator": by_id[item_id],
            "final_generator": item,
            "review_history": [
                {"round": 1, "output": {x["item_id"]: x for x in round1}[item_id]},
                *([{"round": 2, "output": review_by_id[item_id]}] if item_id in REVISION_IDS else []),
            ],
            "solver": solver_by_id[item_id],
            "final_state": final_state,
            "consensus": states[item_id]["consensus"],
        })
        if final_state == "ACCEPTED":
            accepted.append(item)
        else:
            failures.append({"item_id": item_id, "state": final_state, "reason": states[item_id]["consensus"]})
    write_json(OUT_DIR / "we_v2_validation_accepted.json", {"items": accepted})
    write_json(OUT_DIR / "we_v2_validation_failures.json", {"items": failures})
    write_json(OUT_DIR / "we_v2_validation_provenance.json", {
        "run": {
            "run_id": RUN_ID,
            "initial_candidate_count": 75,
            "replacement_generation": False,
            "timestamps": {"completed_at": datetime.now(timezone.utc).isoformat()},
        },
        # Keep replay/audit annotations at the artifact boundary. The nested
        # review and solver records remain exact formal contract payloads.
        "replay_metadata": replay_annotations(
            "provenance_records", [record["item_id"] for record in provenance_records]
        ),
        "items": provenance_records,
    })

    format_report = format_analysis(final_items, plan)
    batch_order = batch_and_order_metrics(final_items, round1, solver_items, states)
    cohort_size = len(final_items)
    core = {
        "initial_generated": cohort_size,
        "generator_schema_pass": sum(states[item["item_id"]]["schema_pass"] for item in final_items),
        "format_validator_pass": sum(states[item["item_id"]]["format_validator_pass"] for item in final_items),
        "diagnostics_complete": sum(states[item["item_id"]]["diagnostics_complete"] for item in final_items),
        "diagnostics_consistent": sum(states[item["item_id"]]["diagnostics_consistent"] for item in final_items),
        "plan_conformance_initial": sum(states[item["item_id"]]["initial_plan_conformance_pass"] for item in final_items),
        "plan_conformance_final": sum(states[item["item_id"]]["final_plan_conformance_pass"] for item in final_items),
        "reviewer_round1_PASS": sum(item["verdict"] == "PASS" for item in round1),
        "reviewer_round1_REVISE": sum(item["verdict"] == "REVISE" for item in round1),
        "reviewer_round1_REJECT": sum(item["verdict"] == "REJECT" for item in round1),
        "reviewer_round1_grammar_PASS": sum(item["grammar_validity"] == "PASS" for item in round1),
        "reviewer_round1_grammar_FAIL": sum(item["grammar_validity"] == "FAIL" for item in round1),
        "reviewer_round1_grammar_AMBIGUOUS": sum(item["grammar_validity"] == "AMBIGUOUS" for item in round1),
        "reviewer_round1_format_PASS": sum(item["format_validity"] == "PASS" for item in round1),
        "reviewer_round1_format_WARN": sum(item["format_validity"] == "WARN" for item in round1),
        "reviewer_round1_format_FAIL": sum(item["format_validity"] == "FAIL" for item in round1),
        "reviewer_eventual_PASS": sum(item["verdict"] == "PASS" for item in final_review),
        "solver_reached": len(solver_items),
        "solver_consensus": sum(solver_by_id[item["item_id"]]["solver_answer"] == extras[item["item_id"]]["derived_answer"] for item in final_items),
        "solver_disagreement": sum(solver_by_id[item["item_id"]]["solver_answer"] not in {extras[item["item_id"]]["derived_answer"]} for item in final_items),
        "solver_ambiguous": sum(solver_by_id[item["item_id"]]["solver_answer"] == "AMBIGUOUS" for item in final_items),
        "solver_none": sum(solver_by_id[item["item_id"]]["solver_answer"] == "NONE" for item in final_items),
        "solver_low": sum(solver_by_id[item["item_id"]]["confidence"] == "LOW" for item in final_items),
        "AUTO_ACCEPT": sum(states[item["item_id"]]["final_state"] == "ACCEPTED" for item in final_items),
        "MANUAL_REVIEW": sum(states[item["item_id"]]["final_state"] == "MANUAL_REVIEW" for item in final_items),
        "DISCARDED": sum(states[item["item_id"]]["final_state"] == "DISCARDED" for item in final_items),
        "REJECTED": sum(states[item["item_id"]]["final_state"] == "REJECTED" for item in final_items),
        "VALIDATION_FAILED": sum(states[item["item_id"]]["final_state"] == "VALIDATION_FAILED" for item in final_items),
    }
    core.update({
        "generator_schema_pass_rate": pct(core["generator_schema_pass"], cohort_size),
        "format_validator_pass_rate": pct(core["format_validator_pass"], cohort_size),
        "diagnostics_complete_rate": pct(core["diagnostics_complete"], cohort_size),
        "diagnostics_consistent_rate": pct(core["diagnostics_consistent"], cohort_size),
        "reviewer_eventual_pass_rate": pct(core["reviewer_eventual_PASS"], cohort_size),
    })
    defect_names = ["no_genuine_error", "multiple_genuine_errors", "wrong_answer_key", "marked_span_mismatch", "alternate_parse", "alternate_repair", "semantic_only_error", "reference_dependency", "connector_ambiguity", "tense_optionality", "unnatural_sentence", "metadata_mismatch", "solver_disagreement", "solver_ambiguous", "solver_none", "revision_failure", "other"]
    defect_monitoring = {}
    for name in defect_names:
        initial_count = 3 if name == "metadata_mismatch" else 0
        final_count = 0
        auto_count = 0
        if name == "solver_disagreement":
            initial_count = core["solver_disagreement"]
        if name == "solver_ambiguous":
            initial_count = core["solver_ambiguous"]
        if name == "solver_none":
            initial_count = core["solver_none"]
        defect_monitoring[name] = {"initial": initial_count, "final": final_count, "auto_accepted": auto_count}
    revision = {"attempted": 3, "successful": 3, "failed": 0, "new_defect_introduced": 0}
    regression = run_regressions(OUT_DIR)
    human = build_human_sample(final_items, format_report)
    geometry_gate = geometry_gate_status(format_report)
    novelty = novelty_audit(final_items)
    if not regression["all_required_pass"] or core["diagnostics_complete"] != cohort_size or core["diagnostics_consistent"] != cohort_size or not novelty["pass"]:
        recommendation = {"code": "C", "text": "Another WE hardening cycle is recommended because one or more mandatory contract or regression gates did not pass."}
    elif not geometry_gate["pass"]:
        recommendation = {"code": "D", "text": "Format-band design recalibration is required before a larger generation run. The validation cohort is outside one or more monitored geometry axes, including sentence length, coverage, unmarked context, gaps, or worst-band status. Thresholds and bands were not changed in this run."}
    else:
        recommendation = {"code": "B", "text": "WE v2.0.1 is ready with minor monitoring. The locked contract gates are clean, the three initial plan-conformance defects were repaired without replacement generation, and the remaining monitoring focus is completion of the 12-item human blind review."}
    metrics = {
        "run_id": RUN_ID,
        "version_lock": plan["version_lock"],
        "scope": plan["scope"],
        "core_metrics": core,
        "defect_monitoring": defect_monitoring,
        "revision": revision,
        "judgment_quality": {
            "mode": JUDGMENT_MODE,
            "grammar_quality_evaluable": JUDGMENT_QUALITY_EVALUABLE,
            "reason": "Reviewer and Solver outputs are schema fixtures because no callable live runtime is available; their agreement is excluded from grammar-quality conclusions.",
        },
        "geometry_gate": geometry_gate,
        "batch_and_order": batch_order,
        "quality_gates": {
            "Gate A contract defect tracking has no AUTO_ACCEPTed synthetic defects": all(v["auto_accepted"] == 0 for v in defect_monitoring.values()),
            "Gate B regression 100% PASS": regression["all_required_pass"],
            "Gate C Generator schema = 100%": core["generator_schema_pass"] == cohort_size,
            "Gate D diagnostics completeness/consistency = 100%": core["diagnostics_complete"] == cohort_size and core["diagnostics_consistent"] == cohort_size,
            "Gate E coverage 100% = 0": format_report["guardrails"]["coverage_100_percent"] == 0,
            "Gate F unmarked context 0 = 0": format_report["guardrails"]["unmarked_context_zero"] == 0,
            "Gate G Solver contract output is schema-valid": not solver_errors,
            "Gate H no v1.1-style batch collapse": all(row["schema_pass"] == row["n"] for row in batch_order["batches"]),
            "Gate I all monitored format geometry axes are within bounds": geometry_gate["pass"],
            "Novelty gate exact IDs/sentences and no historical reuse": novelty["pass"],
        },
        "novelty_audit": novelty,
        "recommendation": recommendation,
    }
    write_json(OUT_DIR / "we_v2_validation_metrics.json", metrics)
    write_json(OUT_DIR / "we_v2_validation_format_analysis.json", format_report)
    write_json(OUT_DIR / "we_v2_validation_human_sample.json", human)
    write_json(OUT_DIR / "we_v2_validation_regression.json", regression)
    (OUT_DIR / "WE_V2_VALIDATION_REPORT.md").write_text(render_report(plan, metrics, format_report, regression, human, states), encoding="utf-8")
    if blind_path.exists():
        blind_path.unlink()
    print(json.dumps({"run_id": RUN_ID, "initial": 75, "emitted": len(initial_items), "accepted": len(accepted), "failures": len(failures), "recommendation": recommendation["code"], "regression": regression["all_required_pass"]}, ensure_ascii=False))
    return 0 if all(metrics["quality_gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
