# Glossary

| Term | Meaning |
|---|---|
| **Production** | One run that turns a moodboard file and a prompts file into finished References, Stills and Animations, with review, in one Flow project. |
| **Item** | One row in a Production: a Reference, a Still or an Animation. It has a state (queued, running, review, approved, failed) and Takes. |
| **Take** | One generated attempt for an Item. Modify or Retry makes a new Take; earlier Takes stay on disk. |
| **Reference** | A Character or Place image made first (ids like `CH_...`, `MD_...`) so later shots stay consistent. |
| **Still** | A single image shot (ids `IMG_`, `STILL_`, `SHOT_`). |
| **Animation** | A video shot (ids `ANI_`, `ANIM_`, `VID_`), usually from a Still as its start frame. Costs more credits than a Still. |
| **Run** | One execution of a batch or Production, with a `run_id` and a run folder. Can be paused, resumed, cancelled. |
| **Engine** | The local process that owns Chrome, the queue, the ledger and the files. Agents and the app are its clients. |
| **Ledger** | The engine's on-disk record of credits quoted, submitted and spent. Source of truth for "did this cost credits". |
| **Gate** | A point where work stops until something is true: the credit cap (`max_credits`), a quote check, the daily cap, or a person (CAPTCHA, verification). |
