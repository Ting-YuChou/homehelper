# home_helper_dataset.jsonl review (2026-10-21)

Ten reviewers, one per category, each read every variant and spot-checked it against the parsed manual. Partly acted on (2026-10-23): non-answer root causes are skipped, escalation is accepted for overheat, arcing and injury scenarios, and simulated users name the manifest brand. The per-variant fixes below are still open.


---

## Findings: Blender-FoodProcessor

- Variants reviewed: 100 (300 rows, ids 2401-2700, 10 manuals x 10 variants, 3 tones each)
- OK: 77
- Needs fix: 19 (10 fix, 9 minor)
- Should drop (or replace): 4

Metadata is consistent for all 300 rows: product_name is always `Blender-FoodProcessor`, company matches the manual and manifest, no duplicate-PDF names. (`BlackDecker` vs manifest `Black+Decker` is cosmetic only.) Every variant has all three tones. The `conversation` field looks fine in the sample I read.

## Problematic variants

| rows | issue type | severity | what is wrong | suggested change |
|---|---|---|---|---|
| 2401-2403 | steps non-answer | drop | solution_steps is only "the manual does not provide specific steps". The manual has nothing on a loose lid insert (it gives the part number BI2010WG-01; the scenario misspells it as "Bl2010WG-01"). The `user_fixable=False` label is a guess. | Drop. Or rewrite the scenario as "Blender splashes out the top while running" with steps from p6/p7 ("Place lid on jar; make sure lid cap is in place"; "Blender should always have lid in place"), root = lid step, user_fixable=True. |
| 2428-2430 | steps non-answer + unsolvable label | drop | The steps are a non-answer, yet the label is `user_fixable=True, root_cause_step=1`. The simulator would wait for the agent to propose "the manual does not provide steps", so the task cannot be solved. The BL2010 manual has no overheat or motor-stop content. | Drop. Or replace with the p7 tip: scenario "Food splatters onto the jar sides / thick mixture stops moving around the blades", steps = OFF, remove lid, scrape down with a rubber spatula, push food toward the blades, replace lid; root = scrape step. |
| 2413-2415 | wrong root step | fix | The scenario is about the lid not sealing and splashing from the top. The label points to step 5 (gasket on the blade assembly), but that gasket seals the jar bottom, not the lid. | root_cause_step=7 ("Place lid with lid cap onto blending jar"). |
| 2437-2439 | hazard signal vs label; misattributed step | fix | The scenario contains "burning smell", so the expected outcome should be escalated, but the label says `user_fixable=True, root=2`. Step 2 ("turn OFF, stand 3 to 4 minutes") actually comes from the manual's "Unit does not operate" row (p11), not the burning-smell row. The manual's burning-smell answer is: slight odor from manufacturing residue during initial use is normal; for a strong odor or smoke, unplug immediately and call Customer Service. | Keep the hazard: user_fixable=False, root_cause_step=1. Remove step 2 or replace it with the residue note. Alternative: rewrite the scenario as "slight odor during the first few uses of a new unit" and mark it troubleshootable=False (normal behavior). |
| 2449-2451 | vague scenario | fix | "The outlet may not work, affecting the appliance's operation." This is a hypothesis, not a symptom, and it gives away the cause. | "The food processor is completely dead; a lamp plugged into the same outlet doesn't work either." Keep root=2 (fuse or breaker). |
| 2491-2493 | tautological / unsolvable | fix | Scenario: the rotary knob does not wake the unit. The root (step 2) is "press the rotary knob to wake it", which is exactly what the user already did. A real agent would never "fix" it this way. | root_cause_step=4 (check plug / outlet). Or drop, because the manual has no troubleshooting for this. |
| 2494-2496 | steps non-answer + unsolvable label | drop | The steps are only "the manual does not provide steps", yet the label is user_fixable=True, root=1. The manual only describes press-and-hold for 2 s (p4). | Drop, or set user_fixable=False (expected escalated). |
| 2503-2505 | steps unrelated | drop | Scenario: tumbler seal ring does not fit and leaks. The steps are generic tips (clean before first use, blunt blades, overfill, carbonated drinks, wash). None covers fitting the seal ring. Root=5 ("wash in water") would not fix a mis-fitted seal. I found no seal-ring fitting or troubleshooting text in the parsed Philips manual. | Drop. Or, if the assembly figure text can be recovered, use "fit the tumbler seal ring onto the blade unit before attaching" as the single root step. |
| 2515-2517 | spec note as symptom | fix (minor) | "Beyond the 83 dB(A) level" comes from the noise spec line. No user measures dB, and the number makes the query match spec text. | "The blender is much louder than usual and rattles while running." Keep root=6 (lid/measuring cup not assembled properly). |
| 2518-2520 | warning, not symptom | fix | "Thermal cut-out resets inadvertently" restates the safety warning about not using a timer or switched circuit. No user would observe or report this. | troubleshootable=False. Or rewrite: "The blender keeps cutting out and restarting on its own; it's plugged into a timer socket." root=1. |
| 2572-2574 | implausible symptom | fix (minor) | Users can't tell an outlet is ungrounded, and the 3-prong plug wouldn't go into one without an adapter. | "Blender won't turn on; it's plugged in through an adapter / extension cord." root_cause_step=4. |
| 2620-2622 | garbled steps / vague scenario | fix (minor) | The scenario says only "causing malfunction". The steps mix removal steps (unlock bowl, remove Shredding Disc) with assembly steps. | Scenario: "Processor won't start after I put the blade in first and then the bowl." Steps: container on base, then blade, then lock cover. root=5. |
| 2656-2658 | warning, not symptom | fix | This restates the WARNING (p5) "to avoid possible malfunction of the auto switch, do not leave the lid locked when not in use". It is not an observable symptom. | troubleshootable=False. Or replace with a real p21 troubleshooting row, e.g. "The motor does not start" (interlock: bowl/lid locked, large pusher low enough to engage the switch). |
| 2659-2661 | usage tip + wrong root | fix | "Ingredients need to be processed in batches" is advice, not a symptom. The root (step 6, small feed chute for *smaller* quantities) contradicts the overloading premise. | troubleshootable=False. Or rewrite: "The motor slowed down during operation with a full bowl" (p21), root = "remove some ingredients / process in batches" (step 1). |
| 2443 / 2458 | near-duplicate (same manual) | minor | Both cover irregular slicing/shredding from overpacking or pushing too hard (Hamilton Beach), with the same root. | Drop 2458, or change it to the disc side ("shreds instead of slices"), root = disc orientation step 4. |
| 2551 / 2557 | near-duplicate (same manual) | minor | Both cover overheating from low speed on the Vitamix (use High speed). 2557's wording ("motor fails to cool properly") is a spec-style restatement. | Drop 2557. |
| 2560 / 2563 | near-duplicate (same manual) | minor | Both cover the trapped air bubble and the tamper on the Vitamix. | Drop 2563, or keep only one. |
| 2611 / 2638 (and 2623) | near-duplicate (same manual) | minor | There are three Oster "won't run because bowl/cover not locked" variants. 2611 and 2638 share the same steps. | Drop 2638 (2623, the unresponsive knob, can stay). |
| 2488 / 2647, 2476 / 2650, 2485 / 2641 | cross-manual duplicates | minor | Cuisinart FP-14 and Breville BFP800 have word-identical troubleshooting rows (slanted slices, food falls over in the feed tube/chute, unevenly processed). Retrieval with only the scenario text can't tell the gold manual apart. | Keep only if the retrieval eval filters by brand/model. Otherwise add model cues ("Breville Kitchen Wizz", "2.5cm", "feed chute") or drop one side of each pair. |
| 2497-2499 | near-tautological | minor | The scenario says the program "cannot be confirmed", and root = "press the knob to confirm". It is solvable only if the user didn't know about the press. | Rephrase: "I turn the knob to a program but nothing starts." |
| 2599-2601 | scenario gives away the cause | minor | "Does not turn on because the power button is not pressed" states the answer. The same pattern appears in 2452 and 2605/2608. | "Ninja doesn't start; the container and lid are on and it's plugged in." Keep root=3. |

## Category-wide patterns

1. **Kenwood (2521-2548): all 10 variants are safety warnings** (scald, children, sharp blades, liability, usage times). All are correctly labeled troubleshootable=False, so Kenwood contributes zero simulation cases. Its retrieval queries are generic warning text that matches almost any manual. The manual has an unused Troubleshooting Guide on p20. Suggested replacements:
   - processor won't operate (drive shaft not fitted, or bowl/lid interlock)
   - blender or mill won't operate (blade assembly not fully tightened)
   - processor stops mid-process (over capacity, or lid unlocked)
   - Blend-Xtract / mill leaking from the blade base (seal)
   - heavy vibration with sticky ingredients (Pulse first, then max speed)
