# Complete merged delivery proof for #788 and #790

Additive proof repairs evidence gaps after merged #789/#791. Historical packets remain unchanged: some XML has unescaped redaction placeholders and original revision hashes do not bind later merged changes. This supplement binds actual merged main4fc45bf02eeae19c37221d91145a3be1e47ebdf4 including both deliveries.

Actual invocation from that tree: `uv run --locked --extra dev pytest --junitxml=$ROUND/faa790-full.xml`. Exit0: **2277 passed,12 skipped,89.09% coverage**. Twelve pre-existing opt-in/live/acquisition/sample/calibration skips remain. Full log and valid XML retained. XML is parsed before metadata redaction and after serialization; only local paths/hostname metadata change.

Manifest membership replay: original immutable API and count-only mutation each yield3 assertion failures; exact restoration yields3 passes. Fresh real HTTP smoke with CSV/directory loading and actual manifest builder: equal counts with work-b missing/retired extra are unhealthy, builder exits0, then differences are empty/healthy. See smoke.json and mutation-receipt.json.

Monochrome replay: forced-color pixels6FAIL/3PASS, restored9PASS; omitted strategy ETag3FAIL, restored3PASS; omitted fit ETag6FAIL/13PASS, restored19PASS. All sources restored byte-identically. Fresh valid red/green JUnit and logs retained. Full suite ran before mutations on identical restored bytes. Inspected source: card evidence appended after atomic file replacement; strategy selected before reduced decode/fit; feed entry points share strategy-aware rendering; native palette guards remain active; API reports use writer evidence.

Provider comparisons for #789/#791 remain CONCERNS from incomplete input. This packet supplies independently inspectable proof, does not relabel provider verdicts, establish physical fidelity/deployment or close sources before review and verifier disposition. Production code, dependencies and lock bytes are unchanged.

Fresh exact original monochrome source5a236579ab0becd260e717c7497c3023af614000 against the current delivery regressions yields11 assertion failures, zero errors/skips. `monochrome-original-red.xml` is valid XML; `monochrome-receipt.json` binds all five original/corrected source files and the actual final test file. Corrected source is restored byte-identically; the restored strategy/ETag and full-suite gates above use those same current bytes.
