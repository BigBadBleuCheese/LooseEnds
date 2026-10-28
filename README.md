<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/header-dark.svg">
    <img alt="Loose Ends" src="docs/header-light.svg" width="100%">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/BigBadBleuCheese/LooseEnds/actions/workflows/build.yml"><img alt="Build" src="https://github.com/BigBadBleuCheese/LooseEnds/actions/workflows/build.yml/badge.svg"></a>
  <a href="https://github.com/BigBadBleuCheese/LooseEnds/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/BigBadBleuCheese/LooseEnds"></a>
  <a href="https://github.com/BigBadBleuCheese/LooseEnds/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/BigBadBleuCheese/LooseEnds/total"></a>
  <img alt="The Sims 4 1.129.39.1030" src="https://img.shields.io/badge/The%20Sims%204-1.129.39.1030-1A7F37">
  <img alt="Python 3.7" src="https://img.shields.io/badge/python-3.7-3776AB?logo=python&amp;logoColor=white">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/github/license/BigBadBleuCheese/LooseEnds"></a>
</p>

A script mod for The Sims 4 that fixes game state EA leaves dangling: loops that never back off, failures with no fallback, event listeners that are lost or never removed, and work the game repeats when the answer can't have changed. Each of these makes the game slower or makes Sims misbehave.

## What it fixes

| Fix | What you'll notice |
|---|---|
| Faster snippet lookups for pie menus | Pie menus open faster, especially with many mods installed. |
| Reuse Sim filter results while building a pie menu | The same. While one menu is being built, the game asks the same "who qualifies?" questions thousands of times; the answers are remembered for that menu. |
| Score pie menu entries without rescanning every moodlet | Pie menus open faster for Sims with many moodlets. Each menu entry used to be checked against every moodlet; now it's checked only against the moodlets that can change its score. |
| Find a Sim picker's candidate for its tests without the long lookup | Pie menus open faster. Interactions where you pick a Sim test every Sim in the game before they can be shown, and every test looked up the candidate the long way. |
| Check pie menu entries against dynasty rules without rebuilding every rule | Pie menus open faster for Sims in a dynasty. Every entry was checked against every dynasty rule by rebuilding that rule's list of interactions; now each list is built once. |
| Faster object tag checks for autonomy and interaction filters | Sims decide what to do faster, especially on busy lots and with mods that add interactions through traits. Checking whether an object has any tag from a list rebuilt the object's whole tag list once for every tag in that list; now it's one comparison. |
| Answer "every participant" lookups without checking every participant type | Busy lots (high schools especially) lag less. Every time the game tests an interaction for a Sim, it looks up all of the interaction's participants by checking more than 150 kinds of participant one at a time; now only the dozen that can apply are checked. |
| Phantom "too Tense/Uncomfortable" mood fix | Sims are no longer refused interactions as "far too Tense" or "far too Uncomfortable" while their mood is positive. |
| Autonomous Sim pickers skip Sims their follow-up can't run on | Pets stop trying to wake up Sims who aren't asleep, over and over. Sims stop repeatedly starting chats with Sims they can't actually talk to. |
| Autonomous chats that find nothing to say stop retrying the same Sim | Part of the chat fix above. |
| Visitors stuck trying to leave the lot are sent home | NPCs told to leave who can't start leaving (for example, while wearing a towel) no longer stand on your lot for hours. After several failed tries, they're sent home the way the game already does elsewhere. |
| Rabbit holes, roommates, clubs and relationships keep listening after you travel | After every trip, the game stopped listening for certain events (relationship and club changes, roommates dying, Sims being reset, and more) until you reloaded your save. Now they keep working. |
| Small business employees aren't penalized again for every past shift | Ended shifts no longer apply their end-of-shift results again when that employee is later sent home early. |
| Ended restaurant chef shifts stop reacting to Build mode and resets | Ended chef shifts are properly cleaned up. |

## Safe by design

Every time the game starts, Loose Ends checks that each piece of game code it touches is exactly the code it was built against.

- If a game update changed that code, or another mod rewrote it in a way Loose Ends can't safely build on, that fix stays off.
- If a fix ever runs into an error, it switches itself off for the rest of the session and the game carries on as if it weren't installed.
- Either way, the first time you enter Live mode that session, you get one notification saying which fixes are off and why. If everything is working, you see nothing.

## Installing

