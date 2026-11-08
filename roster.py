#!/usr/bin/env python3
"""Control Roster: reconcile project-owned Azure RBAC Reader assignments.

Only assignments with a deterministic project-owned GUID are ever removed.
Demo mode simulates Azure assignments without Azure credentials.
"""
import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEMO_SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"


def load_json(path):
    with Path(path).open(encoding="utf-8") as file:
        return json.load(file)


def validate(roster, config):
    if not isinstance(config, dict) or not isinstance(config.get("resource_groups"), dict):
        raise ValueError("settings.json must contain a resource_groups object")
    groups = config["resource_groups"]
    if not groups or set(groups) != set(roster):
        raise ValueError("Department names must match in roster.json and settings.json")
    if len(set(groups.values())) != len(groups):
        raise ValueError("Each department must have a different resource group")
    seen = set()
    normalized = {}
    for dept, entry in roster.items():
        rg = groups[dept]
        if not isinstance(rg, str) or not rg.startswith("rg-controlroster-"):
            raise ValueError(f"{dept}: use a resource group named rg-controlroster-...")
        if not isinstance(entry, dict) or set(entry) != {"head", "members"}:
            raise ValueError(f"{dept}: expected exactly 'head' and 'members'")
        members = entry["members"]
        if not isinstance(members, list):
            raise ValueError(f"{dept}.members must be a list")
        valid_members = []
        for member in members:
            if not isinstance(member, str):
                raise ValueError(f"{dept}: object IDs must be UUID strings")
            try:
                user_id = str(uuid.UUID(member))
            except (ValueError, AttributeError):
                raise ValueError(f"{dept}: '{member}' is not an Entra object ID (UUID)")
            if user_id == "00000000-0000-0000-0000-000000000000":
                raise ValueError(f"{dept}: all-zero UUID is not allowed")
            if user_id in seen:
                raise ValueError(f"Duplicate user ID across roster: {user_id}")
            seen.add(user_id)
            valid_members.append(user_id)
        head = entry["head"]
        if head is not None and head != "":
            if not isinstance(head, str):
                raise ValueError(f"{dept}: head must be an object ID or empty")
            try:
                head = str(uuid.UUID(head))
            except ValueError:
                raise ValueError(f"{dept}: head must be an object ID or empty")
            if head not in valid_members:
                raise ValueError(f"{dept}: head must also appear in members")
        normalized[dept] = valid_members
    return normalized


def run_az(*args):
    cmd = ["az", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Azure CLI failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def assignment_name(scope, principal_id):
    """Same principal + scope always receives the same project-specific UUID."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"control-roster:reader:v1:{scope.lower()}:{principal_id.lower()}"))


def assignment_id(scope, name):
    return f"{scope}/providers/Microsoft.Authorization/roleAssignments/{name}"


def read_scopes(config, mode):
    if mode == "demo":
        return {d: f"/subscriptions/{DEMO_SUBSCRIPTION}/resourceGroups/{rg}"
                for d, rg in config["resource_groups"].items()}
    scopes = {}
    for dept, rg in config["resource_groups"].items():
        # Fails early if the group does not exist or isn't visible to Azure CLI.
        scopes[dept] = run_az("group", "show", "--name", rg, "--query", "id", "-o", "tsv")
    return scopes


def read_current(scopes, mode, demo_state):
    if mode == "demo":
        records = load_json(demo_state) if Path(demo_state).exists() else []
        if not isinstance(records, list):
            raise ValueError("Demo state must be a JSON list")
        return {dept: [a for a in records if a.get("scope", "").lower() == scope.lower()]
                for dept, scope in scopes.items()}
    current = {}
    for dept, scope in scopes.items():
        raw = run_az("role", "assignment", "list", "--scope", scope, "--role", "Reader",
                     "--fill-principal-name", "false", "-o", "json")
        current[dept] = json.loads(raw)
    return current


def make_plan(normalized, scopes, current):
    """Returns (add, remove); deletions apply ONLY to exact project-owned GUIDs."""
    adds, removes = [], []
    for dept, users in normalized.items():
        scope = scopes[dept]
        desired = set(users)
        existing_users = {str(a["principalId"]).lower() for a in current[dept]}
        for user_id in sorted(desired - existing_users):
            adds.append({"department": dept, "scope": scope, "principalId": user_id,
                         "name": assignment_name(scope, user_id)})
        for assignment in current[dept]:
            principal = str(assignment["principalId"]).lower()
            if (principal not in desired
                    and str(assignment.get("name", "")).lower() == assignment_name(scope, principal)):
                removes.append({"department": dept, "scope": scope, "principalId": principal,
                                "name": assignment["name"], "id": assignment["id"]})
    return adds, removes


def make_demo_record(action):
    return {"department": action["department"], "scope": action["scope"],
            "principalId": action["principalId"], "name": action["name"],
            "id": assignment_id(action["scope"], action["name"]),
            "roleDefinitionName": "Reader", "principalType": "User"}


def apply(adds, removes, mode, demo_state):
    if mode == "demo":
        records = load_json(demo_state) if Path(demo_state).exists() else []
        removed_ids = {x["id"] for x in removes}
        records = [x for x in records if x["id"] not in removed_ids]
        records.extend(make_demo_record(x) for x in adds)
        Path(demo_state).write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        print(f"Updated simulated Azure state: {demo_state}")
        return
    for a in adds:
        print(f"GRANT Reader {a['principalId']} on {a['department']}", flush=True)
        run_az("role", "assignment", "create", "--name", a["name"],
               "--assignee-object-id", a["principalId"],
               "--assignee-principal-type", "User", "--role", "Reader",
               "--scope", a["scope"], "-o", "none")
    for a in removes:
        print(f"REVOKE project-managed Reader {a['principalId']} on {a['department']}", flush=True)
        run_az("role", "assignment", "delete", "--ids", a["id"], "-o", "none")


def main():
    parser = argparse.ArgumentParser(description="Validate / plan / apply control roster changes")
    parser.add_argument("action", choices=["validate", "plan", "apply"])
    parser.add_argument("--mode", choices=["demo", "azure"], default="demo")
    parser.add_argument("--demo-state", default=str(ROOT / ".demo-state.json"))
    args = parser.parse_args()
    try:
        roster, config = load_json(ROOT / "roster.json"), load_json(ROOT / "settings.json")
        normalized = validate(roster, config)
        print(f"Valid roster: {len(normalized)} departments, {sum(len(x) for x in normalized.values())} members")
        if args.action == "validate":
            return 0
        scopes = read_scopes(config, args.mode)
        current = read_current(scopes, args.mode, args.demo_state)
        adds, removes = make_plan(normalized, scopes, current)
        for x in adds:
            print(f"+ GRANT Reader | {x['department']:12} | {x['principalId']}")
        for x in removes:
            print(f"- REVOKE Reader | {x['department']:12} | {x['principalId']} (project-owned)")
        if not adds and not removes:
            print("No changes: Azure already matches the managed portion of the roster.")
        if args.action == "apply":
            apply(adds, removes, args.mode, args.demo_state)
        return 0
    except (ValueError, FileNotFoundError, json.JSONDecodeError, RuntimeError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
