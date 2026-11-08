# The Control Roster — Azure Access Automation

**Start with [LAB.md](LAB.md).** The walkthrough is designed for a team of four and a 90–120 minute mentorship meeting.

## Clone the starter repository into VS Code

Before the workshop, the mentor should commit the files in this starter pack to the repository; otherwise cloning a README-only repository will not include the lab scripts. Each student then runs:

```bash
git clone https://github.com/akneewhowah/FirstAzureProject-ControlRoster.git
cd FirstAzureProject-ControlRoster
code .
```

If the code is not yet on GitHub, you can run it directly from this extracted ZIP folder first.

## Run it in 30 seconds (no Azure account needed)

```bash
python roster.py validate
python -m unittest discover -s tests -v
python roster.py plan                 # default: safe demo mode
```

To see a real simulated onboarding/offboarding, follow LAB.md and edit `roster.json` with the included sample UUIDs. Then use `python roster.py apply` and inspect `.demo-state.json`.

## Commands

| Command | Meaning |
|---|---|
| `python roster.py validate` | Check JSON format, duplicate IDs and head membership |
| `python roster.py plan` | Preview changes in the **local demo** |
| `python roster.py apply` | Apply changes only to `.demo-state.json` |
| `python roster.py plan --mode azure` | Preview actual Reader RBAC changes in Azure |
| `python roster.py apply --mode azure` | Create/delete only project-owned Reader assignments in Azure |

### Security and scope

- The program manages **only the Reader role at configured resource group scopes**, not subscription-wide access.
- It removes **only assignments it created**, identified by deterministic UUIDs. Unrelated role assignments are never removed.
- Removing this project's Reader assignment does **not** remove other inherited/existing privileges or delete identity objects or access keys.
- The head field is documentation only in v1. A lead receives Reader just like members.
- Do **not** commit access keys, service principal passwords, `.env` credentials or sensitive employee data.
- Only use real Microsoft Entra user **object IDs from the same tenant** when running in Azure mode.
- Resource groups have no deployment fee; adding storage or databases later may incur costs.

## Files

```text
roster.json                         Desired department membership
settings.json                       Mapping from department to Azure resource group
roster.py                           Validation and reconciliation engine
.github/workflows/control-roster.yml  Tests + optional Azure OIDC deployment
tests/test_roster.py                 Six unit tests
LAB.md                               Participant walkthrough
MENTOR_NOTES.md                      Facilitator checklist and resume rubric
```
