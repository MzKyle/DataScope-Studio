# 3-Minute New User Usability Test

This protocol prepares a short first-run usability test for DataScope Studio. It is not a
claim that the targets have been met.

## Materials

- A DataScope Studio installer for the tester's platform.
- Fixture data: `tests/fixtures/sample_sensor.csv`.
- Screen recording or observer notes.
- A timer visible to the observer.

## Scenario

Give the tester only this prompt:

> Please try to use this software to view this robot data.

Do not explain Project, Mapping, Recording, Blueprint, RRD, RBL, Catalog, Recipe, or Plugin
concepts before the task. If the tester asks for help, record the timestamp and the exact
question before answering.

## Timeline

| Time | Observe | Notes |
| --- | --- | --- |
| 00:00 | App launched, first screen understood | |
| 00:30 | Tester finds the import/inspect entry point | |
| 01:00 | Data source selected or dropped | |
| 01:30 | Automatic inspection/mapping progress understood | |
| 02:00 | Preview or meaningful data summary visible | |
| 02:30 | Next action toward visualization understood | |
| 03:00 | Rerun opened or recording generation completed | |

## Observation Sheet

| Question | Yes/No | Evidence |
| --- | --- | --- |
| Did the app launch successfully? | | |
| Did the tester understand the first screen? | | |
| Did the tester know where to drop or choose data? | | |
| Was the tester blocked by Project terminology? | | |
| Was the tester blocked by Mapping terminology? | | |
| Did the tester understand the next step after import? | | |
| Did the tester see a data preview? | | |
| Did the tester open Rerun or generate a recording? | | |

## Time to First Value

Record the time from launching DataScope Studio to the first moment the tester sees meaningful
data, either in Preview or in a Rerun visualization.

Time to First Value: `____:____`

## Friction Log

| Event | Timestamp | Detail |
| --- | --- | --- |
| First hesitation | | |
| First incorrect click | | |
| First request for help | | |
| Term that was not understood | | |
| Button or control not discovered | | |
| Misunderstanding of final result | | |

## Acceptance Targets

These are targets for future observed tests, not pass/fail claims for this document.

- `<= 30 s`: find Quick Inspect.
- `<= 60 s`: complete data import.
- `<= 120 s`: see Preview.
- `<= 180 s`: enter Rerun or successfully generate a Recording.

## Session Summary

Tester ID:

Platform:

Installer version:

Fixture used:

Observer:

Date:

Outcome summary:

Follow-up changes suggested:
