# apps/dsn_study/api/decision.py
"""The System-1 decision API for dsn_study, so that skills, the web client and
the operator can all use the decision capability.
#
#   GET  /api/decision/status    status (running, VRAM, idle reclaim)
#   POST /api/decision/probe     read the user state (emotion and crisis)
#   POST /api/decision/classify  classify into labels (question type, difficulty)
#   POST /api/decision/retrieval the retrieval gate (does this need a source)
#   POST /api/decision/warmup    warm the model up in the background
#   POST /api/decision/stop      release the VRAM right now
#
# A decision is an extra capability, so every failure answers 200 with a
# degraded marker instead of 5xx: a caller, especially a skill, must not fail
# as a whole because the decision was not available.
"""

from __future__ import annotations

import logging
import threading

from flask import Blueprint, jsonify, request, g

logger = logging.getLogger("DecisionAPI")

decision_bp = Blueprint("decision_api", __name__)

_auth_manager = None


def init_decision_api(auth_manager):
    global _auth_manager
    _auth_manager = auth_manager


@decision_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


def _body() -> dict:
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@decision_bp.route("/api/decision/status", methods=["GET"])
def decision_status():
    """Status of the decision subsystem."""
    from apps.dsn_study.models import decision_service as ds

    try:
        info = ds.decision_service_status()
    except Exception as e:
        logger.warning("cannot read the decision status: %s", e)
        return jsonify({"error": str(e)}), 200
    return jsonify(info)


@decision_bp.route("/api/decision/probe", methods=["POST"])
def decision_probe():
    """Read the user state (emotion and crisis).

    Answers with a degraded marker when no decision is possible, and the
    caller decides whether it can use the result.
    """
    from apps.dsn_study.models import decision_service as ds

    data = _body()
    text = str(data.get("text") or "")
    is_voice = bool(data.get("is_voice"))
    try:
        state = ds.probe_state(text, is_voice=is_voice)
    except Exception as e:
        logger.warning("the state probe failed: %s", e)
        return jsonify({"degraded": True, "reason": str(e)}), 200
    return jsonify(state.to_dict()), 200


@decision_bp.route("/api/decision/classify", methods=["POST"])
def decision_classify():
    """Sort a piece of content into one of the given labels."""
    from apps.dsn_study.models import decision_service as ds

    data = _body()
    text = str(data.get("text") or "")
    labels = data.get("labels") or []
    if not isinstance(labels, list) or not labels:
        return jsonify({"error": "labels must be a non-empty array"}), 400
    try:
        label = ds.classify_question(text, [str(x) for x in labels])
    except Exception as e:
        logger.warning("the classification failed: %s", e)
        return jsonify({"degraded": True, "reason": str(e)}), 200
    if label is None:
        return jsonify({"degraded": True, "reason": "the decision service is not available"}), 200
    return jsonify({"label": label}), 200


@decision_bp.route("/api/decision/retrieval", methods=["POST"])
def decision_retrieval():
    """The retrieval gate: does this question need a source."""
    from apps.dsn_study.models import decision_service as ds

    data = _body()
    question = str(data.get("question") or "")
    context = str(data.get("context") or "")
    try:
        out = ds.needs_retrieval(question, context)
    except Exception as e:
        logger.warning("the retrieval gate failed: %s", e)
        return jsonify({"degraded": True, "reason": str(e)}), 200
    if out is None:
        return jsonify({"degraded": True, "reason": "the decision service is not available"}), 200
    return jsonify(out.to_dict()), 200


@decision_bp.route("/api/decision/warmup", methods=["POST"])
def decision_warmup():
    """Warm the decision model up in the background.

    The llama-server cold start takes tens of seconds, so the request returns
    immediately and the work happens in a thread.
    """
    from apps.dsn_study.models import decision_service as ds

    def _run():
        try:
            ds.warmup_decision()
        except Exception as e:
            logger.warning("the decision warmup failed: %s", e)

    threading.Thread(target=_run, daemon=True, name="decision-warmup-api").start()
    return jsonify({"status": "warming"}), 200


@decision_bp.route("/api/decision/stop", methods=["POST"])
def decision_stop():
    """Stop the decision model now and return the VRAM, without waiting for
    the idle timeout."""
    from apps.dsn_study.models.resource_setup import get_study_pool
    from infra.resources.decision_service import DECISION_RESOURCE

    pool = get_study_pool()
    if pool is None or pool.get_spec(DECISION_RESOURCE) is None:
        return jsonify({"error": "the decision resource is not registered"}), 404
    ok = pool.stop_resource(DECISION_RESOURCE)
    return jsonify({"stopped": bool(ok)}), 200
