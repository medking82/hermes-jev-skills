"""Blender's default decision boundary: code first, optional bounded read-only Jev advice.

No source code, filenames, object names, images, free text or measurements leave
this module. Jev can prioritize a probe; it cannot edit, approve or finish a job.
The executor owns Blender, permissions, checkpoints, budgets and verification.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, Mapping
from .choose import MIN_CONFIDENCE, choose

SCHEMA = 'jev.blender_state_v1'
CHECKS = ('geometry', 'materials', 'framing', 'lighting', 'preview', 'export')
ISSUES = ('none', 'geometry', 'materials', 'framing', 'lighting', 'export', 'unclear')
FIELDS = {'schema', 'revision', 'issue', 'symptoms', 'export_requested', 'private', 'stagnation', 'estimated_probe_ms'} | set(CHECKS)
SYMPTOMS = {'render_dark', 'viewport_visible', 'color_mismatch', 'geometry_matches',
            'subject_clipped', 'unexpected_shadow', 'faceted_surface', 'export_only_difference'}
PROBES = {
    'inspect_geometry': 'Inspect local mesh topology, normals, smooth shading and transforms against the specification',
    'inspect_materials': 'Inspect local material assignments and shader settings',
    'inspect_framing': 'Inspect local camera framing and visible bounds',
    'inspect_lighting': 'Inspect local light and exposure settings',
}
# Conservative economic gate, not a claim of calibrated rendering performance.
# The caller must supply a measured lower bound for the expensive alternative.
MIN_EXPENSIVE_PROBE_MS = 1000


def validate(state: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(state, Mapping) or set(state) != FIELDS or state.get('schema') != SCHEMA:
        raise ValueError('Blender state must match the exact closed schema')
    for check in CHECKS:
        if not isinstance(state[check], str) or state[check] not in ('unknown', 'pass', 'fail'):
            raise ValueError('Check states must be unknown, pass or fail')
    if not isinstance(state['issue'], str) or state['issue'] not in ISSUES:
        raise ValueError('Issue must use the fixed vocabulary')
    symptoms = state['symptoms']
    if (not isinstance(symptoms, list) or len(symptoms) > len(SYMPTOMS)
            or any(not isinstance(item, str) or item not in SYMPTOMS for item in symptoms)
            or len(set(symptoms)) != len(symptoms)):
        raise ValueError('Symptoms must be unique entries from the fixed vocabulary')
    for key in ('private', 'export_requested'):
        if type(state[key]) is not bool:
            raise ValueError('Flags must be actual booleans')
    for key in ('revision', 'stagnation', 'estimated_probe_ms'):
        if type(state[key]) is not int or not 0 <= state[key] <= 1_000_000_000:
            raise ValueError('Counters must be bounded nonnegative integers')
    return dict(state)


def build_request(state: Mapping[str, Any]) -> Dict[str, Any]:
    clean = validate(state)
    if clean['private']:
        raise ValueError('Private Blender work never enters this selector')
    identifier = 'blend-' + hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()[:12]
    return {
        'schema': 'jev.action_choice_request_v1',
        'goal': 'Prioritize one safe local diagnostic probe for an unclear visual discrepancy. Do not edit or declare completion.',
        'observation_id': identifier,
        'regions': [{'id': check, 'role': 'local_check', 'label': check + ': ' + clean[check], 'interactive': False}
                    for check in CHECKS if check != 'export' or clean['export_requested']] + [
                        {'id': 'symptom-' + str(i), 'role': 'observed_symptom',
                         'label': symptom.replace('_', ' '), 'interactive': False}
                        for i, symptom in enumerate(clean['symptoms'])],
        'history': [],
        'candidates': [{'id': key, 'description': value} for key, value in PROBES.items()] + [
            {'id': 'reobserve', 'description': 'Return to the local planner for a fresh diagnosis'},
            {'id': 'abstain', 'description': 'Abstain because no diagnostic probe is supported'}],
    }


def select(state: Mapping[str, Any], *, timeout: float = 1.0, transport=None) -> Dict[str, Any]:
    clean = validate(state)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout must be positive and finite')
    budget = min(float(timeout), 1.0)

    def direct(action, reason, called=False):
        return {'action': action, 'reason': reason, 'jev_called': called,
                'requires_local_verification': True, 'revision': clean['revision']}

    required = [check for check in CHECKS if check != 'export' or clean['export_requested']]
    if any(clean[check] == 'fail' for check in required):
        return direct('planner_repair', 'failed_local_check')
    for check in required:
        if clean[check] == 'unknown':
            return direct('render_preview' if check == 'preview' else 'inspect_' + check, 'mandatory_local_check')
    if clean['issue'] == 'none':
        return direct('verify_artifacts', 'verification_is_not_a_model_verdict')
    if clean['issue'] != 'unclear':
        return direct('inspect_' + clean['issue'], 'known_issue')
    if clean['private'] or clean['stagnation'] >= 2 or clean['estimated_probe_ms'] < MIN_EXPENSIVE_PROBE_MS:
        return direct('planner_inspect', 'local_planner_is_safer_or_cheaper')
    request = build_request(clean)
    try:
        pick = choose(request, timeout=budget, transport=transport, usage_feature='blender_advice')
        confidence = pick.get('confidence')
        if (pick.get('observation_id') == request['observation_id']
                and type(confidence) in (int, float) and math.isfinite(confidence)
                and max(.65, MIN_CONFIDENCE) <= confidence <= 1
                and pick.get('selected_id') in PROBES):
            result = direct(pick['selected_id'], 'bounded_read_only_advice', called=True)
            result['confidence'] = confidence
            return result
    except Exception:
        # The same local planner takes over when no valid Jev advice exists.
        pass
    return direct('planner_inspect', 'jev_unavailable_or_unusable', called=True)