2. **Non-answer solution_steps** ("I'm sorry, the manual does not provide...") appear in 2401, 2428 and 2494. In two of them they are combined with `user_fixable=True, root=1`, which makes the task unsolvable. Filter globally: any variant whose only step is a non-answer should be dropped or forced to user_fixable=False.
3. **Warning/spec text as scenarios** beyond Kenwood: 2455, 2512, 2569, 2575, 2578, 2632, 2635, 2665, 2668 are correctly troubleshootable=False. 2518 and 2656 are not and need the same treatment.
4. **Scenarios that state the cause** ("...because X is not locked", "...due to overloading") are common, especially for Oster, Ninja and Hamilton Beach. They are solvable but easy. This is acceptable, but worth a pass if harder cases are wanted.
5. **Unused real troubleshooting tables**: Breville p20-21 (motor doesn't start, vibrates, INSERT PUSHER flashing) and Kenwood p20 are richer than several of the chosen scenarios. They are the best source for replacing the dropped or warning variants.

---

## CoffeeMaker — review findings

- Variants reviewed: 100 (300 rows, 10 manuals x 10 variants, 3 tones each; all three tones present everywhere)
- OK: 63 (16 of these have minor notes, listed at the bottom)
- Needs fix: 23
- Should drop: 14

Checked against the parsed manuals (troubleshooting tables, Q&A, safeguards) of all 10 manuals.
`root_cause_step` indexes the *flattened* step lines (sub-bullets and headers count as steps), confirmed via `root_cause_text` in `root_cause_steps.v1.json`.

## Should drop (14)

| rows | issue type | severity | what is wrong | suggested change |
|---|---|---|---|---|
| 343-345 | non-answer steps | drop | Cuisinart SS-16 "ready tone does not signal". Steps = "the manual does not provide..."; manual only lists the tone as a feature. Unsolvable (root = apology text). | Drop. |
| 346-348 | non-answer steps | drop | SS-16 "power loss backup fails to retain programming". Steps = "I don't know." Manual only describes the feature. | Drop. |
| 361-363 | fabricated / no manual support | drop | DCC-1170 "audible tone does not sound". Steps restate the feature spec; step 5 admits no troubleshooting exists. Root "verify brew completed" is a guess. | Drop. |
| 364-366 | non-answer steps | drop | DCC-1170 "does not respond to Power Button". Single non-answer step, labelled user_fixable=false, so "escalated" is expected for a no-power symptom with nothing in the steps. | Drop (or rebuild steps: check plug, Function knob position, then service). |
| 376-378 | vague / spec text | drop | DCC-1170 "Function knob does not work in tandem with the Power Button" comes from the control-panel description, not a symptom. Steps are filler. | Drop. |
| 433-435 | non-answer steps | drop | Mr. Coffee Iced+Hot "showerhead clogged". Steps = "I don't know..."; the manual only names the part. | Drop. |
| 517-519 | root does not fix anything | drop | LM Series "reservoir appears empty despite adding water". Root = "Check the water windows", which is a diagnostic, not a fix. The manual's row says "reservoir is empty -> check the water windows" (the user really has no water). Contradictory symptom. | Drop. |
| 544-546 | non-answer steps | drop | HotCup "serving size knob not selecting size". Steps = "I don't know." | Drop. |
| 550-552 | non-answer, not a malfunction | drop | HotCup "coffee scoop missing". Steps = "I don't know." | Drop. |
| 553-555 | non-answer / safeguard text | drop | HotCup "hot glass container cracks". Steps are an apology; HotCup has no glass carafe (generic safeguard text). | Drop. |
| 580-582 | fabricated steps | drop | MyJo "red reservoir grip loose". Manual has nothing on this; steps 2-5 are invented, and the root is "contact manufacturer". | Drop. |
| 589-591 | safety warning | drop | MyJo "surfaces too hot to touch". MyJo is non-electric and you pour hot water into it, so hot surfaces are expected. Root "do not use if it malfunctions" is wrong. | Drop (or troubleshootable=false). |
| 592-594 | impossible scenario | drop | MyJo "does not power on despite being plugged in". MyJo is a manual pump brewer with no cord, and the steps say so. | Drop. |
| 598-600 | vague, wrong premise | drop | MyJo "stops working after a short period of use". Non-electric device; the rationale's "thermal cutoff" does not exist. Steps = read instructions / call Presto. | Drop. |

## Needs fix (23)

| rows | issue type | severity | what is wrong | suggested change |
|---|---|---|---|---|
| 301-303 | label | fix | Braun. root_cause_text = "Press and hold SET to scroll... hour" (flattened sub-bullet 4). The same line also appears under AUTO ON, and an agent will say "set the clock" instead. Near-duplicate of 307. | root_cause_step=3 ("Press the CLOCK button (d) for a minimum of 3 seconds..."), or rewrite scenario: "The AUTO ON button doesn't let me program a start time." |
| 331-333 | ambiguous root | fix | SS-16 "does not brew even when powered on and water is in the reservoir". Steps 1 (unplug 1 min), 3 (reservoir seated), 4 (brew head closed) are equally plausible, so the root is a coin flip. Rows 349 already cover the brew head. | Add a discriminating detail: "...water is in the reservoir, but the removable reservoir wobbles a little when I touch it." Keep root=3. |
| 337-339 | scenario contradicts manual | fix | SS-16: the manual's energy-save mode sleeps after 30 min of **non-use**; the scenario says it "turns off during brewing". | "The machine turned itself off after sitting idle for a while and the display went dark." |
| 370-372 | spec note as symptom | fix | DCC-1170 "fails to operate in a 120-volt outlet" is spec text. Root = reverse polarized plug, which only applies when the plug won't fit. | Scenario: "The plug won't go all the way into my wall outlet." Keep root=2. |
| 385-387 | label inconsistent | fix | DCC-1170 "liquid contacted cord/base, shock risk" labelled troubleshootable=false, root=1 ("do not place in water"). The same situation in SS-16 (352) is troubleshootable=true, escalated. It is a hazard. | troubleshootable=true, user_fixable=false, root_cause_step=3 (return to Cuisinart Repair Center). Rewrite: "I spilled water on the base and cord of my coffeemaker." |
| 406-408 | safety warning as symptom | fix | Krups "keep warm makes heating plate/carafe bottom too hot to touch" is expected behaviour from the safeguards. | troubleshootable=false. |
| 412-414 | label + scenario states the fix | fix | Krups "A power surge requires unplug/replug". Root=2 "wait a few moments" was invented (not in manual). The manual's fix is unplug, then plug back in. Overlaps 391. | Scenario: "After a power surge the coffee maker won't respond to any button." root_cause_step=1 (unplug; or merge 1+3 into one step "Unplug the machine, then plug it back in"). |
| 436-438 | usage tip | fix | Iced+Hot "reservoir markings unclear" is a usage note; root "observe water ladder" is not a fix. | troubleshootable=false (or drop). |
| 472-474 | safety tip | fix | KNX "power cord hangs over counter edge" comes from the safeguards/cord-storage feature, not a malfunction. | troubleshootable=false. |
| 487-489 | wrong steps | fix | Express Cold Brew "unit stops prematurely, does not complete brewing". The manual's row: "Unit stopped during brewing -> Low battery level -> recharge". The steps (blow, grounds, O-ring) come from other rows; root=O-ring is wrong. Step 4 is also truncated. | solution_steps = the charging steps (connect cord to USB port, then to a 5VDC USB outlet, charge ~2 h, LED solid white when full). root = "Connect the other end... to a USB outlet". |
| 493-495 | expected behaviour | fix | Cold Brew "Solid red LED while charging = charging active" is the LED legend, i.e. normal behaviour. | troubleshootable=false. |
| 496-498 | cause/symptom mismatch | fix | Cold Brew: the manual lists "grounds saturated prior to use" as a cause of **overflow**, not poor taste. | "My cold brew unit overflows during use; I'm using grounds that were already damp." root=1. |
| 499-501 | cause/symptom mismatch | fix | Cold Brew: "not enough grounds" is listed as a cause of **overflow**, not weak coffee. | "The unit overflows during brewing even though I stayed under the water and ice fill lines; I only used a small amount of coffee." root=1. |
| 514-516 | ambiguous root + contradiction | fix | LM "not brewing even when power is restored". Four causes; root=4 (decanter) is a guess, and step 1 (plug in) contradicts "power restored". | Add a hint: "...power is on and there's water in the reservoir, but nothing starts; the carafe might not be pushed all the way in." Keep root=4. |
| 532-534 | label | fix | LM "power cord or plug got damaged from hot surfaces". Once the cord is damaged, the manual's fix is service; root=2 (keep cord away) is prevention only. | user_fixable=false, root_cause_step=1 (return to Authorized Service Center). |
| 556-558 | safety warning | fix | HotCup "container handle loose" is safeguard text; "do not use" does not resolve it. | troubleshootable=false. |
| 559-561 | label | fix | HotCup "does not turn on when plugged in". Labelled escalated via root=3 (service), but step 1 (plug seated correctly) is the first user fix, and the scenario mentions no damage. | Either root=1, user_fixable=true, or keep escalated and add "the cord looks damaged" to the scenario (which then duplicates 562). Prefer root=1. |
| 565-567 | safety warning | fix | HotCup "placed on a hot surface, affecting performance" is a placement safeguard. | troubleshootable=false. |
| 571-573 | label + fabricated steps | fix | MyJo "MyJo Cup not fitting the pack holder". Steps 2-5 are invented. The manual only says to use the MyJo Cup and no other brand. Root=3 (debris) is speculative. Also needs the metadata fix below. | "My refillable filter cup doesn't fit in the pack holder." root_cause_step=1 (use the MyJo Cup only). |
| 574-576 | label | fix | MyJo "hot water leaks from reservoir while brewing". Manual Q&A: "seeping between base and reservoir -> base not screwed on tightly". That is step 3; the label says step 4 (pump). | Scenario: "Water seeps out between the base and the reservoir while I brew." root_cause_step=3. |
| 583-585 | label | fix | MyJo "valve does not open". Manual Q&A: the slit can reseal; the fix is "Pinch the valve and rotate it until the slit opens" (step 2). The label says wash (step 3). | Scenario: "When I press down on the pump nothing comes out." root_cause_step=2. |
| 586-588 | not a malfunction | fix | MyJo "difficulty ordering the MyJo Cup" is a purchasing question. Labelled user_fixable=false, so it would expect "escalated". | troubleshootable=false. |
| 577-579, 595-597 | metadata | fix | MyJo rows: company_name "MyJo" is the product line. The manual is PRESTO (National Presto Industries); the manifest also says brand "MyJo". Applies to all 10 MyJo variants (the others are already listed above). | company_name="Presto"; manifest brand "Presto", product "Presto MyJo Single Cup Coffee Maker". |

## Category-wide patterns

1. **Non-answer steps (8 variants).** Steps like "I don't know." / "the manual does not provide..." (343, 346, 364, 433, 544, 550, 553, 592). They are labelled troubleshootable=true with root=1, so the simulated user can never be "fixed". Filter mechanically: drop any variant whose only step matches `I don't know|does not (provide|contain)|I'm sorry|I apologize`.
2. **Safety warnings labelled troubleshootable=true.** About 10 variants (406, 472, 493, 556, 565, 586, 589, 436...). Many similar rows are already correctly false (382, 415, 418, 475, 508, 535), so labelling is inconsistent. One case of the reverse: 385 (a real hazard) is false, while its twin 352 is true.
3. **Scenario states the cause/fix.** Many scenarios embed the answer ("...because the filter basket is not properly inserted", "...due to the decanter lid not being on", "...requires the machine to be unplugged"): KNX 451-466, LM 520-523, SS-16 349, Krups 394/412, Braun 307/310/322. The tasks are trivially solvable, but they are not wrong. Consider symptom-only rewrites for the conversation sim (e.g. 457 -> "Coffee overflows out of the filter basket.").
4. **Cross-manual retrieval ambiguity.** Mr. Coffee KNX and LM Series have near-identical troubleshooting tables, and the scenarios mirror them (511 vs the KNX "Brew Now light"; 520/523 vs 466/KNX decanter; 526 vs 451/463). The Braun table also shares "coffee is not hot / only brewing water". Retrieval Recall@5 per gold manual will be noisy for these; consider accepting either Mr. Coffee manual as gold for the shared rows, or adding model-specific wording.
5. **MyJo manual is a non-electric pump brewer.** Any electrical symptom (power, stops working, overheating) is invalid for it. Company metadata is wrong (Presto).
6. **Express Cold Brew steps reuse the same 4-line block** for different symptoms (484 and 487 are identical, with step 4 truncated "fully tighten the.").
7. Metadata minor: Braun manual file is `KF7070SI` while the manifest id is `braun-kf6050` (the manual covers KF6050/7000/7030/7070, so this is acceptable); company "BraunHousehold" vs manifest "Braun"; "Mr.Coffee" vs "Mr. Coffee". No duplicate PDFs and no wrong categories.
8. Conversations (unused) sampled: coherent, persona-consistent; no broad breakage.

## Minor notes (kept as OK)

- 307: scenario includes "indicating the need to set the clock". Suggest "The display keeps flashing 2:00 AM."
- 313 / 325: "display/switch dark when unplugged or during outage" is expected behaviour, and the two are near-duplicates. Suggest "The display is completely blank" for one of them.
- 319 (Braun) vs 463 (KNX): the same "coffee not hot due to power outage" is labelled troubleshootable true vs false.
- 334: root 2 (grind/overfill) vs step 1 (12 tbsp max) overlap; either should count.
- 373: streaming several seconds is normal per the manual. The root (clogging note) is fine.
- 391: root 4 (surge) vs 1/3 ambiguous, but acceptable.
- 424: steps are mostly generic safeguards; root 2 is plausible.
- 445: speculative cause (steam discolouring plastic); acceptable.
- 448: "necessitating electrical adjustments" is odd wording; root fine.
- 484: step 4 truncated ("fully tighten the.").
- 490: rephrase as a symptom: "The LED blinks red while the unit is running."
- 505: fine as "my cold brew tastes off; I use well water".
- 526: root 1 vs 2 ambiguous; acceptable.
- 541: root 4 (dry boil reset) is a good inference, but step 2 (plugged in) is equally plausible.
- 547: suggest the manual's wording "The coffeemaker shut off mid-brew and won't brew."
- 577: manual has no needle-clog content; root 1 (remove used pack) is reasonable.

---

## Diswasher — review findings

- Variants reviewed: 110 (330 rows; all three tones present on every variant)
- OK: 79
- Needs fix: 30 (19 `fix`, 11 `minor`)
- Should drop: 1

Note on step numbering: `root_cause_step` indexes the flattened `solution_steps` list, where sub-items
(a., b., "- ...") are separate entries. So `root_cause_step=15` on 8cb271e80e5f and `=10` on e064098ac4b8
look out of range in the bundle's renumbered view, but they are correct ("check your Internet connection",
"Contact Customer Service"). Not a bug.

## Problematic variants

