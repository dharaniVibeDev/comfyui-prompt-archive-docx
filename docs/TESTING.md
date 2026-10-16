# Testing

## Automated tests

Use the Python interpreter from the ComfyUI environment, from the repository root:

```sh
python -B -m unittest discover -s tests -p "test_*.py" -v
```

All **11 tests passed** during release preparation:

- Six existing archive tests cover DOCX text/preview contents, reopening SQLite, workflow filtering, capture from linked primitives, camera/lighting sections, graph identity across widget-input compaction, zero conditioning, and unsupported text transforms.
- Five package tests cover imports and registration, frontend file inclusion, disabled archiving, two-image saving/persistence, output-root containment, and invalid preview controls.

These tests use temporary directories. The package-import tests provide minimal ComfyUI host stubs; they do not pretend to execute a diffusion model or replace a real ComfyUI integration test.

## Verified host

The release staging copy was installed under a separate temporary ComfyUI base directory, with its own input/output/user folders and an in-memory ComfyUI application database. It shared the existing Python environment without changing installed packages.

| Component | Verified version |
| --- | --- |
| ComfyUI | 0.38.0 |
| Frontend | 1.53.10 |
| Python | 3.13.16 |
| NumPy | 2.5.3 |
| Pillow | 12.3.0 |
| aiohttp | 3.14.3 |
| OS | Windows |

The actual ComfyUI server imported and registered `PromptArchiveDOCX` and served all five frontend assets. A CPU `EmptyImage → Prompt Archive DOCX` run saved two 256×128 image records. Their DOCX archives passed ZIP/XML checks, contained one JPEG and no workflow JSON or PNG, and downloaded byte-for-byte identically to disk. Those simple flat-color test documents were 2,687 and 2,688 bytes; this is not a general document-size benchmark.

No fresh checkpoint, LoRA or diffusion-model generation was performed for this release test. Earlier local development tested real Krea/KSampler workflows, but that does not establish compatibility with every checkpoint loader or custom sampler. Linux/macOS desktop integration was not tested.

## Browser checks and screenshots

The real frontend was tested with isolated, sanitized verification records and a browser-only matching workflow. No saved production workflow was modified.

Verified actions:

- Load the thumbnail gallery, filter by current/individual workflow, and show a search empty state.
- Inspect a selected archive and its stored prompts/settings.
- Show three current-versus-archived differences without changing values.
- Cancel without changing the graph; require an explicit checkbox before confirmation.
- Confirm reload and verify the same graph ID/object, node identities/count and root/nested connections, with sampler steps restored to 2.

The four WebP files in `docs/screenshots/` are optimized captures of that actual interface. They use neutral documentation copies of verification records; local paths were masked and image metadata was stripped. Original DOCX files, databases, images, private workflows, local test logs and machine-specific verification scripts are intentionally excluded.

## Repeating a real-host check

Use a separate ComfyUI base directory and install this package in that base's `custom_nodes` folder. Start that instance with `--base-directory`, its own port, `--cpu` and `--database-url sqlite:///:memory:`. Do not point test output at an existing production archive.

Connect a built-in Empty Image node to Prompt Archive DOCX, set batch size 2, and queue it. Verify two documents and two SQLite records. For reload checks, archive a workflow with supported editable widgets, change a value in the same graph, inspect the comparison, cancel once, then review and confirm. Node count and connections should remain unchanged. Do not use private prompts or production images for screenshots or public test fixtures.
