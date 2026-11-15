# Visio Export Flow

> **Command paths:** `${SKILL_DIR}` in the command examples below is a placeholder for the installed skill's base directory, not a built-in variable. Set it once before running the commands (see the "Resolving `${SKILL_DIR}`" section in `SKILL.md`). Keep the current working directory in your workspace and invoke scripts through that anchored path, because they import sibling modules by filename.

## Prerequisites

- Windows
- Microsoft Visio desktop installed locally
- Python environment with `pywin32`

## Pipeline

1. Prepare or refine `scene.json`
2. Validate:

```powershell
python ${SKILL_DIR}\scripts\scene_validate.py <scene.json>
```

3. Render and export:

```powershell
python ${SKILL_DIR}\scripts\scene_to_visio.py <scene.json> --output-dir <exports>
```

Optional style override:

```powershell
python ${SKILL_DIR}\scripts\scene_to_visio.py <scene.json> --output-dir <exports> --style-profile clean_white
```

## Expected Outputs

The renderer writes:
- `<name>.vsdx`
- `<name>.svg`
- `<name>.png`

By default the basename comes from the input scene filename.

## Current V1 Limitations

- connectors support explicit `points` and right-angle routing, but are not yet fully glued ShapeSheet connectors
- basic flowchart masters are used when the local Visio stencil is available, with primitive fallback
- export depends on local Visio behavior, which can vary by Office version

These are acceptable for a first reusable skill because the schema and renderer boundary are already correct.

## Debug Priorities

If rendering fails, check in this order:

1. `scene.json` schema validity
2. `pywin32` import availability
3. Visio COM launchability
4. asset file path validity
5. export permission or save path issues
