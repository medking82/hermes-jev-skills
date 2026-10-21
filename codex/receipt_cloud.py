"""Bounded, stdlib-only receiver; repository_dispatch.client_payload IS the report.

validate(report, policy) returns a detached sanitized report or raises ValueError.
decide(report, now) and outage(state, now) are pure alert planners.
receive(api, report, policy, now, workflow_url) and watchdog(...) use the small
GitHubAPI interface below. No updater, payload code, or credential store is read.
State writes precede notifications; processed keys follow them. Issue markers
survive failed writes, closed issues, and bounded local history eviction.
"""

import argparse
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPOSITORIES = {"jev": "medking82/hermes-jev-skills",
                "native-review": "medking82/native-review"}
BRANCH = "updater-receipts"
MAX_REPORT = 16384
MAX_STATE = 524288
MAX_SEEN = 2048
REPORT_MAX_AGE = timedelta(minutes=15)
CLOCK_SKEW = timedelta(minutes=5)
REASONS = {"conflict", "ci-failure", "local-tests-failure", "local-edits",
           "pinned-controls", "permissions", "launcher-failure", "stale-receipt",
           "upstream-stopped", "validation-failure", "offline", "pending-ci",
           "unclassified-stop"}
STATUSES = {"unchanged", "updated", "stopped", "deferred", "enrolled", "ready"}
FIELDS = {"schema", "device", "kind", "observed_at", "task", "receipt",
          "last_update", "blocked", "launcher", "canary"}
EVENT_FIELDS = {"status", "event_id", "observed_at", "commit", "run_url", "reason"}


def matches(pattern, value):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid object fields")