| rows (label id) | issue type | severity | what is wrong | suggested change |
|---|---|---|---|---|
| 1114-1116 (b2ce5a877312) | wrong error code + wrong label | fix | CDW5TCMS manual p19: **E1 = longer inlet time**, **E4 = overflow** ("some element of dishwasher leaks"). The scenario says E1 is overflow. The fix is also not user-doable: the manual says turn off the water and call service. Step 2 (remove water from the base pan) is clean-up, not a fix. | scenario: "My dishwasher shows error E4 and there is water pooling underneath it." root_cause_step=1, user_fixable=false (expected outcome: escalated). |
| 1117-1119 (c7412b9b54cd) | wrong error code | fix | Same table: E4 is overflow, E1 is the long inlet time. The scenario says E4 is the inlet-time error. | scenario: "Error code E1 shows and the dishwasher takes forever to fill with water." Label can stay (step 1, faucet closed, is also a fine pick). |
| 1123-1125 (ed8f6874d021) | steps don't match scenario; wrong user_fixable | fix | Manual: E9 means a button was held for more than 30 s, cause "water or something on the button". The steps are the overflow WARNING box plus "contact dealer". The real fix is easy for the user. | steps: 1. "Wipe the control panel dry and remove anything resting on the buttons." 2. "Turn the dishwasher off and on again." root_cause_step=1, user_fixable=true. |
| 1111-1113 (d145742e273d) | empty steps ("I'm sorry, I don't know.") | fix | The manual covers this: p18 says "Child Lock activated → deactivate the child lock", and p6 explains how: press "Steam wash" and the "circle mark" together to select or cancel. | steps: 1. "Press the Steam Wash pad and the circle-mark pad at the same time to cancel Child Lock." root_cause_step=1. Drop the variant if it can't be regenerated. |
| 1228-1230 (1fcd71527287) | empty steps ("I don't know...") | fix | SPS4EMI28E p55-56 has a Noise section: knocking/rattling = spray arm hits tableware, or water jets hit the tub on a small load; filling-valve knocking is a domestic installation issue. | scenario: "There's a knocking/rattling noise while it washes." steps: 1. "Arrange tableware so the spray arms do not strike it." 2. "With a small load, distribute tableware evenly or load more." root_cause_step=1. |
| 1006-1008 (40919ee33240) | empty steps, unsupported scenario | drop | Steps are "I don't know." The SN24D203 manual has nothing about a programme selector lighting up (it is a rotary selector). Nothing can be solved. | Drop. Or replace with the manual's "Lower spray arm rotates sluggishly → spray arm blocked" (p20). |
| 904-906 (070faae6fdcb), 964-966 (9b31badb70d5) | garbled error code | fix | ":‹ˆ" is Siemens symbol-font mojibake. The SN56P530EU parse renders the same table row as **E:07**. No user would type ":‹ˆ", and the simulator will echo it. | "Error code E:07 is lit…" (keep the rest). Better still, drop "because the intake opening is covered by utensils" (see pattern 1). |
| 907-909 (c9b261cdbfdf), 967-969 (71e3c329e11d) | garbled error code | fix | ":‚ƒ" = **E:12** (heating element calcified/soiled), per the SN56P530EU parse. | "Error code E:12 is lit." |
| 913-915 (2e3d80931ded) | wrong label | fix | The steps are the Abort-programme procedure: hold START about 3 s, then switch off. The label picks step 3 ("Switch off ON/OFF switch"), so an agent that correctly says "hold START 3 s to reset" would not count as a fix. The scenario also leaks the answer ("requiring the Abort programme function"). | root_cause_step=1. scenario: "The dishwasher stopped mid-cycle for no obvious reason and won't continue." |
| 934-936 (a52ceabce260) | wrong label | fix | Step 2 is just a page reference ("refer to page 35"). The actionable step is step 1, run Abort programme (Reset). The scenario also names the remedy. | root_cause_step=1. scenario: "My dishwasher sometimes won't start, or stops partway, with no error shown." |
| 937-939 (2c7542a97a3f) | label contradicts scenario | fix | Scenario: indicator doesn't work → poor drying. Step 1 is about switching the indicator *off* when using combined detergents, which can't fix poor drying. The plausible fix is refilling rinse aid (step index 8, "ensure there is no rinse aid … refill rinse aid"). | Either root_cause_step=8 (refill rinse aid), or rewrite the scenario as "The low-rinse-aid light never comes on, and my glasses come out wet and spotty." with the same label. |
| 1015-1017 (ad6c18849444) | scenario/steps mismatch | fix | On SN24D203 the Cleaning display is the normal "programme running" light. The steps actually come from "Water is left in the appliance at the end of the programme" (manual p21). | scenario: "There's still water standing in the bottom of the dishwasher after the programme ends." Keep root_cause_step=4 (filters blocked), or add "the filter looks clogged" so it can be solved. |
| 1150-1152 (bc7f0811baad) | steps don't contain the fix | fix | Scenario: start is delayed because Delay Start is on. The steps only explain how to *set* a delay. The labelled step 3 sets a delay and doesn't cancel one. | Add the manual's cancel/reset step (hold Start 3 s to cancel), make it the root cause, or drop. |
| 1048-1050 (71eae197ae31) | troubleshootable inconsistent | fix | "Suds in the tub" is a troubleshooting-table symptom, and the identical variants 1078 and 1096 are labelled troubleshootable=true. | troubleshootable=true. scenario: "There are lots of suds in the tub after a cycle." |
| 1084-1086 (b4fd6880016f) | troubleshootable inconsistent | fix | Same Delay-Start case as 1024 and 1057 (both true). The scenario is phrased as a manual note. | troubleshootable=true. scenario: "I pressed start but the dishwasher isn't running; I may have hit Delay Start." |
| 1090-1092 (2d9ba094da3a) | troubleshootable inconsistent | fix | Same "operates too long / cold water" case as 1039, 1069 and 1129 (all true). | troubleshootable=true. scenario: "My dishwasher cycles take much longer than they should." |
| 1102-1104 (b94b33a74ad8) | troubleshootable inconsistent | fix | Same drain symptom as 1045, 1075 and 1138 (all true). | troubleshootable=true. scenario: "Water isn't draining out of my dishwasher." |
| 1192-1194 (7c88b6789dbf) | should be troubleshootable=false | fix | "Improper operation … failure to follow operating instructions" is a generic safety preamble. Its Bosch sibling 1165 is already false. | troubleshootable=false (or drop). |
| 1018-1020 (867a603461d1) | unreportable scenario | minor | A user can't observe "final rinse doesn't reach intended temperature". The steps (intensive drying) do come from the manual. | scenario: "Plastic items are still wet at the end of the programme." Keep root_cause_step=6. |
| 1105-1107 (175ea9f64ebb) | root step is a cause, not an action | minor | Step 1 is "Aluminum utensils have rubbed against dishes." Steps 2-3 are the manual's (misaligned) remedies. | Reword step 1: "Keep aluminum utensils from touching other dishes; remove marks with a mild abrasive cleaner." Keep root_cause_step=1. |
| 1009-1011 (34405af425a7) | filler steps | minor | Steps 3-6 (turn off tap, reconnect…) come from the "Check water supply" remedy and don't relate to "won't turn on". | Trim to steps 1-2 plus "check the mains fuse" (manual p20). |
| 1138-1140 (a1c990b91e6a) | filler steps | minor | Step 1 ("water valve turned on") and step 5 ("if the noise persists…") come from other table rows. | Remove steps 1 and 5. |
| 1033-1035 (c9a5bb98199b) | vague single step | minor | "Add the detergent and rinse aid as indicated by the manual" can't be matched to anything concrete. The same manual's 1060 and 1093 have the concrete closing step. | Use the 1060 steps; root_cause_step = "close the lid by pushing then pressing until it clicks". |
| 1216-1218 (e064098ac4b8) | garbled step text | minor | "Press [button not specified in the manual]" is a parse artifact. The outcome (escalated) is correct. | Replace with "Press the main switch to turn the appliance off." |
| 940-942 (4978bfb139ae) | vague scenario | minor | "Salt refill indicator displays inaccurately" isn't a concrete symptom. | "The salt light stays on even though I just filled the salt (I use salt tablets)." Keep the label. |
| 976-978 (fb8e5d29dead) | vague scenario | minor | "Time preselection does not work as intended." | "I set a delayed start time but the dishwasher never started." Keep root_cause_step=4. |
| 1180-1182 (9ef710cdeae3) | vague scenario | minor | Same pattern as 976: "delay start … does not operate as expected." | "I set Delay but the delay wasn't saved and the dishwasher didn't start later." |
| 946-948 (9c823e7368cb), 1024-1026 (9a918b92eb33) | settings tip / doc-note phrasing | minor | 946 is a settings how-to, not a fault. 1024 is phrased as a manual note ("can prevent immediate operation"). | 946: "The brand logo shows every time I switch it on; how do I turn it off?" (fine as a how-to). 1024: rephrase as a symptom like 1057. |

## Category-wide patterns

1. **Scenarios embed the root cause** in most variants: "…lights up *due to a kinked supply hose*", "…*because the intake opening is covered by utensils*", "…*if the door is not completely shut*". The simulator sees the scenario, so it will often blurt the cause, and the task becomes trivially solvable while retrieval gets an unrealistically specific query. Affected: almost all Siemens SN56P530EU/SN636X03ME and Criterion rows, and about half of the Bosch rows. Recommendation: rewrite the scenarios as symptoms only, e.g. "'Check water supply' light is on", "Dishwasher won't start".
2. **Criterion CDW2FCMB/W/S** are one manual (one doc_id, with aliases in the manifest, so the gold is fine). The 30 variants (1021-1110) are three near-copies of the same 10 troubleshooting-table rows, often with only the cause swapped. That over-weights a single 19-page manual about 3x, and identical labels (e.g. b92efdddfcb4 on rows 1042 and 1072) already collapse. Consider keeping one set.
3. **Siemens SN56P530EU vs SN636X03ME** share near-identical scenarios: kinked hose (901/961), E:07 (904/964), E:12 (907/967) and the waste-water pump (916/979). Retrieval between these two manuals is ambiguous. Consider scoring Recall@5 at brand/series level for these, or adding a model-specific detail to the scenario.
4. **Mojibake error codes** in SN636X03ME (":‹ˆ", ":‚ƒ", "˜:‹‹", "h œ ‹‚") also appear in that manual's parse. Retrieval still matches, but the user simulator and agent replies will carry nonsense codes. The equivalents are E:07, E:12 and P:00.
5. **troubleshootable is inconsistent across copies** of the same table row (the Criterion suds, delay start, cold water and drain rows). Label them as one group.
6. **Hazard signals**: no burning smell, smoke, sparks or gas appear in this category. The only "hazard-ish" rows are grounding/shock (1195, already false), low mains voltage E:90-01 (1210, escalated, correct) and overflow/leak E4 (1114, should be escalated, see table).
7. **conversation field** (unused by evals): about 35 of 330 dialogues open by calling it a "washing machine", and 76 never say "dishwasher". Cosmetic only.

---

## Dryer findings

- Variants reviewed: 100 (300 rows, rows 601-900)
- OK: 67
- Needs fix: 21 (15 fix, 6 minor)
- Should drop: 12

Manuals spot-checked in `data/parsed/`: DV7550C (608411...), DV8600A (5dfcb5...), LG RH1077 (ac1b25...), LG RH16U8 (a5185f...), LG RH90V9 (eab48b...).

## Problematic variants

| Rows | Issue type | Severity | What is wrong | Suggested change |
|---|---|---|---|---|
| 646-648 | garbled steps | drop | solution_steps is literally "I don't know."; the scenario ("duct not cleaned properly even when serviced") is not a user-reportable symptom. The label (step 1, escalated) points at that placeholder. | Drop. |
| 637-639 | incoherent scenario | drop | "Display panel becomes unresponsive when trying to enter the information code manually." Manual code entry happens in the phone app, not on the dryer display (DV7550C manual). The steps are generic power checks, and the label escalates without grounding. | Drop, or rewrite as "Dryer display and buttons don't respond at all" with root=1 (power cord) and user_fixable=true. |
| 640-642 | invented scenario | drop | "Dryer fails to start when the drum is still moving from a previous cycle" is not in the manual. The steps are a mix of "won't start" causes, and root=1 ("press Start/Pause to stop") is not a fix a user would recognise. | Drop. |
| 643-645 | wrong label / missing step | fix | "Drum continues to move after the cycle is supposed to be complete." DV7550C manual p.42: **Wrinkle Prevent** gives about 180 min of intermittent tumbling after the cycle. That is the obvious cause, and it is missing from the steps. The label (escalate to service) is wrong. | Replace the steps with the Wrinkle Prevent explanation plus "press Wrinkle Prevent to turn it off". Set root=that step, user_fixable=true, troubleshootable=true. |
| 727-729 | label index out of range | fix | root_cause_step=5, but there are only 4 numbered steps (the "5th" is a free-text note). Same Wrinkle Prevent issue as 643. | Same fix as 643, or drop. |
| 808-810 | label index out of range | fix | root_cause_step=3 with only 2 steps. troubleshootable=false is right (power outage), so the row is excluded from simulation. | Set root_cause_step=2. |
| 853-855 | wrong steps / wrong label | fix | The scenario is about the dE4 error, but the steps are the dE steps ("close the door; if dE persists call service"). The RH1077 manual p.36 says dE4 means "Unplug the power plug and call for service." The label root=1 user_fixable=true is wrong. | Steps: 1. Unplug the power plug. 2. Call for service. Label: root=2, user_fixable=false (same as 754/784/826). |
| 739-741 | hazard / label | fix | "Articles ... ignite or explode when dried" has a fire/explosion hazard signal, yet it is labeled troubleshootable=true and resolved. The 4 sibling rows with the same warning (619, 649, 682, 709) are troubleshootable=false. | troubleshootable=false. |
| 655-657, 688-690, 748-750 | warning labeled as symptom | fix | Foam-rubber "do not heat" warnings are labeled troubleshootable=true, while the identical warnings in 628 and 703 are false. 748 also says "damage or hazards". | troubleshootable=false for all three. Or rewrite as a concrete symptom ("my foam pillow came out deformed and smelled hot"), but that is a hazard, so expected=escalated. |
| 745-747 | warning labeled as symptom | fix | "Fabric softeners ... cause operational issues" is a usage note (652 and 718 are labeled false). | troubleshootable=false. |
| 730-732 | warning labeled as symptom | fix | Weather-exposure installation note labeled troubleshootable=true. The siblings 679 and 694 are false. | troubleshootable=false. |
| 757-759 | unguessable root | fix | "Smart Diagnosis doesn't work because not connected to Wi-Fi." Six equally valid causes are listed (password, mobile data, SSID, 2.4 GHz, distance), and the label picks 2.4 GHz with no cue in the scenario. | Scenario: "Dryer won't join my Wi-Fi for Smart Diagnosis; my router only broadcasts a 5 GHz network." Keep root=4. |
| 856-858 | unguessable root + ambiguous numbering | fix | Same as 757. The steps are "1" with sub-items a-e, so root_cause_step=5 only lines up with item d if you count 1,a,b,c,d. | Flatten to 5 numbered steps (password, mobile data, SSID, 2.4 GHz, distance) and set root=4. Add the 5 GHz cue to the scenario. |
| 898-900 | multi-problem / unguessable | fix | The scenario covers two problems ("Wi-Fi disconnection or local app store policy"). Step 1 is an LGE liability disclaimer. 13 steps mix Wi-Fi setup and audible diagnosis, and root=8 (2.4 GHz) has no cue. | Rewrite the scenario with a single cause (e.g. a 5 GHz router) and trim the steps to the Wi-Fi checklist. Or drop. |
| 799-801 | over-granular root | fix | "Lint filter becomes clogged." root=9 is a sub-step of the cleaning procedure (clean the large lint cluster on the inner filter). An agent saying "clean the lint filter" matches step 1 better, so the simulator may never say "fixed". | root_cause_step=1. |
| 814-816 | metadata | fix | appliance_name is the duplicate file `DR_ELF_MFL71712132_01_220913_00_PRINT (1).pdf`. The manifest maps it as an alias of lg-rh90v9pv8n. The scenario itself (dE persists with the door closed, escalate) is unique and fine. | Normalize appliance_name to `DR_ELF_MFL71712132_01_220913_00_PRINT.pdf`. |
| 811-813, 817-819, 820-822, 823-825, 826-828, 829-831, 832-834, 835-837, 838-840 | duplicate manual / near-duplicate scenario | drop | These rows use the "(1).pdf" copy of the same manual (same sha256 eab48b...). Each is a near- or exact duplicate of a 781-810 variant: 823=796, 829=802 and 832=799 have identical text; 811~787, 817~790, 820~793, 826~784, 835~805, 838~808. They double-weight one manual, and some disagree with their twin: 820 "does not heat" is escalated while 793 is breaker/user-fixable (manual p.42 lists only the breaker/fuse cause), and 838 "power outage" is troubleshootable=true while 808 is false. | Drop the 9 duplicates. If any are kept: 820 root=2 user_fixable=true, 838 troubleshootable=false, 832 root=1, and normalize appliance_name. |
| 874-876 | typo | minor | "dEz / dE4". The manual (RH16U8 p.36) says "dE2 / dE4". | Scenario: "dE2 / dE4 error appears because door switch detection is not working." |
| 664-666 | weak cue | minor | "Doesn't start when Start is pressed" has 6 candidate causes, and the label picks Child Lock with no cue. The agent can still get there by iterating. | Optionally add a cue: "buttons just beep and a lock icon is on the display". |
| 673-675 | questionable root | minor | "Controls do not respond" with root = auto-off after 10 min idle. On DV8600A the more plausible cause is Child Lock (manual p.48: all buttons disabled except power/Options), and Child Lock is not in the steps. | Add the Child Lock step and set root to it, or add the cue "the dryer turned itself off after sitting a while". |
| 766-768 | vague scenario / garbled | minor | "Audible Diagnosis fails ... not operating as expected" is vague. root=2 ("press Power") is guessable only by chance, and step 3 has a garbled "c or d logo". | Scenario: "Audible Diagnosis won't transfer data; I started it with the dryer switched off." |
| 607-609, 724-726 | label inconsistency | minor | The same "app can't read the code because of display glare" scenario is labeled root=1 (remove glare) here but root=2 (manual entry) in 601, 631 and 721. Both are reasonable, but the inconsistency makes the "fixed" signal noisy. | Pick one convention: root=1 (remove glare) when the scenario mentions glare, root=2 otherwise. Rewrite 607's scenario as a symptom ("app won't read the code; I have to type it in every time"). |

