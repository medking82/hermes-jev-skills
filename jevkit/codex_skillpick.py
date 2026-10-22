"""Codex adaptation of TypeSafe's official two-request skill-suggestion recipe.

https://docs.typesafe.ai/cookbooks/skill_suggestion
Choice ranks/selects; independent Nouls decide whether to recommend anything.
Keep the community selector unchanged for other hosts and comparative evaluation.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
import stat

from . import client, privacy, skillpick

RECIPE = "typesafe-skill-suggestion-v1"
SHORTLIST = 3
EXCERPT_CHARS = 700
DESCRIPTION_CHARS = 8000
READ_CHARS = 16000
GATE_THRESHOLD = 0.30
FITS_THRESHOLD = 0.30
GATE_QUESTIONS = {
    "acts_on_user_system": (
        "Is the assistant being asked to act on the user's files, accounts, devices, "
        "or online services, rather than only to explain or advise?"),
    "would_follow_documented_procedure": (
        "Would a careful expert answering this consult a specific documented procedure "
        "or set of commands, rather than answering from general understanding?"),
    "prose_suffices": (
        "Could a knowledgeable generalist fully satisfy this request in prose, with "
        "no tools, no documentation, and no access to the user's files or accounts?"),
}
_CJK_SENSITIVE = re.compile(r"密码|密钥|口令|私钥|银行卡|信用卡|身份证|客户资料|隐私数据")


def build_state(turn):
    # Match the cookbook's request state. Context remains empty until separately
    # evaluated; this is not task-history collection or cross-turn deduplication.
    return {"request": privacy.redact(turn, 2000), "recent_context": ""}


def stage_one_questions(catalog):
    options = {s["name"]: s["description"][:skillpick.DESCRIPTION_CHARS] for s in catalog}
    # The API requires two options. A singleton's applicability still needs judging.
    if len(options) == 1:
        none = "__no_match__"
        while none in options:
            none += "_"
        options[none] = "No catalog skill applies."
    return dict({"which": client.choice(
        "Which of these skills, if any, is the right one to load to help with the user's latest request?", options)},
                **{"gate::" + key: client.noul(text) for key, text in GATE_QUESTIONS.items()})


def _probability(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise client.JevError("invalid_response")
    return value


def _clean_evidence(text, limit):
    """Withhold sensitive lines, including instructional credential examples."""
    lines, withheld, usable = [], 0, False
    for line in text.splitlines():
        if privacy.is_sensitive(line) or _CJK_SENSITIVE.search(line):
            lines.append("[sensitive line withheld]")
            withheld += 1
        else:
            lines.append(line)
            usable = usable or bool(line.strip() and not line.lstrip().startswith("#"))
    return privacy.redact("\n".join(lines), limit)[:limit], withheld, usable


def evidence(skill):
    """Read only an admitted candidate's bounded entrypoint, never linked resources."""
    path = Path(skill["path"])
    if not path.is_absolute() or path.name != "SKILL.md":
        raise client.JevError("skill_evidence_unavailable")
    try:
        for node in (path, *path.parents):
            info = node.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
                raise OSError("linked entrypoint")
        if not stat.S_ISREG(path.stat().st_mode):
            raise OSError("not a regular entrypoint")
        with path.open(encoding="utf-8-sig") as stream:
            prefix = stream.read(READ_CHARS)
    except (OSError, UnicodeError):
        raise client.JevError("skill_evidence_unavailable") from None
    front = re.match(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", prefix, re.S)
    if prefix.startswith("---\n") and not front:
        raise client.JevError("skill_evidence_unavailable")
    description = skillpick._front_matter(prefix).get("description") or skill["description"]
    body = prefix[front.end():] if front else prefix
    body = body.lstrip()[:EXCERPT_CHARS]
    if len(description) > DESCRIPTION_CHARS:
        raise client.JevError("skill_evidence_unavailable")
    # Documentation often names credential setup without containing a credential.
    # Withhold those lines entirely, not the other candidates' useful evidence.
    # Do not downgrade to description-only when all substantive body is withheld.
    description, description_withheld, usable_description = _clean_evidence(description, DESCRIPTION_CHARS)
    body, body_withheld, usable_body = _clean_evidence(body, EXCERPT_CHARS)
    if not usable_description or ((description_withheld or body_withheld) and not usable_body):
        raise client.JevError("skill_evidence_sensitive")
    fingerprint = hashlib.sha256((description + "\n" + body).encode("utf-8")).hexdigest()
    return {"description": description, "body": body}, {
        "name": skill["name"], "evidence_sha256": fingerprint, "body_chars": len(body),
        "redacted_lines": description_withheld + body_withheld}


def evidence_unchanged(result, catalog):
    """A duplicate may reuse its decision only while the actual evidence is unchanged."""
    rows = {s["name"]: s for s in catalog}
    try:
        for prior in result.get("verification", {}).get("evidence", []):
            if evidence(rows[prior["name"]])[1] != prior:
                return False
    except (KeyError, client.JevError):
        return False
    return True


def verify(turn, catalog, stage_one, *, ask_fn, request_gate=False):
    """Finish the official recipe from a shared first request; at most one more call."""
    answers = stage_one["answers"]
    values = {key: _probability(answers["gate::" + key]["noul"]) for key in GATE_QUESTIONS}
    gate = sum(1 - v if k == "prose_suffices" else v for k, v in values.items()) / len(values)
    details = {"recipe": RECIPE, "gate": round(gate, 6), "gate_values": values,
               "gate_threshold": GATE_THRESHOLD, "request_gate_enforced": request_gate,
               "fits_threshold": FITS_THRESHOLD,
               "shortlist": [], "evidence": []}
    result = {"status": "ok", "skills": [], "needs_skill": round(gate, 6),
              "latency_ms": stage_one.get("latency_ms", 0), "verification": details}
    # The official request-only gate missed a covered request in the paired run
    # and another local-catalog smoke case. Keep it evaluable, but production
    # reads the actual candidate procedures before abstaining. See the scorecard.
    if request_gate and gate < GATE_THRESHOLD:
        details["outcome"] = "gate_no_match"
        return result
    probabilities = answers["which"]["probabilities"]
    by_name = {s["name"]: s for s in catalog}
    expected = set(stage_one_questions(catalog)["which"]["criteria"])
    if set(probabilities) != expected:
        raise client.JevError("invalid_response")
    ranked = sorted(probabilities, key=lambda name: -_probability(probabilities[name]))
    names = [name for name in ranked if name in by_name][:SHORTLIST]
    details["shortlist"] = names
    texts = {}
    try:
        for name in names:
            texts[name], metadata = evidence(by_name[name])
            details["evidence"].append(metadata)
    except client.JevError as error:
        result.update(status="fail_open", reason_code=error.code)
        details["outcome"] = "evidence_unavailable"
        return result
    questions = {}
    if len(names) > 1:
        questions["which"] = client.choice(
            "Exactly one of these skills is the right one to load for the user's latest "
            "request. Which one? Read what each actually does, not just its name.",
            {name: texts[name]["description"] + "\n" + texts[name]["body"] for name in names})
    for name in names:
        # As in the cookbook, Choice gets the excerpt; Nouls independently check
        # each full description. max(fits), not the Choice's confidence, gates output.
        questions["fits::" + name] = client.noul(
            "Does the skill '" + name + "' do the specific thing the user's request asks "
            "for? It is described as: " + texts[name]["description"])
    reply = ask_fn(build_state(turn), questions, timeout=1.4)
    fits = {name: _probability(reply["answers"]["fits::" + name]["noul"]) for name in names}
    winner = names[0] if len(names) == 1 else reply["answers"]["which"]["choice"]
    if winner not in names:
        raise client.JevError("invalid_response")
    details.update(fits=fits, winner=winner, outcome="selected" if max(fits.values()) >= FITS_THRESHOLD else "fit_no_match")
    result["latency_ms"] += reply.get("latency_ms", 0)
    if max(fits.values()) >= FITS_THRESHOLD:
        result["skills"] = [{"name": winner, "path": by_name[winner]["path"], "match": fits[winner]}]
    return result