def timestamp(value):
    if not matches(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        raise ValueError("Invalid UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError("Invalid UTC timestamp") from None


def utc(value):
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("UTC clock required")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_policy(policy):
    exact(policy, {"schema", "kind", "devices", "canary_devices"})
    if type(policy["schema"]) is not int or policy["schema"] != 1:
        raise ValueError("Invalid policy schema")
    if type(policy["kind"]) is not str or policy["kind"] not in REPOSITORIES:
        raise ValueError("Invalid policy kind")
    for name in ("devices", "canary_devices"):
        values = policy[name]
        if (type(values) is not list or len(values) > 256
                or any(not matches(r"[0-9a-f]{16}", value) for value in values)
                or len(set(values)) != len(values)):
            raise ValueError("Invalid device registry")
    if not set(policy["canary_devices"]) <= set(policy["devices"]):
        raise ValueError("Canaries must be registered")
    return policy


def validate_event(value, kind):
    if value is None:
        return
    exact(value, EVENT_FIELDS)
    if type(value["status"]) is not str or value["status"] not in STATUSES:
        raise ValueError("Invalid receipt status")
    if not matches(r"[0-9]{1,24}", value["event_id"]):
        raise ValueError("Invalid event ID")
    timestamp(value["observed_at"])
    if value["commit"] is not None and not matches(r"[0-9a-f]{40}", value["commit"]):
        raise ValueError("Invalid commit")
    if value["run_url"] is not None and not matches(
            r"https://github\.com/" + re.escape(REPOSITORIES[kind])
            + r"/actions/runs/[0-9]+", value["run_url"]):
        raise ValueError("Invalid CI URL")
    if value["reason"] is not None and (
            type(value["reason"]) is not str or value["reason"] not in REASONS):
        raise ValueError("Invalid reason code")


def validate(report, policy):
    validate_policy(policy)
    exact(report, FIELDS)
    if type(report["schema"]) is not int or report["schema"] != 1:
        raise ValueError("Invalid report schema")
    if report["kind"] != policy["kind"] or type(report["kind"]) is not str:
        raise ValueError("Kind differs from policy")
    if not matches(r"[0-9a-f]{16}", report["device"]) or report["device"] not in policy["devices"]:
        raise ValueError("Device is not registered")
    if (type(report["canary"]) is not bool
            or report["canary"] != (report["device"] in policy["canary_devices"])):
        raise ValueError("Canary identity differs from policy")
    timestamp(report["observed_at"])
    task = report["task"]
    exact(task, {"state", "last_run", "last_result"})
    if type(task["state"]) is not str or task["state"] not in {
            "Ready", "Running", "Disabled", "Missing", "Denied"}:
        raise ValueError("Invalid task state")
    if task["last_run"] is not None:
        timestamp(task["last_run"])
    if task["last_result"] is not None and type(task["last_result"]) is not int:
        raise ValueError("Invalid task result")
    for name in ("receipt", "last_update", "blocked", "launcher"):
        validate_event(report[name], report["kind"])
    if report["last_update"] is not None and report["last_update"]["status"] != "updated":
        raise ValueError("Invalid last update")
    if report["blocked"] is not None and report["blocked"]["status"] != "stopped":
        raise ValueError("Invalid blocked receipt")
    if len(json.dumps(report, allow_nan=False).encode("utf-8")) > MAX_REPORT:
        raise ValueError("Report too large")
    return copy.deepcopy(report)


def alert(key, category, event=None, reason=None):
    return {"key": key, "category": category,
            "reason": reason or (event or {}).get("reason"),
            "commit": (event or {}).get("commit"),
            "run_url": (event or {}).get("run_url")}


def decide(report, now):
    """Plan alerts from an already validated report, without mutating it."""
    utc(now)
    result = {}
    current = report["receipt"]
    for field in ("receipt", "blocked", "launcher", "last_update"):
        event = report[field]
        if event is None:
            continue
        if event["status"] == "stopped":
            key = "event:stopped:" + event["event_id"]
            result.setdefault(key, alert(key, "launcher" if field == "launcher" else "stopped", event))
        elif event["status"] == "updated":
            key = "event:updated:" + event["event_id"]
            imported = not (current and current["status"] == "updated"
                            and current["event_id"] == event["event_id"]
                            and timestamp(report["observed_at"]) - timestamp(event["observed_at"])
                            <= REPORT_MAX_AGE)
            result.setdefault(key, alert(key, "receipt-imported" if imported else "updated", event))
    task = report["task"]
    context = report["blocked"] or current or report["launcher"] or report["last_update"]
    if task["state"] in {"Disabled", "Missing", "Denied"}:
        key = "task:" + task["state"] + ":" + ((current or {}).get("event_id") or "0")
        result[key] = alert(key, "task-" + task["state"], context,
                            "permissions" if task["state"] == "Denied" else "unclassified-stop")
    blocked = report["blocked"]
    sticky = (task["last_result"] == 2 and blocked and current
              and current["status"] == "stopped"
              and blocked["event_id"] == current["event_id"])
    if task["state"] == "Ready" and task["last_run"] is not None and not sticky:
        last_run = timestamp(task["last_run"])
        if (now - last_run > timedelta(minutes=5)
                and (current is None or current["status"] == "enrolled"
                     or last_run > timestamp(current["observed_at"]))):
            key = "task:stale:" + task["last_run"]
            result[key] = alert(key, "stale", context, "stale-receipt")
    return list(result.values())


def outage(state, now):
    """An outage says nothing about CI or local tests; no state means no enrollment."""
    utc(now)
    if state is None:
        return []
    receipt = state["report"]["receipt"]
    if receipt and receipt["status"] == "deferred" and receipt["reason"] == "offline":
        return []
    if now - timestamp(state["received_at"]) <= timedelta(hours=3):
        return []
    key = "outage:" + state["received_at"]
    return [alert(key, "reporting-unavailable", reason="offline")]


def marker(report, key):
    namespace = [report["kind"], report["device"], report["canary"], key]
    digest = hashlib.sha256(json.dumps(namespace, separators=(",", ":")).encode()).hexdigest()
    return "<!-- updater-receipt:v1:" + digest + " -->"


def issue(report, item, workflow_url):
    titles = {"updated": "Updated", "receipt-imported": "Receipt Imported",
              "stopped": "Stopped", "launcher": "Launcher Failure", "stale": "Stale Receipt",
              "reporting-unavailable": "Reporting Unavailable"}
    category = item["category"]
    title = titles.get(category, category.replace("task-", "Task "))
    prefix = "[LIVE CANARY] " if report["canary"] else ""
    suffix = " " + item["commit"][:12] if item["commit"] else ""
    body = [marker(report, item["key"]),
            "LIVE CANARY: isolated test device; not production." if report["canary"] else "Production device.",
            "Kind: " + report["kind"], "Device: " + report["device"],
            "Class: " + category, "Reason: " + (item["reason"] or "none")]
    if category == "reporting-unavailable":
        body.append("No report for more than three hours. No CI or local test conclusion is available.")
    if category == "receipt-imported":
        body.append("Historical update receipt imported; this does not indicate current task success.")
    if item["commit"]:
        body.append("Commit: " + item["commit"])
    if item["run_url"]:
        body.append("CI: " + item["run_url"])
    body.append("Receiver Workflow: " + workflow_url)
    return {"title": prefix + "[Updater " + title + "]" + suffix,
            "body": "\n\n".join(body)}


def validate_state(state, policy, device):
    exact(state, {"schema", "report", "received_at", "last_receipt", "last_update", "seen_event_ids"})
    if type(state["schema"]) is not int or state["schema"] != 1:
        raise ValueError("Invalid state schema")
    validate(state["report"], policy)
    if state["report"]["device"] != device:
        raise ValueError("State device mismatch")
    timestamp(state["received_at"])
    for name in ("last_receipt", "last_update"):
        validate_event(state[name], policy["kind"])
    if state["last_update"] is not None and state["last_update"]["status"] != "updated":
        raise ValueError("Invalid saved update")
    seen = state["seen_event_ids"]
    if (type(seen) is not list or len(seen) > MAX_SEEN or any(not matches(
            r"(?:event:(?:stopped|updated):[0-9]{1,24}|task:(?:Disabled|Missing|Denied)(?::[0-9]{1,24})?|"
            r"(?:task:stale|outage):[0-9TZ:-]{20})", key) for key in seen)):
        raise ValueError("Invalid processed events")
    return state


def latest(previous, candidate):
    if candidate is None:
        return previous
    if previous is None or timestamp(candidate["observed_at"]) >= timestamp(previous["observed_at"]):
        return copy.deepcopy(candidate)
    return previous


def notify(api, state, sha, items, workflow_url):
    report = state["report"]
    pending = [item for item in items if item["key"] not in state["seen_event_ids"]]
    if not pending:
        return 0
    # REST all-state pagination is authoritative, including closed issues. Never edit.
    markers = set()
    for existing in api.issues():
        if "pull_request" not in existing:
            markers.update(re.findall(r"(?m)^<!-- updater-receipt:v1:[0-9a-f]{64} -->$",
                                      existing.get("body") or ""))
    created = 0
    for item in pending:
        identity = marker(report, item["key"])
        if identity not in markers:
            api.create_issue(issue(report, item, workflow_url))
            markers.add(identity)
            created += 1
        state["seen_event_ids"].append(item["key"])
    state["seen_event_ids"] = state["seen_event_ids"][-MAX_SEEN:]
    api.save_state(report["device"], state, sha)
    return created


def receive(api, report, policy, now, workflow_url):
    """Explicit dispatch only: may bootstrap the dedicated branch from main."""
    report = validate(report, policy)
    timestamp(utc(now))
    age = now - timestamp(report["observed_at"])
    if age > REPORT_MAX_AGE or age < -CLOCK_SKEW:
        raise ValueError("Report observation outside freshness window")
    times = [report["task"]["last_run"]]
    times.extend(report[name]["observed_at"] for name in
                 ("receipt", "last_update", "blocked", "launcher") if report[name])
    if any(value and timestamp(value) - now > CLOCK_SKEW for value in times):
        raise ValueError("Future receipt or task observation")
    validate_workflow_url(workflow_url, policy["kind"])
    api.ensure_branch(create=True)
    state, sha = api.load_state(report["device"])
    if state is None:
        state = {"schema": 1, "report": report, "received_at": utc(now),
                 "last_receipt": None, "last_update": None, "seen_event_ids": []}
    else:
        validate_state(state, policy, report["device"])
        # An older observation cannot replace state or refresh its outage clock.
        if timestamp(report["observed_at"]) < timestamp(state["report"]["observed_at"]):
            return 0
    items = decide(report, now)
    if timestamp(report["observed_at"]) >= timestamp(state["report"]["observed_at"]):
        state["report"] = report
    state["received_at"] = utc(now)
    state["last_receipt"] = latest(state["last_receipt"], report["receipt"])
    state["last_update"] = latest(state["last_update"], report["last_update"])
    if report["receipt"] and report["receipt"]["status"] == "updated":
        state["last_update"] = latest(state["last_update"], report["receipt"])
    # Persist input before side effects, so watchdog can retry a failed notification.
    sha = api.save_state(report["device"], state, sha)
    return notify(api, state, sha, items, workflow_url)


def watchdog(api, policy, now, workflow_url):
    validate_policy(policy)
    validate_workflow_url(workflow_url, policy["kind"])
    utc(now)
    if not api.ensure_branch(create=False):
        return {"production": 0, "canary": 0}
    counts = {"production": 0, "canary": 0}
    for device in policy["devices"]:
        # Canaries are explicit dispatch tests, never continuously monitored hosts.
        if device in policy["canary_devices"]:
            continue
        state, sha = api.load_state(device)
        if state is None:
            continue
        validate_state(state, policy, device)
        count = notify(api, state, sha, decide(state["report"], now) + outage(state, now), workflow_url)
        counts["canary" if state["report"]["canary"] else "production"] += count
    return counts


class CloudError(Exception):
    """Safe fixed error; API bodies and CLI stderr never reach logs."""


class GitHubAPI:
    def __init__(self, repository):
        if repository not in REPOSITORIES.values():
            raise ValueError("Unapproved repository")
        self.root = "repos/" + repository
        self.owner = repository.split("/")[0]

    def request(self, method, endpoint, payload=None, missing=False, assignment=False):
        command = ["gh", "api", "--hostname", "github.com", "--include", "--method", method,
                   self.root + "/" + endpoint]
        if payload is not None:
            command.extend(["--input", "-"])
        try:
            result = subprocess.run(command, input=None if payload is None else json.dumps(payload),
                                    capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError):
            raise CloudError("GitHub API transport failed") from None
        header, separator, body = result.stdout.replace("\r\n", "\n").partition("\n\n")
        status = re.match(r"HTTP/\S+ ([0-9]{3})(?: |$)", header)
        code = int(status[1]) if status else 0
        if missing and code == 404:
            return None
        if assignment and code == 422:
            return None
        if result.returncode or not separator or not 200 <= code < 300:
            raise CloudError("GitHub API request failed")
        try:
            return json.loads(body) if body.strip() else {}
        except ValueError:
            raise CloudError("GitHub API response invalid") from None

    def ensure_branch(self, create):
        if self.request("GET", "git/ref/heads/" + BRANCH, missing=True) is not None:
            return True
        if not create:
            return False
        source = self.request("GET", "git/ref/heads/main")
        self.request("POST", "git/refs", {"ref": "refs/heads/" + BRANCH,
                                           "sha": source["object"]["sha"]})
        return True

    def load_state(self, device):
        data = self.request("GET", "contents/state/" + device + ".json?ref=" + BRANCH, missing=True)
        if data is None:
            return None, None
        try:
            if data.get("encoding") != "base64" or len(data["content"]) > MAX_STATE * 2:
                raise ValueError
            raw = base64.b64decode(data["content"].replace("\n", ""), validate=True)
            if len(raw) > MAX_STATE:
                raise ValueError
            return json.loads(raw), data["sha"]
        except (ValueError, KeyError, TypeError):
            raise CloudError("Saved receipt state invalid") from None

    def save_state(self, device, state, sha):
        raw = json.dumps(state, sort_keys=True, indent=2).encode("utf-8")
        if len(raw) > MAX_STATE:
            raise CloudError("Receipt state limit exceeded")
        payload = {"message": "Record sanitized updater receipt", "branch": BRANCH,
                   "content": base64.b64encode(raw).decode("ascii")}
        if sha is not None:
            payload["sha"] = sha
        result = self.request("PUT", "contents/state/" + device + ".json", payload)
        return result["content"]["sha"]

    def issues(self):
        page = 1
        while True:
            batch = self.request("GET", "issues?state=all&per_page=100&page=" + str(page))
            if type(batch) is not list:
                raise CloudError("GitHub issues response invalid")
            yield from batch
            if len(batch) < 100:
                return
            page += 1

    def create_issue(self, payload):
        # An ineligible owner assignment is the only tolerated API rejection.
        result = self.request("POST", "issues", dict(payload, assignees=[self.owner]), assignment=True)
        if result is None:
            self.request("POST", "issues", payload)


def validate_workflow_url(value, kind):
    if not matches(r"https://github\.com/" + re.escape(REPOSITORIES[kind])
                   + r"/actions/runs/[0-9]+", value):
        raise ValueError("Invalid receiver workflow URL")


def load_json(path, limit):
    with open(path, "rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Input size limit exceeded")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--policy", required=True)
    args = parser.parse_args(argv)
    try:
        policy = validate_policy(load_json(args.policy, MAX_REPORT))
        event = load_json(args.event, 1048576)
        repository = REPOSITORIES[policy["kind"]]
        if (os.environ.get("GITHUB_REPOSITORY") != repository
                or event["repository"]["full_name"] != repository
                or event["repository"]["owner"]["login"] != "medking82"
                or os.environ.get("GITHUB_REF") != "refs/heads/main"):
            raise ValueError("Untrusted workflow context")
        workflow_url = "https://github.com/" + repository + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "")
        validate_workflow_url(workflow_url, policy["kind"])
        now = datetime.now(timezone.utc)
        mode = os.environ.get("GITHUB_EVENT_NAME")
        if mode == "repository_dispatch":
            if (event.get("action") != "codex-updater-receipt"
                    or event["sender"]["login"] != "medking82"
                    or os.environ.get("GITHUB_ACTOR") != "medking82"):
                raise ValueError("Untrusted dispatch actor")
            report = validate(event["client_payload"], policy)
            count = receive(GitHubAPI(repository), report, policy, now, workflow_url)
            counts = {"production": 0 if report["canary"] else count,
                      "canary": count if report["canary"] else 0}
        elif mode in {"schedule", "workflow_dispatch"}:
            if mode == "workflow_dispatch" and os.environ.get("GITHUB_ACTOR") != "medking82":
                raise ValueError("Untrusted watchdog actor")
            counts = watchdog(GitHubAPI(repository), policy, now, workflow_url)
        else:
            raise ValueError("Unsupported workflow event")
        summary = ("Updater Receipts: " + str(counts["production"]) + " Production Issue(s); "
                   + str(counts["canary"]) + " LIVE CANARY Issue(s).\n")
        print(summary, end="")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
                stream.write(summary)
        return 0
    except (CloudError, ValueError, KeyError, TypeError, OSError):
        print("Receipt receiver failed: validation, state, or GitHub API failure.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
