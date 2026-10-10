# RERUN — video shot list (at most three minutes)

The owner records and narrates. Every screen is the keyless demo or a committed file: **the app replays recorded runs; nothing runs live and no key is used.** Say so on screen: the scene pages carry the label REPLAY, and the first caption reads "Replay of recorded runs, no live call". Nothing in the video is simulated; if a shot ever shows something that is not a recorded run, caption it "simulated".

## Before recording

- In a clone of the commit you submit, start the demo and leave it running:

   ```bash
   python demo.py
   ```

- Open the address it prints. Use one browser window at one zoom level, with a second tab on the repository's README on GitHub.
- Keep a terminal open in the clone for the last shot (verifying a certificate offline). Download one certificate beforehand if the network is slow: on the latent_ode certificate page, **Download certificate JSON**.
- Do not type or edit any number on screen; every figure shown comes from the app, the README or a committed record.

## Shots

| Time | Beat | Screen and action | Caption on screen | Spoken (suggested) |
|---|---|---|---|---|
| 0:00–0:15 | Problem | README on GitHub, the first lines of "The result" | Replay of recorded runs, no live call | A paper ships with its code. Later, someone runs it, and it does not run. Nobody can tell whether it ever ran, or why it stops. |
| 0:15–0:30 | Input | The demo's home page: paste `https://github.com/YuliaRubanova/latent_ode`, submit; intake clones it at its pinned commit and names the documented command. **Start execution run** stays disabled (demo mode) | Input: a repository and its documented command | RERUN takes a repository at a pinned commit and the command its README documents. |
| 0:30–0:55 | Sandbox run | Gallery, open the **latent_ode** scene (REPLAY), then its run timeline: the baseline operation in the Nebius Token Factory sandbox, its sandbox id and exit code | Nebius Token Factory sandbox, as recorded | It runs that command in a Nebius Token Factory sandbox, in the environment of the paper's era, and keeps every log. |
| 0:55–1:15 | Failure classified | Same timeline: the classifier line and the error chain; then the certificate's error chain | Deterministic classification, no model call | The failure is classified by fixed rules, not by a model: what stopped the run, quoted from its own output. |
| 1:15–1:40 | Repair | Same scene: the first round of candidates proposed by Nemotron Super, the Tavily references stored on the attempt, the adjudicator's choice by Nemotron Ultra, the environment change it adopted, and the run after it | Nemotron Super proposes, Nemotron Ultra adjudicates, every change gate-checked | Then Nemotron models propose environment changes. Each one passes a tamper gate and runs in its own branch of the sandbox image; Ultra picks one only if the run gets further. |
| 1:40–2:00 | Tamper gate | Gallery, open the **spline-calibration** scene (REPLAY): candidates that reached a zero exit by skipping the missing inputs, none adopted; show the scene's note | A zero exit is not a reproduction | A run that ends with exit zero can still be fake: here candidates skipped the missing inputs. None was adopted, and the scene says which layer refused them. |
| 2:00–2:20 | Certificate | The latent_ode certificate page: verdict label, outcome ladder, blocker; **Download certificate JSON**; then the terminal | Every certificate verifies offline | Each run ends in a certificate with its evidence. It verifies offline, with no network and no key. |
| 2:20–2:45 | Result table | The Batch Lab page: the held-out counts, the diagnosis with its strict figure, then the README's "What weakens these claims" lines | The result, and what weakens it | Read the counts as they are on screen. Then the limits: anti-cheat is not a headline claim, and REVIEW REQUIRED asks a human to look; it does not detect cheats. |
| 2:45–3:00 | Close | README: the try-it line and the licence | Apache licence. One command, no key: `python demo.py` | Every number traces to a committed record, and one command replays it all without a key. |

Command for the certificate shot (the file name is the one you downloaded):

```bash
python scripts/verify_passport.py <downloaded certificate file>
```

## What the audio must name

The hackathon asks for Nebius Token Factory and NVIDIA in the audio: the sandbox shot names Nebius Token Factory, and the repair shot names the Nemotron models (Nano for recon is on the stack page if time allows).

## Not shown, and why

- **A live run.** The hosted demo is keyless and refuses live execution; a live run spends money and needs keys the video must not show.
- **A REVIEW_REQUIRED certificate in the app.** The demo seeds the recorded runs of the earlier sets; the live flag-mode runs are under `runs/v1.10/` and the app does not replay them. If you show one, show the committed record file and caption it as a record, not as the app.