1. Download `CodeBleu-LooseEnds.ts4script` from [Releases](https://github.com/BigBadBleuCheese/LooseEnds/releases).
2. Put it in your `Mods` folder (script mods can be at most one folder deep inside `Mods`).
3. Make sure **Enable Custom Content and Mods** and **Script Mods Allowed** are on in Game Options → Other.

## Cheat console commands

Open the console with Ctrl+Shift+C. None of these need `testingcheats`.

| Command | What it does |
|---|---|
| `looseends.status` | Shows each fix's state and what it has done this session. |
| `looseends.disable <fix>` | Turns a fix off for this session. |
| `looseends.enable <fix>` | Turns it back on (never turns on a fix that failed its safety check). |
| `looseends.profile <sim id>` | Times building the active Sim's pie menu for that Sim and writes a profile to your Mods folder. |
| `looseends.anatomy <sim id>` | Builds the same pie menu and writes a report to your Mods folder of which interactions, tests and Sim pickers took the time. |
| `looseends.profile_autonomy <sim id> [runs]` | Runs that Sim's autonomy (without pushing anything) a few times, then once counted and once profiled, and writes a report to your Mods folder of where the time went. |
| `looseends.watch_lag [seconds] [ms]` | Watches every simulation tick until `looseends.watch_lag stop`, including across travel. When you start it, each time a lot finishes loading, and whenever a tick takes longer than `ms` (150 by default), it profiles the next `seconds` real seconds (60 by default, up to 8 captures) and writes a report to your Mods folder. |
| `looseends.count_participants [seconds]` | Counts every participant lookup the game makes for interactions over the next `seconds` real seconds (120 by default), by participant type and by what asked, with the time each took, and writes a report to your Mods folder. `looseends.count_participants stop` ends it early. |
| `looseends.profile_next_picker` | Profiles the next picker window you open (for example, the recipe picker). |
| `looseends.time_next_picker` | Times the next picker window from your click to the window being sent. |

Fix names for `disable`/`enable`: `ordered_types`, `pie_menu_filters`, `phantom_mood`, `autonomous_sim_pickers`, `content_scoring`, `picked_sim_lookup`, `all_participants`, `dynasty_rules`, `tag_checks`, `social_picker_cooldown`, `leave_lot`, `travel_event_subscriptions`, `small_business_employee_events`, `chef_events`.

## For modders

### Layout

| Path | Contents |
|---|---|
| `src/codebleu_loose_ends/` | The mod. `guard.py` (fingerprint checks, install and rollback, fault handling), `notify.py` (the Live mode notification), `commands.py`, and one module per fix in `fixes/`. |
| `testkit/` | A separate test-only mod with commands that force game states for in-game testing. The releases never ship it. |
| `tests/` | Unit tests. Most run the game's own compiled bytecode with stub globals (`tests/ea.py`), so they test EA's real code paths, not a reimplementation. |
| `tools/fp.py` | Prints the fingerprint of any game function: `python tools/fp.py module:Class.method`. |
| `tools/names.py` | Lists the names a game function refers to, which tells you what a test has to stub. |

### Requirements

Python **3.7** exactly. The game runs CPython 3.7, so the mod must be compiled by 3.7, and the tests can only read the game's 3.7 bytecode with 3.7. The build and test scripts refuse to run on any other version.

The tests and tools read the game's `simulation.zip`, `core.zip` and `base.zip` from `Data\Simulation\Gameplay` in the game's install folder. Common install locations are found automatically; otherwise set `LOOSE_ENDS_GAME_SCRIPTS` to that folder.

### Building and testing

```
python build.py            # build/CodeBleu-LooseEnds.ts4script
python build_testkit.py    # build/CodeBleu-LooseEnds-TestKit.ts4script
python run_tests.py        # each test module in its own process
```

### How the guard works

Each fix declares the game functions it wraps (`Hook`) and the game functions whose behavior it relies on (`Requirement`), each with a 64-bit FNV-1a fingerprint of the function's code object. A fix installs only if every fingerprint matches. Otherwise:

- If the mismatched code is EA's, the game changed and the fix stays off.
- If it's another mod's wrapper whose `functools.wraps` chain leads to the exact EA function, the fix stacks on top of it, unless the hook or requirement opts out with `stack_on_mods=False` (a fix that skips or bypasses that function would skip the other mod's wrapper too).
- Anything else is reported as a conflict with that mod.

Install is all-or-nothing per fix, with rollback. At run time, a fix's own exception switches it off and its wrappers pass straight through to the game's code.

Fingerprints are tied to a game version. When the game updates, run `tests/test_fingerprints.py`. Any function that changed has to be re-read before its fingerprint is updated, because the fix may no longer be correct.

### Adding a fix

1. Add `src/codebleu_loose_ends/fixes/<key>.py` with `FIX = Fix('<key>', '<player-facing title>', _build)`. `_build` imports the game modules and returns `([Hook, ...], [Requirement, ...])`.
2. Add the module to `FIX_MODULES` in `src/codebleu_loose_ends/__init__.py` and its counters to `commands.py`.
3. Add tests that run the game's own bytecode, and update the expected fix and status line counts in `tests/test_package.py`.
4. Wrap fix logic so any exception calls `FIX.fault(e)`. Nothing Loose Ends adds may raise on the game's call path.

## License

[MIT](LICENSE)