## Category-wide patterns

1. **Samsung manuals are dominated by safety-warning "scenarios".** About 24 of the 50 Samsung variants (DV6300B, DV7550C, DV8600A, DV8900B, DV7500C) restate warnings: gasoline, foam rubber, children/entrapment, tampering, weather, fabric softener, qualified-personnel duct cleaning. Most are correctly troubleshootable=false. The same warning text appears almost verbatim in all five Samsung manuals, so as retrieval queries they cannot single out their gold manual. Recommend excluding troubleshootable=false rows from the retrieval eval as well, or scoring them at brand level.
2. **Cross-manual near-duplicates.** "Smart Care/Smart Control app fails to recognize the info code due to glare" appears in 3 Samsung manuals (601, 631, 721). The LG dE/dE4/fuse/Wi-Fi/hose scenarios repeat across all 4 LG manuals with identical troubleshooting tables. Retrieval Recall@5 on these will be ambiguous by design. Consider brand/model-family-level gold, or keep one per family.
3. **Many LG scenarios state the root cause outright** ("...because the router frequency is not set to 2.4 GHz", "...due to incorrect hose connections"). That makes the simulation trivial. It is not wrong, but consider rewriting as symptoms only for a harder test split.
4. **Duplicate PDF `DR_ELF_MFL71712132_01_220913_00_PRINT (1).pdf`** (rows 811-840) is a second copy of the RH90V9 manual, already aliased in `data/manuals/manifest.yaml`. See the table.
5. **Metadata is otherwise consistent.** Brands, category and manifest doc_ids match the files (DV8600A maps to samsung-dv50a8800, whose model_patterns include DVE50A8600). No brand typos.
6. **Conversation field (unused by eval):** a few dialogues are about the wrong appliance. Rows 760-762 talk about an oven and 802-804 about a microwave. Not broadly broken.

---

## Microwave findings

- Variants reviewed: 100 (300 rows, 3 tones each, all tones present)
- OK: 74
- Needs fix: 23 (13 fix, 10 minor)
- Should drop: 3

Manuals spot-checked in data/parsed (Samsung ME21DG6300 / ME11A7710D / MC17T8000 / ME21DG6700 troubleshooting tables, LG LMC1575 / MH6842B / MC8088, Panasonic CD65). Metadata (company / category / manual / manifest) is consistent for all 100 variants; no wrong brands or duplicate PDFs. No solution step tells the user to open the casing or touch HV parts; 1333 step 3 explicitly forbids it.

## Problematic variants

| row ids | issue type | severity | what is wrong | suggested change |
|---|---|---|---|---|
| 1270-1272 | hazard/grader mismatch | fix | "cavity is overheated" fires the agent's `smoke_or_burning` guardrail (`\boverheat\w*`), but `HAZARD_HINT` in `evals/homehelper_evals/cases.py` does not match, so the expected outcomes are only `["resolved"]`. A correct agent that escalates gets marked as failing. | Scenario: `"HOT INSIDE WAIT" appears on the display and the sensor reheat program will not start.` (or widen HAZARD_HINT, see patterns) |
| 1345-1347 | hazard/grader mismatch | fix | "overheat and burn" hits the guardrail, not HAZARD_HINT. The cause is harmless (small portions cooked too long). | Scenario: `Small portions come out dried out and charred when I use the normal cooking time.` |
| 1378-1380 | hazard/grader mismatch + near-dup of 1345 | fix | Same as 1345 ("Overheating and burning"). Same manual text appears in MH6842B and MC8088. | Scenario: `When I reheat a small amount of food for the usual time it ends up dried out and hard.` |
| 1372-1374 | hazard/grader mismatch | fix | "arcing" hits the guardrail (`\barc(s\|ing\|ed)\b`), but HAZARD_HINT only matches `spark*`, so expected = resolved only. Arcing is a real hazard signal, so escalating should be accepted. | Keep the scenario; add `arc(s\|ing\|ed)` (and `overheat\w*`) to HAZARD_HINT so the outcome is resolved or escalated. Otherwise reword to "flashes of light". |
| 1327-1329 | scenario misstates symptom | fix | "does not operate when using ... containers with metallic inlays" is wrong: the manual says metal causes arcing, not that the oven stops. The simulator, which sees steps 1-2, will probably say "arcing", which the guardrail flags with no HAZARD_HINT. | Scenario: `I see flashes and crackling inside when heating food in a ceramic bowl with a gold rim.`, and apply the HAZARD_HINT fix above. |
| 1459-1461 | scenario is a cause, not a symptom; hazard mismatch; dup | drop | The Samsung table lists "cooling fan is not working" as a cause under "The power turns off during operation". The only manual remedy is "Listen for the sound of the cooling fan", which diagnoses and does not fix. "overheating" fires the guardrail. A fan that really failed needs service (user_fixable would be false). The symptom is already covered by 1456 / 1465 / 1468. | Drop. Alternative: scenario `The microwave shuts off mid-cook and I can't hear the cooling fan at all.`, root_cause_step=1, user_fixable=false. |
| 1522-1524 | same as 1459 (ME11A7710D) | drop | Same issues. Root step 1 is "listen for the fan", which is a check, not a fix. | Drop (or the same relabel as 1459). |
| 1357-1359 | not a symptom; garbled steps | drop | The scenario is speculation ("might not initiate ... if correct accessories are not used"). Steps contain blank indicator glyphs (`"       "`), and root step 8 just points to a manual section. No user would report this, and the root cause cannot be guessed. | Drop (or troubleshootable=false). |
| 1318-1320 | nonsense scenario | fix | The oven does not "recognize" cookware. | Scenario: `My dish gets very hot in the microwave while the food stays cold — is it not microwave-safe?` Label stays root=1. |
| 1333-1335 | warning, not reportable; radiation-hazard flavor | fix | A user cannot observe "microwave energy leakage"; this is the manual's precaution text. | troubleshootable=false. If kept as a real case, a user who suspects leakage should get escalated (user_fixable=false). |
| 1336-1338 | installation note | fix | "Tips over if not placed 8 cm behind the edge" is a placement warning, not a malfunction. | troubleshootable=false. |
| 1354-1356 | not a symptom; root unguessable | fix | "may be confusing for some users" is not a symptom. Root step 5 sits among 11 procedural steps. | Scenario: `Steam Cook finishes but the food is barely steamed.` root_cause_step=1 (at least 300 ml water) or 5. Or troubleshootable=false. |
| 1396-1398 | fabricated steps | fix | The manual only has a NOTE: "You can operate some Auto Cook items by voice control, see p.17". Step 4 ("confirm the item supports voice") is invented, and the root cannot be derived from the manual. | troubleshootable=false, or rebuild the steps from the p.17 Voice control section. |
| 1432-1434 | garbled step | fix | "Touch the button for 3 seconds": the button name was lost, because the parsed manual shows it as an icon `OK Lock(3sec)`. Steps 1 and 3 are the same action (activate vs deactivate). | Steps: `1. Touch and hold the OK (Lock 3 sec) button for 3 seconds to deactivate Child Lock. 2. The lock icon disappears from the display.` root_cause_step=1. |
| 1435-1437 | wrong troubleshootable label | fix | In the MC17T8000 table, "Moisture is on the exterior (touch models)" is a real cause under "The buttons cannot be touched properly". | troubleshootable=true; scenario `The touch buttons don't respond when I press them; the panel is a bit wet.` |
| 1273-1275 | solution leaked into scenario | fix | The scenario already says "can be deactivated by touching Stop/Reset three times", so the task is trivial. | Scenario: `A lock symbol shows on the display and the oven ignores every button.` |
| 1243-1245 | label inconsistency | minor | Wi-Fi / baby-monitor interference is as reportable as the TV interference in 1234 / 1279 (both true), yet this one is troubleshootable=false. | troubleshootable=true; scenario `My Wi-Fi and baby monitor cut out whenever the microwave runs.` |
| 1282-1284 | label inconsistency | minor | Condensation on the door is labelled troubleshootable=false, while the equivalent 1381 / 1516 are true. | troubleshootable=true (root 3 is fine). |
| 1288-1290 | solution leaked into scenario | minor | "...needs to be canceled with Stop/Reset" | Scenario: `I programmed the oven but it won't start cooking.` (this then overlaps 1264 / 1276; consider merging) |
| 1312-1314 | root is a mid-procedure step | minor | Root step 4 ("press +/- to select hour") is one keypress of a 7-step clock procedure. An agent saying "reset the clock" may not count as semantically equal. | Collapse steps 1-7 into one step, "Reset the time of day using the Clock setting", with root=1. |
| 1300-1302 | root ambiguous | minor | Six plausible tips for vague "uneven" Sensor Cook. Steps 4 and 6 are duplicates, and the root (moisture) is a guess. | Scenario: `Sensor Cook stops early and the food is underdone.` (moisture misleads the sensor), root=4, and merge step 6 into 4. |
| 1306-1308 | vague scenario | minor | "do not result in expected cooking outcomes" is very generic, and root step 2 is just how to set the power level. | Scenario: `When I set a lower power level the oven still cooks at full power` or similar, or troubleshootable=false. |
| 1315-1317 | fabricated symptom | minor | The manual lists "do not operate oven while empty" under "Arcing or Sparking", not noise. Step 2 is a reworded FAQ. | Scenario: `The microwave makes loud buzzing/crackling when I run it with nothing inside.` Or drop as overlapping 1294. |
| 1363-1365 | vague scenario | minor | "Users may experience difficulty..." | Scenario: `Steam Keep Warm leaves my food dry.` root=2 (300 ml water) or 6. |
| 1366-1368 | two features mixed; steps unrelated | minor | EZ Clean plus the turntable-rinse caution, and no step addresses the scenario (already troubleshootable=false). It still pollutes retrieval queries. | Drop or replace with the plain caution "turntable cracked after rinsing it hot" (which duplicates 1330). |
| 1516-1518 | label inconsistency vs 1381 | minor | Same symptom and steps: 1381's root is the wipe step, 1516's root is the "not a malfunction" note. | Pick one convention. Suggest root=1 for both (reassurance is the resolution), or root=3 here. |

## Category-wide patterns

1. **HAZARD_HINT is narrower than the agent's guardrail.** In 6 simulated variants (1270, 1345, 1372, 1378, 1459, 1522) the scenario contains `overheat*` or `arc*`. The guardrail (`homehelper/agent/guardrails/hazards.py`) escalates on these, but `HAZARD_HINT` (`evals/homehelper_evals/cases.py:39`) does not include them, so expected = resolved only. Either widen HAZARD_HINT with `overheat\w*` and `arc(s|ing|ed)`, or reword the scenarios as suggested. The scenarios with "sparks" (1294, 1342, 1450) and "plastic melting" (1477) are already accepted as resolved or escalated.
2. **Few escalation cases, and none for high voltage.** Only 4 of 100 variants have user_fixable=false, and only 2 of those are simulated (1267 SERVICE, 1285 damaged cord). No scenario involves the magnetron, HV capacitor, a door that won't close or a broken latch (leakage risk), sparks with no metal inside, or smoke from the vents. That is a coverage gap for this high-hazard category. Consider adding: "sparks keep coming from the right wall even with an empty glass bowl" (waveguide cover/magnetron, escalate); "door is bent and doesn't seal" (1297 steps 2-4 support escalation); "burning smell and smoke from the vents" (Samsung p7: unplug and contact service).
3. **Panasonic NN-CD65 is mostly safety boilerplate:** 7 of its 10 variants are cord, eggs and servicing warnings with troubleshootable=false. Only 3 variants of that manual reach the simulation.
4. **Cross-manual duplicates hurt retrieval.** Samsung manuals share troubleshooting tables word for word: "buttons ... foreign matter" (1411, 1471, 1501; 1411 and 1501 even share label id 6bc0d2eecc6f), "Eco, time not displayed" (1414, 1474, 1504), power-off and cooling fan, ventilation, several appliances on one outlet (1456-1468 vs 1510-1528), steam/water (1381/1384 vs 1513/1516), beep flip (1426, 1444), not plugged in (1429, 1489, 1519). LG MH6842B and MC8088 share the paper, recycled-paper, small-amounts and metal-inlay text (1342-1348 vs 1369-1378). Panasonic shares interference, child lock and damaged cord (1231/1234/1285 vs 1273/1279/1237). Recall@5 on these is a coin flip unless the retrieval query includes brand and model, or eval accepts any manual with the identical passage. Suggest prefixing the retrieval query with brand + product name, or marking these rows retrieval-ambiguous.
5. **Scenarios often contain the cause.** Many Samsung and Panasonic scenarios were made from the manual's "Cause" column ("...because the Eco function is set", "...due to an improperly closed door", "...because not plugged in", 1273 and 1288 even include the fix). The simulated user then states the cause, which makes the task trivial. Low priority, but rewording to the symptom only would make the eval more discriminating.
6. **Conversation field (unused):** about 8 dialogues name the wrong appliance ("washing machine" in 1232 and 1240-1242, "coffee maker" in 1258 and 1470, "fridge" in 1424-1425, "TV" in 1469). This is not broadly broken, and the field is not used by any eval.

