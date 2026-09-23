# Submit a pull request

A worked example, start to finish, using a change that is actually in this
repository's history: commits
[`bb37d57`](https://github.com/diogopelinson/edgesentinel/commit/bb37d57) and
[`09277cb`](https://github.com/diogopelinson/edgesentinel/commit/09277cb). You
can check every claim on this page against `git log`.

The conventions themselves are in [CONTRIBUTING.md](../../CONTRIBUTING.md);
this page shows them applied.

## 0. The bug

While writing documentation, a command in `AGENTS.md` turned out to do nothing:

```bash
$ python -m cli.main doctor
$ echo $?
0
```

No output, no error, exit 0. `edgesentinel doctor` worked, so the CLI itself
was fine — the module path was not. That matters because the console scripts
in a virtualenv embed the absolute path of the directory the venv was created
in, and stop working when the project moves; `python -m` is the documented way
out.

## 1. Branch

One branch per change, named after the roadmap feature it delivers. This was a
fix with no roadmap entry, so it rode along in the branch that found it. On its
own it would have been:

```bash
git checkout -b fix/python-m-entry-point
```

## 2. Write the failing test first

Before the fix. The point is not ceremony: a test written after the fix proves
that the code does what it does, while a test written before proves it catches
the bug.

```python
def test_the_module_can_be_run_with_dash_m():
    """
    O console script do venv embute o caminho absoluto de onde o venv foi
    criado e quebra quando o projeto muda de pasta. 'python -m cli.main' é a
    saída documentada para esse caso — e só funciona com o bloco __main__.
    """
    import subprocess

    from cli import __version__

    resultado = subprocess.run(
        [sys.executable, "-m", "cli.main", "--version"],
        cwd=ROOT, capture_output=True, text=True,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == f"edgesentinel {__version__}"
```

Run it and watch it fail, with the failure you expected:

```
E       AssertionError: assert '' == 'edgesentinel 0.3.0'
E         - edgesentinel 0.3.0
1 failed, 8 passed
```

Empty output — exactly the bug, now pinned.

## 3. Commit the test, alone

```bash
git add tests/cli/test_version.py
git commit
```

```
test(cli): require the module to run with python -m

The console scripts in a venv embed the absolute path of the directory
the venv was created in, and stop working when the project moves -
which is exactly the state of this checkout. "python -m cli.main" is the
documented way out, and it silently did nothing: no __main__ block, so
the module was imported and the process exited 0 with no output.

The test runs it as a subprocess and compares the output of --version
with cli.__version__, so it also pins the two entry points to the same
version string.
```

The subject says what, in English and in the imperative. The body says **why**
— the diff already shows what changed. No `Co-Authored-By` or other
attribution trailers.

## 4. Make it pass

```diff
--- a/cli/main.py
+++ b/cli/main.py
@@ -150,4 +150,8 @@ def _setup_logging(level: str) -> None:
         level=getattr(logging, level),
         format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
         datefmt="%Y-%m-%d %H:%M:%S",
-    )
\ No newline at end of file
+    )
+
+
+if __name__ == "__main__":
+    main()
```

Four lines. That is normal: most of the work was knowing which four.

Commit it separately, because **one commit touches one file**:

```
fix(cli): make python -m cli.main run the CLI

Adds the __main__ block. Without it, the module was imported, main()
was never called, and the process exited 0 having printed nothing -
"edgesentinel doctor" and "python -m cli.main doctor" behaved
differently, and only the first one was ever tried.

prog is already fixed to "edgesentinel" in the parser, so both paths
print the same help and the same version.
```

## 5. Prove the test can fail

The step that separates a suite from a suite that is merely green. Break the
code the test covers, on purpose, and watch the test fail:

```bash
# comment out the __main__ block
python -m pytest tests/cli/test_version.py -q
# 1 failed  ← good: the test is doing its job
git checkout cli/main.py
```

If the test still passes against broken code, it is not testing what you think,
and fixing that now is cheaper than discovering it during an incident. For
bigger changes, script it — several mutations, each asserting that the intended
test breaks.

## 6. Update what the change touched

In the same branch:

- the docs that mention the area — `docs/reference/cli.md` for this one;
- `CHANGELOG.md`, under `[Unreleased]`;
- `docs/roadmap.json`, if the change delivers a feature: mark it `done` with
  the merge SHA and promote whatever it unlocked;
- the Portuguese mirrors, `README-BR.md` and `USAGE-PTBR.md`, when the English
  side changed.

Each of those is its own commit.

## 7. Open the pull request

The template asks four things. Filled in for this change:

> ## What this changes
>
> `python -m cli.main` was importing the module and exiting 0 without running
> anything, because there was no `__main__` block. That path is the documented
> workaround for a venv whose console scripts broke — which is the state of any
> checkout that has moved directory since the venv was created — so the
> workaround did not work either.
>
> ## Roadmap
>
> None. Bug found while writing `AGENTS.md`, which documents that command.
>
> ## How it was verified
>
> `pytest tests/ -q` — 370 passed. The new test fails against the unfixed
> code with `assert '' == 'edgesentinel 0.3.0'`, and I re-ran it with the
> `__main__` block commented out to confirm it still fails.
>
> ## Checklist
>
> - [x] `pytest tests/ -q` is green
> - [x] New tests fail against the unfixed code (mutation-checked)
> - [x] Docs updated in this branch — `docs/reference/cli.md`
> - [x] `CHANGELOG.md` updated under `[Unreleased]`
> - [ ] `docs/roadmap.json` reflects reality — not a roadmap feature
> - [x] One file per commit, English messages, no attribution trailers

Unchecked boxes are fine when the reason is written next to them. An unchecked
box with no explanation is the only kind that costs a review round.

## 8. What happens next

The pipeline runs the suite on Ubuntu with Python 3.10 through 3.13 and on
Windows with 3.10. A review will look at, roughly in this order:

1. **Does the test fail without the fix?** If the answer is not in the PR, it is the first question.
2. **Is the failure mode understood?** "It silently exited 0" is an explanation; "it was broken" is not.
3. **Does anything else make the same mistake?** Here: is there another entry point with no `__main__`?
4. **Did the docs that describe this behaviour change with it?**
5. **Style and layering** — last, because it is the cheapest thing to fix and the least likely to matter.

Small, well-explained pull requests are merged quickly. A large one is not
refused, but expect to be asked what the smallest version of it would look
like.

## A shorter checklist

```bash
git checkout -b fix/something            # or feat/<roadmap-id>
# write the failing test, watch it fail
git add <test file> && git commit        # one file
# write the fix, watch it pass
git add <source file> && git commit      # one file
# break the source on purpose, confirm the test fails, restore it
# update docs, CHANGELOG, roadmap — one commit each
pytest tests/ -q
git push -u origin fix/something
gh pr create                             # fill in the template
```
