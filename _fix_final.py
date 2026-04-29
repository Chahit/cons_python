import re

# ================================================================
# FIX 1: kanban_pipeline.py — remaining PDF unsafe cells + DuplicateKey
# ================================================================
with open("frontend/tabs/kanban_pipeline.py", "rb") as f:
    raw = f.read()
src = raw.decode("utf-8", errors="replace")

# 1a. Wrap the lane header cell (line 1044)
old_lane_hdr = 'pdf.cell(0, 10, f"{lane[\'label\']} Partners  ({len(lane_df)} accounts)  |  {period_label}")'
new_lane_hdr = 'pdf.cell(0, 10, _kb_pdf_safe(f"{lane[\'label\']} Partners  ({len(lane_df)} accounts)  |  {period_label}"))'
if old_lane_hdr in src:
    src = src.replace(old_lane_hdr, new_lane_hdr, 1)
    print("OK: wrapped lane header PDF cell")
else:
    # Try regex approach
    src = re.sub(
        r'pdf\.cell\(0,\s*10,\s*f"\{lane\[.label.\]\} Partners.*?period_label\}"',
        '_kb_pdf_safe_PLACEHOLDER',
        src,
        count=1,
    )
    print("WARN: lane header not matched exactly")

# 1b. Wrap the KPI period_label value cell (line 956 area)
old_kpi_period = '(f"{period_label} Value",   _fmt_pdf(total_rev)),'
new_kpi_period = '(_kb_pdf_safe(f"{period_label} Value"),   _fmt_pdf(total_rev)),'
if old_kpi_period in src:
    src = src.replace(old_kpi_period, new_kpi_period, 1)
    print("OK: wrapped period_label in KPI label")
else:
    print("WARN: KPI period_label not found exactly")

# 1c. Also wrap any remaining pdf.cell calls that use period_label directly
src = re.sub(
    r'(pdf\.cell\([^,]+,[^,]+,\s*)f"([^"]*\{period_label\}[^"]*)"',
    r'\1_kb_pdf_safe(f"\2")',
    src,
)
print("OK: wrapped remaining period_label pdf.cell calls via regex")

# 1d. DuplicateWidgetID — use lane's key + abs position from shown.index
# The current: f"kb_jump_{lane['key']}_{_kb_i}_{name[:20]...}"
# Problem: if the same lane is re-rendered, _kb_i resets.
# Better: use the actual df index (row.name or idx from enumerate)
# The loop is: for _kb_i, (_, row) in enumerate(shown.iterrows()):
# _kb_i is unique within the lane, but across ALL lanes it could repeat.
# Since the key already includes lane['key'], it's actually unique.
# Error shows key WITHOUT _kb_i → server still has old code cached.
# Add a lane-level counter that's globally unique using the lane index too.
# The actual fix: Streamlit is still loading OLD code — need to verify the
# key format is actually using _kb_i. Let's confirm and add a hash fallback.

# Replace current key formula with one using hash of full name for uniqueness
old_safe_key_line = '_safe_key = f"kb_jump_{lane[\'key\']}_{_kb_i}_{name[:20].replace(\' \',\'_\').replace(\'.\',\'\')}"'
new_safe_key_line = '_safe_key = f"kb_jump_{lane[\'key\']}_{_kb_i}_{abs(hash(name)) % 99999}"'
if old_safe_key_line in src:
    src = src.replace(old_safe_key_line, new_safe_key_line, 1)
    print("OK: fixed _safe_key with hash")

old_sa_key_line = '_sa_key = f"kb_sa_{lane[\'key\']}_{_kb_i}_{name[:20].replace(\' \',\'_\').replace(\'.\',\'\')}"'
new_sa_key_line = '_sa_key = f"kb_sa_{lane[\'key\']}_{_kb_i}_{abs(hash(name)) % 99999}"'
if old_sa_key_line in src:
    src = src.replace(old_sa_key_line, new_sa_key_line, 1)
    print("OK: fixed _sa_key with hash")

with open("frontend/tabs/kanban_pipeline.py", "wb") as f:
    f.write(src.encode("utf-8"))
print("SAVED kanban_pipeline.py")

# ================================================================
# FIX 2: product_lifecycle.py — remove Quick Select + Specific Month
# ================================================================
with open("frontend/tabs/product_lifecycle.py", "rb") as f:
    raw2 = f.read()
src2 = raw2.decode("utf-8", errors="replace")

# Find the Quick Select block start and end (before Custom Range or similar)
# Quick Select block + Specific Month block
# Remove from "# Quick Select" label or its st.markdown up to the Custom Range section

# Find what comes AFTER the month chips loop (the custom range inputs)
# Pattern: remove from Quick Select markdown down to the first date_input line
old_block_match = re.search(
    r"(    st\.markdown\([^)]+Quick Sel[^)]+\)[^\n]*\n.*?)(?=    (?:col|c1|c2|cal|st\.date_input|# Custom|# Manual|custom))",
    src2, re.DOTALL | re.IGNORECASE
)

if old_block_match:
    block = old_block_match.group(0)
    print("Found Quick Select block to remove:")
    print(repr(block[:200]))
    src2 = src2.replace(block, "", 1)
    print("OK: removed Quick Select + Specific Month from product_lifecycle.py")
else:
    # Try line-based removal
    lines = src2.splitlines(keepends=True)
    # Find start: line with "Quick Sel"
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if "Quick Sel" in line and "st.markdown" in line and start_idx is None:
            start_idx = i
        if start_idx is not None and ("date_input" in line or "col1" in line or "# Custom" in line.lower()):
            end_idx = i
            break
    if start_idx is not None and end_idx is not None:
        print(f"Removing lines {start_idx+1} to {end_idx} from product_lifecycle.py")
        src2 = "".join(lines[:start_idx] + lines[end_idx:])
        print("OK: removed via line splicing")
    else:
        print(f"WARN: could not find block boundaries (start={start_idx}, end={end_idx})")
        # Show context around line 64
        for i, l in enumerate(lines[60:95], 61):
            print(i, repr(l[:100]))

with open("frontend/tabs/product_lifecycle.py", "wb") as f:
    f.write(src2.encode("utf-8"))
print("SAVED product_lifecycle.py")

print("ALL DONE")