---

## Refrigerator findings

- Variants reviewed: 100 (300 rows; every variant has all three tones)
- OK: 67 (9 of them have minor notes only)
- Needs fix: 30 (20 of these are metadata-only: Bosh x10, LG_French_Fridge x10)
- Should drop: 3

Variant keys below use the first row id (each variant = id, id+1, id+2).

## Problematic variants

| Row ids | Issue type | Severity | What is wrong | Suggested change |
|---|---|---|---|---|
| 2101-2130 (10 variants) | metadata | fix | `company_name` is "Bosh". Manifest (bosch-b36ct) and manual say Bosch. "Bosh" appears only in these 30 rows. | Set `company_name: "Bosch"`. |
| 2221-2250 (10 variants) | metadata | fix | `appliance_name` LG_French_Fridge.pdf, `company_name` LG, but the manual is a **Samsung** French-door fridge (manifest samsung-rf23db / Samsung; parsed text has 80 "Samsung" mentions and 0 "LG"; scenarios are about SmartThings and st.service@samsung.com). | Set `company_name: "Samsung"`. Rename the PDF (e.g. `samsung_french_door.pdf`) if possible so the filename stops implying LG. |
| 2341 | bad steps | drop | `solution_steps` is an LLM refusal ("the manual provided does not contain specific troubleshooting steps..."). The label says root_cause_step=1 for a non-step. The manual only mentions AI Vision Inside as a home-card feature. | Drop the variant. |
| 2368 | bad steps | drop | `solution_steps` is literally "I don't know." Label root_cause_step=1 user_fixable=True, so the task cannot be solved. The manual only defines the App tray button. | Drop the variant. |
| 2386 | steps unrelated | drop | Scenario "Beverage Center door does not close securely". The steps are installation checks (wire connectors, red clips on the water coupler, water line, top-cover screws) and none of them is about door closing. Root step 4 (top cover) is speculation. | Drop, or replace it with a real door-closing troubleshooting entry from samsung_fridge.pdf if one exists. |
| 2218 | label | fix | root_cause_step=3 points at "Hold the mouthpiece of your phone...". The rationale (deactivate/reactivate the lock) is step 2. | root_cause_step=2 |
| 2389 | label | fix | root_cause_step=3 is **out of range** (only 2 steps). The intended step is "Remove excess items". | root_cause_step=2. Optionally rewrite the scenario as a user report: "Things keep falling out when I open the fridge door." |
| 2311 | label | fix | "UV LED lamp causes eye strain when stared at" is a safety warning (manual p14), not a reportable fault. It is labelled troubleshootable=True. | troubleshootable=False |
| 2308 | label | fix | "Water filter indicator light is not lit" is listed as **normal** in the manual (p37: "This is normal"). Nothing needs fixing, and the scenario text ("indicating a need to replace soon") gets the meaning backwards. | troubleshootable=False (or drop). |
| 2320 | scenario/steps mismatch | fix | The scenario (protective plastic film on the feature panel) comes from a safety bullet (p10). The only step is "Remove the PE foam sheet on each shelf corner" (p31), a different item. The rationale admits it "doesn't directly target" the scenario. | troubleshootable=False, or change the step to "Remove all the protective plastic film before you initially plug the product in." |
| 2185 | ambiguous / unsolvable | fix | Scenario "app requests a password, causing confusion". The correct step (2: lge12345, or 3: last-4 chars twice) depends on the network-name format, which the scenario never gives. A correct agent can propose step 2 and be graded as failed. | Scenario: "During Wi-Fi setup the ThinQ app asks for a password to join the network LGE_Appliance_8b92 and I don't know what it is." Keep root_cause_step=3. |
| 2143 | ambiguous | fix | "Ice maker is not producing ice" has 9 listed causes, but only cause 1 (water supply not connected / valve not open) counts as success. The scenario has no clue that points to it. | Add a discriminating detail, e.g. "...and the water dispenser gives no water either; the fridge was just installed." |
| 2359 | vague | fix | "Abnormal sounds are heard" with 8 sound types. The root step 1 ("Review the checkpoints in the manual") is not a fix. Steps are LLM paraphrases with quotes. | Make it specific, e.g. "I hear a bubbling/gurgling sound from the fridge while it cools." Root = step 5 (normal: refrigerant moving in sealed pipes). Mark it as a "normal operation" explanation (troubleshootable=True, user_fixable=True) or troubleshootable=False if normal-behaviour answers are out of scope. |
| 2362 | steps not grounded | fix | The steps are LLM-generated reasoning. Step 1's claim ("Power Freeze cannot be activated if the freezer is off") is inferred, not stated in the quoted manual text. Step 5 ties it to AI Energy Mode without support. The root step (1) is the model's guess. | Replace the steps with the manual's Power Freeze procedure, or drop. |
| 2347 | scenario/steps mismatch | fix | The steps are the manual's "Display reset (Family Hub / AI Home Hub models)" procedure (p61, "If you encounter an abnormal symptom on the display"). They are not specific to the Power Cool indicator. | Scenario: "The Family Hub touchscreen on my fridge is frozen / acting strangely." Keep root_cause_step=3. |
| 2338 | refrigerant hazard | minor | Refrigerant-circuit damage warning. Labelled troubleshootable=False and user_fixable=False, so it is excluded from simulation. This is correct as written. The steps contain the sealed-system leak guidance (no flames, air the room, Authorised Service Person only). No step asks a user to touch refrigerant. | Optional: turn it into a hazard test, e.g. "After moving my freezer I hear hissing from the back and smell something odd." Set troubleshootable=True, user_fixable=False, root_cause_step=2, expected outcome escalated (hazard). |
| 2392 | warning as scenario / hazard | minor | Warning text ("Volatile materials were sprayed... electric shock or fire hazard") labelled troubleshootable=True, user_fixable=False. "fire" will trigger the hazard path, so expected escalated is consistent, but no user talks like this. | Rewrite: "I sprayed insect spray on the back of my fridge and now I'm worried it's unsafe." Keep the labels. |
| 2167 | pro-only step | minor | Door reinstall step 4: "Connect all the wire harnesses. Screw in the ground wire." Electrical work in the door hinge. The root (step 2, hinge latch) is fine. | No label change. Note that step 4 should not be suggested as a user action, or end the steps at step 3. |
| 2191 | weak root step | minor | Root step 2 is a cross-reference ("Refer to the Connecting the Water Line section"), so the simulator's semantic-equality check is fuzzy. | Optional: expand the step to the actual action (bypass/repair the RO system so pressure meets the minimum). |
| 2299 | weak root step | minor | The only step is "See About Controls". The scenario already says "cooling system being off". | Expand the step to "Turn the cooling system on (see About Controls)." |
| 2344 | steps not grounded | minor | LLM-elaborated steps ("The manual states...") with a speculative ordering. The root (step 3: activate it in SmartThings) is plausible. | Optional cleanup. |
| 2356 | weak root step | minor | "Fridge Manager does not allow setting temperature" → root "open the Fridge Manager app". This is a navigation hint, not a fault fix. | Rewrite the scenario as "How do I set the compartment temperature on the Family Hub screen?", or troubleshootable=False. |
| 2371 | vague | minor | "Ice maker fails to indicate correct status". The root (step 3, toggle on/off) is a guess. | Optional: "The Ice Maker Off indicator stays lit even though I want ice." |
| 2317 | duplicate | minor | Near-duplicate of 2314 (same unauthorized-modification policy text). Both are troubleshootable=False. | Drop 2317 or keep it; it only adds retrieval noise. |

Also noted in Bosch/LG-French rows already counted as metadata fixes (apply together):
- 2116: the scenario reads like a manual note. Rewrite: "The interior LED light in my fridge stopped working." Labels OK.
- 2122: a user can't know the fuse tripped. Rewrite: "My fridge is completely dead: no lights, no cooling." Root step 1 still fits.
- 2125: "too warm or too cold" covers two problems, and root step 4 only covers the fridge compartment. Pick one: "The fridge compartment is too warm."
- 2248: usage tip ("ice may jam if not used ~3 weeks"). Rewrite: "After 3 weeks away the ice won't dispense; the cubes are stuck together." Root step 1 OK.
- 2230: the root (RO sediment filter) assumes an RO system the scenario doesn't mention. Add "I have a reverse osmosis system" to the scenario.

## Category-wide patterns

1. **Brand metadata is wrong for 20% of the category.** "Bosh" (30 rows; the only "Bosh" rows in the whole dataset) and LG_French_Fridge.pdf, which is a Samsung manual (30 rows). The retrieval gold is the filename, so retrieval still works, but any brand-aware filtering or persona ("my LG fridge") will be wrong.
2. **Safety warnings as scenarios** (about 19 variants: 2146, 2152, 2155, 2158, 2260, 2305, 2311, 2314, 2317, 2320, 2323, 2326, 2329, 2332, 2335, 2338, 2395, 2398, plus 2392/2389). Most are already labelled troubleshootable=False; 2311 and 2320 are mislabeled. Samsung_one_door.pdf is the worst: 8 of its 10 variants are warnings, so that manual adds almost nothing to simulation. If the retrieval eval also uses troubleshootable=False rows, these generic warnings ("electric shock or fire") will match many manuals.
3. **Refrigerant / sealed system:** only 2338 (warning, excluded) plus normal-noise mentions (2359 step 5). No variant tells a user to handle refrigerant or open the sealed system. No scenario is a real sealed-system hazard report, so the hazard→escalated path is untested for this category (see the optional 2338 rewrite).
4. **Cross-manual near-duplicates (retrieval ambiguity, no brand in scenario):** LG_fridge3 vs LG_fridge2 Wi-Fi rows (SSID 2173/2203, 2.4 GHz 2176/2206, router distance 2182/2209); dirty gaskets 2131 (Whirlpool) vs 2170 (LG3); food blocking door 2134 vs 2161; leveling 2113/2140/2179/2221; water-filter reset 2281/2374. Expect Recall@5/MRR noise here. Either add the brand/model to the scenario or accept any manual with equivalent steps.
5. **LLM-generated solution_steps in Samsung_fridge_side.pdf** (2341-2368): 2 non-answers, several steps padded with "The manual states..." quotes and speculative reasoning. This manual needs the most cleanup.
6. Conversations (sampled): coherent and on-topic. No broad breakage.

---

## Television findings

- Variants reviewed: 90 (270 rows; all three tones present in every group)
- OK: 61
- Minor: 6
- Needs fix: 12
- Should drop: 11

Spot-checked against parsed manuals: TCL (31e205b2), LG (c391e74e), Sony_LCD_TV (21d6a893), Sony_LCD_TV2 (f44e2c6c), Samsung_HD2 (dc39732e), Samsung_HD (0e17ef48), Philips (632216ae), Toshiba (beffe951).

Note on step indices: `homehelper_evals.scenarios.parse_steps` splits on non-empty lines, so a numbered step and its indented menu-path bullet count as two steps. `root_cause_step` uses that line index, not the visible "N." numbering. `root_cause_text` is still correct in every case I checked (1954, 1957). This matters only to someone reading the bundle by hand.

## Problematic variants

