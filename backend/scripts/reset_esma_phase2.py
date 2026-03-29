"""Reset ESMA Phase 2 checkpoint so ISINs can be re-resolved with API key."""
import json
from pathlib import Path

checkpoint_file = Path(".esma_seed_checkpoint.json")
if not checkpoint_file.exists():
    print("No checkpoint found")
    exit()

cp = json.loads(checkpoint_file.read_text())
resolved_count = len(cp.get("phase2_resolved", []))
print(f"Clearing {resolved_count} phase2_resolved entries (keeping phase1_complete=True)")

cp["phase2_resolved"] = []
cp["phase3_backfilled"] = []
cp["phase4_complete"] = False

checkpoint_file.write_text(json.dumps(cp, indent=2))
print("Done. Run: populate_seed --resume --openfigi-key <key>")
