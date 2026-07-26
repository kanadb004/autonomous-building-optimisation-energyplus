"""Minimal IDF text patching -- avoids a full IDF-parser dependency for the
one thing Phase 2+ needs: swapping the `RunPeriod` window so dev/demo/season
variants don't require hand-maintained IDF copies (§2 Phase 4.4 calls run
period out as "a single config value").
"""

from pathlib import Path


def with_run_period(idf_path, begin_month: int, begin_day: int, end_month: int, end_day: int, output_path) -> Path:
    """Write a copy of `idf_path` to `output_path` with the `RunPeriod`
    object's Begin/End Month/Day fields replaced. Fails loudly if the
    `RunPeriod,` object can't be found, rather than silently no-op-ing."""
    lines = Path(idf_path).read_text().splitlines(keepends=True)

    start = None
    for i, line in enumerate(lines):
        if line.strip() == "RunPeriod,":
            start = i
            break
    if start is None:
        raise RuntimeError("RunPeriod object not found in IDF -- cannot patch run period")

    end = None
    for i in range(start + 1, len(lines)):
        if ";" in lines[i]:
            end = i
            break
    if end is None:
        raise RuntimeError("RunPeriod object has no terminating ';' -- malformed IDF")

    # Fields, in order, after the object keyword line: Name, Begin Month,
    # Begin Day of Month, Begin Year, End Month, End Day of Month, ...
    field_lines = lines[start + 1 : end + 1]
    replacements = {1: begin_month, 2: begin_day, 4: end_month, 5: end_day}

    patched_field_lines = []
    for idx, line in enumerate(field_lines):
        if idx in replacements:
            value_part, sep, comment_part = line.partition("!-")
            terminator = ";" if ";" in value_part else ","
            new_line = f"    {replacements[idx]}{terminator}"
            if sep:
                new_line += "  !-" + comment_part
            elif not new_line.endswith("\n"):
                new_line += "\n"
            patched_field_lines.append(new_line if new_line.endswith("\n") else new_line + "\n")
        else:
            patched_field_lines.append(line)

    new_lines = lines[: start + 1] + patched_field_lines + lines[end + 1 :]

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(new_lines))
    return output_path