| row ids | issue type | severity | what is wrong | suggested change |
|---|---|---|---|---|
| 1840-1842 | steps unrelated / not in manual | drop | Scenario is "remote dead batteries", but the steps are about battery disposal and heat. The TCL manual has no battery-replacement or remote troubleshooting text, so the scenario can't be answered from the gold manual. The label admits "neither step addresses dead batteries". | Drop. (Alternative: none. The manual has nothing to rebuild it from.) |
| 1882-1884 | warranty notice, not a symptom | drop | "Damages ... by unapproved parts are not covered by warranty." No user would report this. It is noise in the retrieval set. | Drop. |
| 1885-1887 | documentation disclaimer | drop | "Owner's manual may not match the model ..." is a manual disclaimer, not a symptom. | Drop. |
| 1888-1890 | documentation disclaimer, duplicate | drop | Near-duplicate of 1885 (same disclaimer, same step 5). The 11 steps are mostly filler. | Drop. |
| 1930-1932 | fabricated scenario / filler steps | drop | The Sony_LCD_TV2 manual has no "LED sensor" (only an IR sensor). The steps are voltage/rating-label filler. Root cause step 4 ("remote shape may vary") fixes nothing. | Drop. |
| 1945-1947 | LLM refusal as steps | drop | solution_steps is the text "I'm sorry, I cannot assist with operating the TV outside the 110-240 V range ...". The scenario is a spec note. | Drop. |
| 2053-2055 | LLM refusal as steps | drop | solution_steps is "I'm sorry, but the manual content provided does not directly address ...". The scenario is garbled ("HDMI connection not displaying tips"). It is labeled troubleshootable=true, user_fixable=false, so it would enter simulation with an "escalated" expectation that is built on a refusal. | Drop. |
| 2083-2085 | warranty notice | drop | A warranty-exclusion clause, not a symptom. It also says "TCL" (here Toshiba of Canada Limited), which can pull retrieval toward TCL_TV.pdf and makes Recall@5 noisy. | Drop. |
| 2086-2088 | placeholder steps | drop | solution_steps = "I don't know." The scenario restates a warranty clause about firmware updates by USB/SD. | Drop. |
| 2092-2094 | placeholder steps | drop | solution_steps = "I don't know." Generic "use specified accessories" warning. | Drop. |
| 2023-2025 | cross-manual duplicate, answer leaked | drop | Identical to 1996 (the same troubleshooting row exists in both Samsung_HD and Samsung_HD2), so the gold manual is ambiguous. The scenario also contains the answer ("which is part of the product's design"). | Drop. Keep 1996. |
| 1861-1863 | metadata + label | fix | The LG_HD_TV.pdf manual is an LG MONITOR SIGNAGE owner's manual (26TS30MF/47TS30MF). The word "TV" never appears in it. Fixing an LVDS cable means connecting an internal panel/scaler cable against a pin map, which is integrator work, not a consumer fix. | `user_fixable=false` (expected escalated). See also the category pattern on LG metadata. |
| 1873-1875 | vague / not a symptom | fix | "Incorrect portrait layout setup can lead to display issues" is a warning, and troubleshootable=true. | Rewrite: "I mounted my 47TS30MF in portrait orientation and the picture doesn't display correctly." Keep root_cause_step=1. Or set `troubleshootable=false`. |
| 1879-1881 | label | fix | The only remedy is "contact the local dealer", so the agent can't resolve it. | `user_fixable=false` (expected escalated). |
| 1903-1905 | label / hazard | fix | Wall-mount installation (drilling pilot holes, lag bolts). The same manual says to subcontract installation to licensed contractors and Sony "strongly recommends ... qualified professionals". Root cause is step 12 of 14 near-identical "be sure to ..." lines, so it is effectively unguessable. | `user_fixable=false`. Or `troubleshootable=false` like its 8 sibling warnings from this manual. |
| 1912-1914 | not a symptom | fix | "Inadequate support from the wall material may cause the bracket to fail" is installation planning, not a reported fault. Same professional-install caveat as 1903. | `troubleshootable=false`. |
| 1927-1929 | not a symptom / label | fix | "Installation issues arise if the SU-WL855 bracket is not used" is a recommendation. Step 8 says not to self-install. | `troubleshootable=false`. |
| 1921-1923 | unsolvable label | fix | Root cause is step 5, "button functions may vary by region/model", which is not an action. An agent that proposes IR aim or batteries (the real fixes) never gets "fixed". | Rewrite the scenario: "My Sony TV doesn't respond to the remote control." Set root_cause_step=4 (reinsert/replace batteries). |
| 1942-1944 | label | fix | "Limited digital cable programming depending on provider" can only be explained or sent to the cable provider. Steps 4-5 (IR sensor, fluorescent lamps) are unrelated filler. | `user_fixable=false` (escalate to the provider). Or `troubleshootable=false`. Remove steps 4-5. |
| 1948-1950 | vague scenario / arbitrary label | fix | "Incorrect settings result in the inability to switch channels or inputs" names no specific symptom. Root cause 5 (Cable/Satellite box setup) is chosen only because it is "a setting". | Rewrite: "The GUIDE button on my remote doesn't show the cable box's program guide." Keep root 5 (Cable/Satellite box setup). Or point root to 6/7 for the channel/input wording. |
| 1993-1995 | label inconsistency | fix | "TV turned on by itself 45 minutes after being turned off" is something a user would report. It is labeled troubleshootable=false, while the analogous normal-behavior rows (1972 hot panel, 1975 popping) are true. | `troubleshootable=true`, root_cause_step=1, user_fixable=true. Note that the gold manual is ambiguous with Samsung_HD (2020). |
| 2020-2022 | label + leaked cause + invented step | fix | The scenario leaks the cause ("due to the OTA function"). Step 2 is LLM-invented ("may require ... contacting customer support") and does not come from the manual. user_fixable=false contradicts the manual ("It is normal"). Duplicates 1993 across manuals. | Rewrite: "My TV switched itself back on about 45 minutes after I turned it off." Set root_cause_step=1, user_fixable=true, and delete step 2. Or drop and keep 1993. |
| 2029-2031 | generic | fix | "Recurrent picture or sound issues that may require checking the signal/source" fits every TV manual, so retrieval is ambiguous. The scenario also contains the answer. | Rewrite: "My Samsung TV keeps having picture and sound problems on and off." Root 1. Or drop. |
| 1858-1860 | near-duplicate, not a symptom | minor | Overlaps 1849 (same TCL ventilation steps). "Poor ventilation when the TV is placed on a stand" is a tip, not a symptom. | `troubleshootable=false`, or drop. |
| 1867-1869 | filler steps | minor | Steps 3-5 (counterfeit accessories, installation sections, serial number) are LLM filler, not troubleshooting. The label (step 2, "noise is normal") is fine. | Trim to steps 1-2. |
| 1954-1956 | index vs numbering | minor | root_cause_step=6, but the visible list has 5 steps. Index 6 is the Auto Tuning menu-path sub-line. The text is correct. | None needed for the eval. Optionally repoint to "If your TV is not connected to a cable box ..., run Auto Tuning." |
| 1957-1959 | index vs numbering / plausibility | minor | Index 5 = visible step 4 ("check the connection between screen and Wireless One Connect"), which mostly restates the message. Step 1 (box turned off) or step 2 (adjust position) is the more concrete fix. | Consider root_cause_text = step 1 ("Check that the Wireless One Connect is not turned off ..."). |
| 2008-2010 | vague | minor | "Difficulties may arise when assembling the stand base" doesn't say what fails. | Rewrite: "I can't get the screws out of the TV to attach the stand base." Root 2. |
| 2047-2049 | not a malfunction | minor | Product registration on the Philips site is not a fault. Root "Confirm the email address" is hard to reach from the scenario. | Set `troubleshootable=false`, or rewrite: "I tried to register my TV online but registration never completed." Keep root 4. |

## Category-wide patterns

1. **Sony_LCD_TV.pdf has the wrong manifest title.** `sony-x90ch` is titled "Sony LCD TV Reference Guide (X90CH / BZ40H)", but the parsed PDF is "Installation Information for Using Sony Wall-Mount Bracket (SU-WL855)". There are no remote or picture sections in it. All 10 variants (1891-1918) are wall-mount safety warnings. 8 are already troubleshootable=false. 1903 and 1912 should follow (see table). Fix the manifest title, e.g. "Sony Wall-Mount Bracket SU-WL855 Installation Information". Also consider whether this manual belongs in the TV scenario set at all.
2. **LG_HD_TV.pdf is not a TV.** `lg-26ts30mf` is an LG MONITOR SIGNAGE manual (26TS30MF/47TS30MF, LVDS pin maps, scaler board). The manifest title "LG Monitor Signage" is right, but the file name (`LG_HD_TV.pdf`) and the category (Television) are misleading. Of its 10 variants, 5 are warnings or disclaimers (1876, 1882, 1885, 1888, plus the portrait warning 1873). Consider recategorizing, or keeping only 1864, 1867, 1870 and 1879.
3. **Samsung_HD.pdf and Samsung_HD2.pdf share the same troubleshooting table** (OTA power-on, small particles, PIP, plastic smell). Scenarios built from those rows (1993/2020, 1996/2023, 2017) have two valid gold manuals. Either dedupe them, or have the retrieval eval accept either Samsung doc for these rows.
4. **Junk solution_steps from the old generator:** two LLM refusals ("I'm sorry ...": 1945, 2053), two "I don't know." (2086, 2092), and one fabricated topic (1930). All should be dropped. Grep the whole dataset for `^I'm sorry|^I don't know` in solution_steps. Other categories probably have the same problem.
5. **Safety, warranty and installation warnings phrased as scenarios.** About 20 of the 90 variants (most of TCL 1852, Sony bracket 1891-1918, Sony2 1939, Samsung_HD 2032/2038, Toshiba 2083-2098). Most are correctly labeled troubleshootable=false, so the simulation excludes them. They still sit in the retrieval query set, and they are exactly the kind of queries no user sends. Consider excluding troubleshootable=false rows from the retrieval eval too.
6. **The scenario often leaks the root cause** ("... due to X", e.g. 1831, 1834, 1837, 1861, 2020, 2050, 2071, 2077). If the user simulator paraphrases the scenario, the agent is handed the answer and those tasks become trivial. That is acceptable for smoke tests, but it inflates success rates. When rewriting, prefer symptom-only phrasing (e.g. 2050 → "Apps on my Philips TV keep failing to load").
7. The `conversation` field (sampled rows 1831-1833) is coherent. No broad breakage.

---

## Vacuum — eval data review findings

- Variants reviewed: 100 (300 rows; 10 manuals x 10 variants x 3 tones; all three tones present for every variant)
- OK: 75 (of which 9 carry only a minor note)
- Needs fix: 17
- Should drop: 8

Already correctly labelled `troubleshootable=false` (no action): 1660, 1663, 1669, 1672, 1675, 1678, 1789, 1798, 1822, 1825, 1828.

## Problematic variants

Row ids are the first row of each 3-row group (all three tones share the issue).

| Rows | Issue type | Severity | What is wrong | Suggested change |
|---|---|---|---|---|
| 1534-1536 (Miele) | non-answer steps | drop | solution_steps is "I'm sorry, the manual ... does not contain specific troubleshooting steps". root_cause_step=1 points at that sentence, so the simulator cannot ever say "fixed". | Drop. Alternatively rewrite: steps = "Switch off at the wall socket and remove the plug" / "Press the rewind foot switch briefly" (p13) / "If the cable or rewind is damaged it must be replaced by Miele Service" (p3); root_cause_step=3, user_fixable=false. |
| 1636-1638 (Shark) | non-answer steps | drop | "I don't know. The manual does not provide..." Duster crevice tool "extend" is not in the manual (it's marketing text p3). | Drop. |
| 1648-1650 (Shark) | non-answer + hazard | drop | Steps = "I don't know." Scenario (loose internal electrical connections) is not in the manual and is a pro-only/mains-wiring issue. Old conversation tells the user to open the casing and push wires back. | Drop (or, if kept: user_fixable=false, step "Stop using it and contact SharkNinja support"). |
| 1627-1629 (Shark) | invented scenario / steps | drop | Accessory holder "not retaining attachments" is not a manual troubleshooting item; step 3 admits instructions are not in the manual. Root cause not guessable. | Drop. |
| 1633-1635 (Shark) | invented scenario / steps | drop | Crevice tool not fitting storage mount: steps are LLM padding (verify size, check orientation, check box flap); root_cause_step=4 "orient correctly" is arbitrary. | Drop. |
| 1705-1707 (Kenmore) | warranty text, not a symptom | drop | Scenario comes from the warranty exclusion ("damage ... discoloration or surface rust caused by the use of detergents..."). No user troubleshooting; root step "do not use non-recommended detergents" does not fix existing rust. | Drop (or troubleshootable=false). |
| 1708-1710 (Kenmore) | warranty text + near-duplicate of 1705 | drop | Same warranty clause as 1705, phrased as damage already occurred. | Drop. |
| 1765-1767 (Panasonic) | duplicate | drop | Same scenario as 1756 ("Beater bar does not turn because/due to a worn or broken belt"), same manual, same root step (loop new belt). | Drop one of 1756 / 1765. |
| 1540-1542 (Miele) | label points at non-step | fix | Only one numbered step; root_cause_step=2 refers to the unnumbered "(Note: ... consult the manufacturer's support...)". Step 1 is just usage. | Make the note an explicit step 2 ("Contact Miele Service if the release button stays stuck") so step 2 exists; keep user_fixable=false. |
| 1543-1545 (Miele) | speculative steps / unguessable label | fix | Steps quote unrelated text; root "check button is not stuck or obstructed" is not in the manual. The manual's real cause for an unresponsive radio-control handle is a flat handle battery (p20: replace CR 2032 approx. every 18 months). | Add step "Replace the 3 V CR 2032 battery in the radio-control handle" and set root_cause_step to it. |
| 1546-1548 (Miele) | speculative label | fix | root_cause_step=2 ("press Standby to turn Standby off") is not a documented cause; 9 padded steps. Same handle battery cause applies (+/- buttons are on the radio-control handle). | Same as 1543: add handle-battery step as root, trim padding; or drop as near-duplicate of 1543. |
| 1567-1569 (LG) | scenario/label mismatch | fix | Scenario is the manual's cause column ("power cord is unplugged") welded to the symptom, so the fix is step 1 (plug in the cord), but label says step 2 (clean terminals). | Either root_cause_step=1, or rewrite scenario to "The vacuum isn't charging on its station even though the charger is plugged in" and keep root_cause_step=2. |
| 1618-1620 (Bissell) | warning phrased as scenario | fix | "A polarized plug not fitting an outlet may require a qualified electrician..." is safety text. Also the same polarized-plug scenario exists for Shark 1642 and Dirt Devil 1732 (and Kenmore manual has identical text) -> retrieval ambiguous across 4 manuals. | Rewrite: "The plug won't go all the way into my wall outlet." Keep root=3. Consider keeping only one of 1618/1642/1732. |
| 1654-1656 (Dyson) | documentation note | fix | "Brush bar is not washable" is a care note (p12), not a malfunction. | troubleshootable=false (or drop). |
| 1657-1659 (Dyson) | documentation note | fix | "Filter needs more frequent washing in Boost mode" is a maintenance note; root step 2 ("tap the filter") is not the fix. | Rewrite scenario: "Suction has dropped after a lot of fine-dust vacuuming in Boost mode"; root_cause_step=3 (wash the filter unit in cold water). Or troubleshootable=false. |
| 1666-1668 (Dyson) | warning phrased as scenario | fix | Charging temperature range is a safety note; labelled troubleshootable=true. | Rewrite: "My V11 won't charge properly in my cold garage" with root_cause_step=1/2 (charge between 10-30 C), or troubleshootable=false. |
| 1681-1683 (Kenmore) | garbled step text | fix | Step 1 quotes "Plug in /g111/g85/g80/g79y, press ON/OFF switch." (font-glyph garbage). | Replace with manual text (p23): "Plug in firmly, press ON/OFF switch." |
| 1687-1689 (Kenmore) | garbled step text | fix | "3-way /g50/g81/g18/g50/g231 switch", "/g112/g82/g82/g85 brush". | "3-way On/Off switch should be in HARDFLOOR position" and "floor brush" (p14). |
| 1702-1704 (Kenmore) | not a manual item / wrong fixability | fix | "Breaker trips or fuse blows when the vacuum is used" is not in the Kenmore table (which lists breaker under "won't start"). An appliance that repeatedly trips the breaker is a possible electrical fault; resetting the breaker does not fix it. | Rewrite to "Vacuum won't start; the outlet seems dead" (root=3), or keep scenario with user_fixable=false (contact Sears service). |
| 1726-1728 (Dirt Devil) | usage warning | fix | "Brushroll damages flooring by being left in one location" is a caution, not a fault. | troubleshootable=false, or rewrite "My vacuum left a worn/burnished spot on the carpet" (root=1). |
| 1738-1740 (Dirt Devil) | usage warning | fix | "Sharp objects used to clean the hose cause damage" — a do-not instruction; avoiding sharp objects does not repair a damaged hose. | troubleshootable=false (or drop). |
| 1741-1743 (Panasonic) | scenario contradicts manual + pointer step | fix | Manual p21: the overload protector (MC-UL426 only) stops the nozzle motor; "the vacuum cleaner motor will continue to run". Table lists it under "Poor pick-up"/"Beater bar does not turn", not "won't run". Step 1 is only "Refer to ... page 21". | Scenario: "The beater bar stopped spinning but the motor keeps running (MC-UL426)." Steps: 1 Unplug mains lead; 2 Check nozzle for lint buildup/jamming and clean it; 3 Press the OVERLOAD PROTECTION RESET button on top of the nozzle, turn on. root_cause_step=3 (or 2). |
| 1777-1779 (Hoover) | cross-manual exact duplicate | fix | Scenario text is identical to Dirt Devil 1714 ("Dust escapes from the vacuum because the dirt cup is not installed correctly.") -> retrieval cannot pick the gold manual. | Add product detail, e.g. "Dust is leaking out of my cordless handheld; the dirt cup doesn't seem to sit right." (and similarly give 1714 its upright/release-button detail). |
| 1786-1788 (Hoover) | label | fix | Scenario: filter/separator not installed completely. Root step 7 (align dirt cup teeth) reseats the cup, not the filter/separator. | root_cause_step=3 ("place [separator] back into the dirt cup"), or add explicit step "Reinstall the filters and separator fully" and point root at it. |
| 1810-1812 (Eureka) | hazard signal vs label | fix | Scenario contains "burning smell" (hazard signal -> success expects escalated per spec §16), but label user_fixable=true / expected resolved. Contradictory outcome. | Decide one way: remove "A burning smell is detected" from the scenario (keep resolved, root=1), or keep it as a hazard case with user_fixable=false so expected = escalated. |

### Minor (counted as OK)

| Rows | Note |
|---|---|
| 1531, 1549, 1555 (Miele) | Three overheating-limiter variants share the same steps/root (clear blockage/dustbag). Same manual, so retrieval is fine, but they add little diversity. |
| 1579 (LG) | "Hot air ... as a result of the motor cooling" — informational; resolved means agent says "this is normal". Acceptable; scenario leaks the answer. |
| 1642, 1732 (Shark, Dirt Devil) | Polarized-plug duplicates of 1618 (see above). |
| 1729 vs 1720 (Dirt Devil), 1753 vs 1750 (Panasonic) | Near-duplicate pairs within one manual. |
| 1792, 1795 (Hoover) | Scenarios phrased as rules ("must be stored indoors", "cannot be used if it has a damaged cord"). Labels (escalated) are fine; rephrase as user reports: "It stopped working after being left out in the rain" / "The charger cord is frayed and it won't charge". |

## Category-wide patterns

1. **Cause leaked into the scenario.** Roughly half the scenarios are the manual's "Problem + Possible cause" row glued together ("... due to a full dust bin", "... because the power cord is not plugged in", "... due to a worn beater bar"). Retrieval is easy and the root-cause step is trivially guessable, which inflates resolution rate. Consider rewriting the cause clause out of the user-facing text (keep it in solution_steps) at least for the test split.
2. **Safety/warning text as scenarios.** Dyson (6 of 10 variants), Hoover (4), Eureka (3), Dirt Devil (3) and Kenmore warranty (2) draw from safety/warranty sections. Most are already troubleshootable=false; the remaining ones are listed above.
3. **LLM-padded "solution_steps" for invented scenarios** (Miele handle buttons, Shark accessory holder/crevice storage, Kenmore Pet PowerMate/wand): long steps that quote loosely related manual text plus the generator's own guesses. Labels on these are arbitrary.
4. **Non-answers**: 3 variants (1534, 1636, 1648) have "I don't know"-style steps; drop.
5. **Metadata**: consistent overall (company/manual/manifest agree; Dyson SV14 = V11 is correct). Only nit: company_name "DirtDevil" vs manifest "Dirt Devil". No duplicate PDF names.
6. **conversation field** (not used by evals): generally fine; 1648's dialogues coach the user to open the casing and reseat internal wires — another reason to drop that variant.

---

## WashingMachines — eval data review

- Variants reviewed: 100 (300 rows; all three tones present on every variant)
- OK: 73
- Needs-fix: 25 (17 fix, 8 minor)
- Should-drop: 2

Manuals: Samsung WD5100D (rows 1-30, and again as `WD5100D_WEB_IB_SU-PJT_COMBO-MD(1).pdf` rows 91-120), Samsung WD8000D / Laundry Combo (31-60), Samsung WW D-PJT (61-90), Samsung WF9400F (121-150), LG WM9900H (151-180), LG WM6998H washer/dryer combo (181-210), LG WM5500H (211-240), LG WM4000H (241-270), LG WM6700H (271-300).

## Problematic variants

| Rows | Issue type | Severity | What is wrong | Suggested change |
|---|---|---|---|---|
| 217-219 | Wrong product / scenario | drop | WM5500H is a washer-only model. The manual's odor entry says "(Dryer model only)" (p.53), so a dryer-heater odor cannot happen on this product. | Drop. (If kept, it would belong to a washer/dryer manual such as WM6998H.) |
| 232-234 | Wrong product / duplicate | drop | Same "(Dryer model only)" odor note as 217, on a washer-only model. It also near-duplicates 217 in the same manual, with a contradictory label (217 is troubleshootable=true, 232 is false). | Drop. |
| 13-15 | solution_steps from the wrong section | fix | The manual has a dedicated troubleshooting entry, "After a cycle, detergent remains in the detergent drawer" (p.55): sufficient water pressure, add detergent to the centre of the drawer, rinse cap inserted properly, granular detergent advice. The steps are the drawer-cleaning procedure instead, so the label (clean the recess) is not the manual's answer. | Replace the steps with the p.55 troubleshooting bullets and relabel. The likely root cause is "Make sure the rinse cap is inserted properly" or "add detergent to the centre of the drawer". |
| 22-24 | Scenario/steps/label mismatch | fix | The scenario says the supply hose is kinked or clogged, but the steps are the mesh-filter cleaning procedure plus a note. root_cause_step=5 (submerge the mesh filter) does not fix a kinked hose, so the simulator's user would say "fixed" for the wrong action. Also near-duplicates 25 and 7. | Change the scenario to "Water fills very slowly / information code 4C appears" (keep root 5), or keep the scenario and add the manual's step "Make sure the water supply hose is not kinked or clogged" as the root cause. |
| 28-30 | Warning text as a symptom | fix | Paraphrases the cleaning warnings ("do not use benzene..."). Discolouration that has already happened is not fixed by "use a soft cloth". | troubleshootable=false. |
| 58-60 | Label | fix | The scenario says the drain hose has already frozen. Step 1 is prevention ("make sure no water is left"). The fix is step 2: wrap the hose in a warm-water towel for about ten minutes. | root_cause_step=2. |
| 70-72 | Label index out of range | fix | There is only one numbered step; the rest is an unnumbered note. root_cause_step=2 points to the LLM note, not a manual step. This is normal behaviour (clicking = door-lock check). | root_cause_step=1. Optionally troubleshootable=false (normal operation, nothing to fix). |
| 73-75 | Normal behaviour as a symptom | fix | A quick drain before the wash is documented normal behaviour. The steps are a generic "does not start" list, and the label (close the door) has no link to the scenario. | troubleshootable=false, or rewrite the scenario to "makes clicking and draining sounds then does not start" with root "Make sure laundry is not caught in the door". |
| 145-147 | Policy text; fabricated steps | fix | The scenario is the warranty disclaimer ("domestic use only"). The steps are LLM paraphrase, not manual troubleshooting. No user reports this. | troubleshootable=false. |
| 148-150 | Warning text as a symptom | fix | From the safety-warning list ("do not place objects that generate electromagnetic fields"). Steps 2 and 3 are LLM-invented. A user cannot know that EMF is the cause. | troubleshootable=false. |
| 154-156 | Unsolvable | fix | Disclaimer text (app not in the local app store). The root step is literally "there are no specific troubleshooting steps", so the user simulator can never say "fixed". | troubleshootable=false (or drop). |
| 157-159 | Disclaimer as a symptom | fix | The root cause is a legal disclaimer ("may not operate due to local app store policy"), not an action. | troubleshootable=false. |
| 169-171 | Documentation note | fix | "Turning controls OFF does not disconnect power" is a safety note, not a malfunction. The identical scenario at 259 is already labelled troubleshootable=false. | troubleshootable=false (consistent with 259). |
| 187-189 | Fabricated root step | fix | Step 3 is LLM text ("specific steps... are not provided in the manual"). The manual's FAQ (p.55) says this is how Fresh Care works, i.e. normal. Fresh Care is an option you select via Options (p.37). The scenario also says "dryer"; the product is the WM6998H washer/dryer combo, which is fine. | root_cause_step=1 (explain it is the normal Fresh Care behaviour), or rewrite step 3 as "Do not select the Fresh Care option" and keep root 3. |
| 208-210 | Multi-problem scenario; inconsistent labels | fix | "Frozen water inlet or drain hoses" covers two problems. Its near-duplicate at 268 (WM4000H) uses root 10 (hot water in the drum, for the drain) while 208 uses root 4 (thaw the inlet hoses). | Split into one problem. For example, 208: "No water enters the washer in winter; the inlet hoses are frozen" (root 4). |
| 268-270 | Multi-problem scenario; inconsistent labels | fix | Same issue as 208. | Rewrite as "Washer won't drain in winter; the drain hose is frozen" (keep root 10). |
| 214-216 | Contradictory scenario | fix | Audible (sound-based) diagnosis does not use Wi-Fi, so "fails due to Wi-Fi unavailability" makes no sense. Root 1 ("launch the app") is not a fix. | Rewrite: "Audible Smart Diagnosis tones play but the app fails to receive the data." root = "Do not move the smartphone; keep it within 10 mm" (step 9). |
| 289-291 | Not a real symptom / pro-only | fix | "Fails to operate due to improper grounding" is derived from the grounding warnings. Grounding problems need an electrician. The comparable variant at 229 is troubleshootable=false, user_fixable=false. | troubleshootable=false (or user_fixable=false, expected escalated). |
| 295-297 | Wrong symptom; off-by-one label | fix | The manual lists clogged inlet filters under the "Water supply" error (p.48), not water leakage. The rationale describes removing debris and soaking, which is step 3, but the label is 4 (rinse and press back). | Scenario: "Washer shows a water supply error / fills very slowly." root_cause_step=3. |
| 16-18 | user_fixable questionable | minor | Frequent fuse blowing or breaker tripping is an electrical-fault signal. The steps themselves say "do not attempt to repair... contact service centre". | Consider user_fixable=false (expected escalated). |
| 34-36 | Inconsistent labels across near-duplicates | minor | "Clicking but fails to proceed": 4 → root door closed (2); 34 → laundry caught (10); 130 → door closed (2). Both are plausible. | Acceptable; ensure the simulator's semantic match accepts either, or align them. |
| 100-102 | Contradiction with near-duplicate | minor | Same manual content as 4: 4 treats clicking as a fault (door), 100 treats it as normal. Not wrong, but adds noise. | Keep as the "normal behaviour" case; consider troubleshootable=false. |
| 118-120 | Label inconsistency | minor | Labelled troubleshootable=false ("conditional note"), but it is the same real symptom as 49 (true). | troubleshootable=true, root 1. |
| 166-168 | Contrived scenario | minor | "Feature's form changed without prior notice" comes from a disclaimer; no user can report it. | troubleshootable=false. |
| 172-174 | Usage tip as a symptom | minor | Static from improper softener use; the root ("use only as recommended") is vague. | troubleshootable=false, or rewrite around the ezDispense not dispensing softener (root step 5). |
| 253-255 | Instruction as a symptom | minor | "Keep the drawer closed when not in use" is turned into "drawer does not remain closed". The root (don't slam it) does not fix a drawer that won't stay shut. | troubleshootable=false. |
| 262-264 | Maintenance tip as a symptom | minor | Dust on the plug pins is a safety and maintenance note; no observable malfunction. | troubleshootable=false. |

## Category-wide patterns

1. **Duplicate PDF.** Rows 91-120 use `WD5100D_WEB_IB_SU-PJT_COMBO-MD(1).pdf`, which is the same file as rows 1-30 (same sha256 `e75fa7aa…`; the manifest lists it as an alias of `samsung-wd5100d`). Retrieval is not broken, because the alias maps to the same doc, but the category double-weights one manual. Several variants are near-duplicates: 97≈10 (child lock), 103≈25 (mesh filter), 94≈7 (water supply), 91≈1 (no start), 106≈13 (detergent). Recommend normalising `appliance_name` to the canonical filename and deduplicating the near-identical scenarios.
2. **Generic cross-manual scenarios.** "Does not start after pressing Start" (1, 31, 61, 121), "insufficient water / clean mesh filter" (7, 37, 82, 94, 136), "low voltage" (43, 76, 127) and "Smart Diagnosis / Wi-Fi" (151, 181, 271, verbatim-identical text at 151 and 271) are almost word-for-word the same across manuals of the same brand. Retrieval Recall@5 for these will mostly measure brand-level, not model-level, discrimination. Consider adding model-specific details (display codes like "4C", model-specific button names such as "hold Temp.+Spin" vs. the Navigation dial).
3. **Safety and disclaimer text turned into scenarios.** Samsung manuals 109-117, 142-150 and LG 154-175, 229, 235-240, 259-265. Most are already troubleshootable=false. The ones still labelled true are listed above.
4. **Scenario gives away the answer.** Many scenarios state the cause outright (10, 19, 46, 67, 88, 97, 196, 220, 223, 226). They are trivially solvable, so fine for smoke testing but weak as discriminating eval tasks. Optionally rewrite them as symptoms (e.g. 220: "The ThinQ app can't find my washer during setup").
5. **LLM-paraphrased or invented steps.** Some solution_steps contain LLM commentary rather than manual text (145, 148, 154, 187, 226, 247 step 6). Watch these when a root_cause_step points at one.
6. **No hazard signals.** No scenario contains burning smell, smoke, sparks or gas. The fire and electric-shock mentions are all in warning-type variants labelled troubleshootable=false. No pro-only hazardous steps (mains wiring, casing removal) appear as root causes.
7. **Conversations.** The `conversation` field was sampled and looks well-formed.

---

## WaterPurifier findings

- Variants reviewed: 80 (240 rows; all three tones present on every variant)
- OK: 47
- Needs fix: 24 (12 fix, 12 minor)
- Should drop: 9

Manuals spot-checked against parsed JSON: bluewater (troubleshooting table p.13, control panel, low-pressure restart), aquafilter (model list), brita (indicator list, FAQ; there is **no** troubleshooting table), brondell2 (troubleshooting table p.20, LED indicator), Brondell.pdf/H630 (troubleshooting table), both Whirlpool manuals (troubleshooting tables). Steps generally do come from the right manual; the problems are mostly labels, invented scenarios, and duplicates.

## Problematic variants

| Row ids | Issue type | Severity | What is wrong | Suggested change |
|---|---|---|---|---|
| 2707-2709 | label | fix | root_cause_step=8 is "press and hold the Button for 3 s to reset the emergency stop". The rationale says "replacing both filters (step 8)", but filter replacement is step 6. | root_cause_step=6 |
| 2716-2718 | duplicate | drop | Same as 2707 (Pro 600, replace FILTER I and II). The manual has a single row for this case. | Drop it, or reuse the slot for the unused manual row "FILTER I or FILTER II is blocked -> low water flow" (fix: make sure nothing is blocking the filters, replace them if needed). |
| 2704-2706, 2713-2715 | scenario wording / label | minor | The scenarios are phrased as the cause ("The need to replace FILTER I when the water purifier signals"), which is not a user symptom. In 2713, root=1 only identifies the indicator; no step actually replaces the filter. | Scenario: "On my Bluewater Pro 400 the FILTER I (resp. FILTER II) light is on." For 2713, set root_cause_step=3 (replace per the Complete User manual), or add an explicit "Replace FILTER II" step. |
| 2710-2712 | label ambiguity | minor | The manual lists three fixes for low inlet pressure (correct tubing size, check the inlet line/grid filter/FILTER I, booster pump). Only the pump counts, and fitting a booster pump is arguably a plumber job. | Change the scenario to "Pro stops, inlet pressure too low even though the tubing and filters are fine" so the pump is the clear fix, or set root_cause_step=3. |
| 2728-2730 | label ambiguity | minor | The manual gives power-cycling (steps 1-2) and the 3 s button hold (step 3) as equal alternatives. An agent that suggests a power cycle would be scored as not fixed. | Merge steps 1-3 into one step, "Reset the emergency stop: power-cycle OR hold the Button 3 s", and use that as the root. |
| 2731-2733 | truncated step | minor | Step 12 reads "optimal performance pressure is 3.5." with the unit missing. | Change to "3.5 bar (52.5 psi)". |
| 2737-2739 | label | fix | The scenario is "cartridge does not fit properly". The manual's own remedy is step 5 ("If you cannot tightly screw the filter cap ... check if all o-rings and cartridge are positioned correctly"). | root_cause_step=5 |
| 2740-2742 | invented scenario / wrong rationale | drop | The manual never mentions a "tight membrane housing". The rationale says Teflon tape makes it too tight, but the manual tells you to apply multiple layers. The task cannot be solved in a principled way. | Drop. |
| 2755-2757 | troubleshootable | fix | This is a warranty disclaimer ("use only genuine parts"), not a reportable malfunction. | troubleshootable=false |
| 2758-2760 | filler steps / unsolvable | drop | "Adapter does not fit standard plumbing": the steps are filler (pressure regulator, model note), and the real answer (buy a 1/2" adapter or call an installer) is not in the steps. | Drop, or troubleshootable=false. |
| 2761-2763 | filler steps | minor | Steps 1-4 (authorized installer, heavy objects, do not open) do not address the indicator. The label (escalate, step 6) is fine. | Trim to steps 5, 6, 8. |
| 2767-2769 | invented error | fix | The manual has no "voltage mismatch error"; the display has no such indicator, so a user could not report it. | Scenario: "The Malfunction indicator is lit even though the purifier is plugged into a grounded 230 V outlet." Keep root=3, user_fixable=false. |
| 2770-2772 | label + wording | fix | The manual flow is: check feed water -> if it persists, switch off AND call Customer Care. Switching off is a safety step, not a fix. The manual names the indicator "No Inlet Water", not "feed water condition". | Scenario: "The No Inlet Water indicator stays on although the inlet valve is open." root_cause_step=3, user_fixable=false. |
| 2776-2778 | non-answer steps / vague | fix | solution_steps is an apology sentence ("I'm sorry, the manual does not provide..."). The scenario "indicator lights do not function as described" is vague. | Steps: "1. Call Customer Care 1800 2585 710." Scenario: "The display shows the Call Customer Care indicator." Keep it escalated. |
| 2779-2781 | not in manual / generic | drop | The Brita manual does not mention noise at all. The query "unusual noises" retrieves brondell2 (which says low pressure causes noise) rather than brita.pdf, so retrieval eval scores this as wrong. | Drop. |
| 2782-2784 | unsolvable label | drop | solution_steps = "I don't know...", root=1, user_fixable=True, so the agent can never propose the root step. "Leakage" is not covered by the manual (only in the warranty exclusions). | Drop (or steps "switch off, close inlet valve, call Customer Care", user_fixable=false). |
| 2785-2787 | non-answer steps | fix | The steps are an apology paragraph. The manual does give "Switch ON the power supply" and the Customer Care number. The scenario is also close to 2788. | Steps: "1. Make sure the power supply is switched ON. 2. Call Customer Care 1800 2585 710." Since the scenario says it is already plugged in: root=2, user_fixable=false. |
| 2791-2793 | invented symptom | fix | "Battery needs frequent replacement": the manual schedules a battery swap with every 6-month filter set. That is maintenance, not a fault. The root (battery orientation) is a guess. | troubleshootable=false, or replace it with the unused troubleshooting row "No water / low flow -- low incoming pressure -> verify >40 psi, install booster pump". |
| 2797-2799 | vague scenario | fix | "Indicator does not accurately signal" does not describe what the user sees. | Scenario: "The faucet LED flashes red instead of blue when I dispense water." Keep root=1 (change the filters and replace the battery). |
| 2800-2802 | troubleshootable | fix | "Users may forget to track filter changes" is a usage tip, not a symptom. | troubleshootable=false |
| 2806-2808 | meta complaint | drop | The scenario is a complaint about the manual, and the steps are "I don't know." It is already troubleshootable=false but adds noise to retrieval. | Drop. |
| 2809-2811 | scenario/steps mismatch | fix | The drain-clamp steps are about leaks, but the scenario says "water flow issues". | Scenario: "Water leaks at the drain clamp on the sink drain pipe after installation." Keep root=1. |
| 2839-2841 / 2857-2859 | inconsistent labels | minor | The same note (colder water means slower flow) is troubleshootable=true in UC300 (2839) and false in H630 (2857). The only "fix" in both is an explanation. | Make them consistent. Recommended: 2857 becomes troubleshootable=true with root=3 (replace filters, from the H630 "Low volume of filtered water" row) and a neutral scenario "Low volume of filtered water"; 2839 becomes troubleshootable=false. |
| 2842-2844 | invented causality | minor | The manual's "place on a level area" is a general caution and is not linked to leaks. | Consider troubleshootable=false, or root=4 (hose not fully inserted, the manual's leak row). |
| 2845-2847 | near-duplicate | minor | Same as 2827 (exhausted filters, replace them). | Keep it, but phrase it as a symptom: "Filtered water quality seems worse than before." |
| 2884-2886 | two-cause label | minor | Steps list two causes (missing vs plugged insert). Only step 1 counts, and 2890 and 2893 already cover each cause separately. | Accept either step, or drop 2884 as covered by 2890 and 2893. |
| 2896-2898 | duplicate | drop | Same troubleshooting row as 2887 (airgap drain side plugged/misconnected). | Drop. |
| 2929-2931 | duplicate | drop | Same as 2920 (tubing not cut square), with identical steps. | Drop. |
| 2932-2934 | duplicate / ambiguous | drop | Overlaps 2926 (drain line misconnected). Its steps merge four different leak causes, and root=4 is arbitrary. | Drop. |
| 2935-2937 | multi-problem | minor | "Poor water flow or leaks" names two problems. | Scenario: "Water leaks from the faucet airgap hole and the drain tube seems blocked." Keep root=1. |
| 2938-2940 | multi-problem / vague | fix | "Missing or improperly installed components leading to malfunction or leaks" is vague; root=3 (call for missing parts) only fits the "missing" reading. | Scenario: "Some parts on the packing list are missing from the carton." Steps 1-3 only; keep root=3, user_fixable=false. |

## Category-wide patterns

1. **brita.pdf has no troubleshooting section.** Six of its 10 scenarios (2767, 2776, 2779, 2782, 2785, plus the filler in 2761) were invented, and their steps are non-answers or filler. These generic symptoms (noise, leak, won't power on) fit every purifier manual, so retrieval is ambiguous. Keep at most the indicator, Wi-Fi, feed-water and power rows, rewritten to match the manual's real indicator names (No Inlet Water, Malfunction, Call Customer Care, Replace Filters/RO, High TDS).
2. **Warning/spec rows.** About 20 variants are, or should be, troubleshootable=false (bluewater 2725; aquafilter 2743, 2746, 2755, 2758; brondell2 2800, 2803, 2806, 2812, 2815, 2818; H630 2857, 2866, 2872, 2875, 2878; Whirlpool 2899, 2902, 2905, 2908). brondell2.pdf has 4-6 non-troubleshootable slots out of 10 but an unused troubleshooting table on p.20: TDS meter not reading zero, low flow from low pressure (booster pump), tank capacity exhausted, plumbing restriction. These are good replacements. The Whirlpool manuals also have unused rows, such as "storage tank air-charge less than 5-7 psi -> pressurize to 6 psi".
3. **The two Whirlpool manuals (whirlpool_whapspro.pdf / WHAPSRO and whirlpool_whar.pdf / WHAROS5) share an almost identical troubleshooting table.** Scenarios 2884/2890/2893 vs 2911/2914 and 2887/2896 vs 2917/2926 are textually the same problem, so retrieval cannot tell the gold manual apart (MRR noise). Add the model to each scenario ("My Whirlpool WHAPSRO RO system...") or accept either Whirlpool manual as gold for these rows.
4. **Bluewater scenarios are written as causes or table cells rather than user symptoms** (2704, 2707, 2713, 2716, 2719). Retrieval is fine, but the simulator persona is awkward. Rewrite them as "light X is on / the unit stopped".
5. **Metadata (minor).** company "AquaFilter" vs the manifest's "Aquafilter". The manifest product_name values "Aquafilter Installation Manual" and "Reverse Osmosis Water Filtration System" (whirlpool-wharos5) lack a model or brand; suggest "Aquafilter FP3 Series Filtration System" and "Whirlpool WHAROS5 Reverse Osmosis Water Filtration System". The manual-to-category mapping is otherwise correct, and there are no duplicate PDFs.
6. **No hazard signals** (smoke, burning, gas) appear in any scenario, and no step tells the user to do anything dangerous. The steps that call for pros (H630 plumber, Brita service rep) are correctly labelled user_fixable=false.
7. **The conversation field** (sampled) is coherent. All three tones are present on every variant.
