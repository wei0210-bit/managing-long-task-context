#!/usr/bin/env bash
# Reproduce the CI "printf: write error: Broken pipe" false failure (run 35175710471, attempt 1).
#
# Usage: ci-epipe-reproduction.sh CI_YML CAPTURED_OUTPUT [REAL_ITERATIONS] [SYNTHETIC_ITERATIONS]
#
# Executes the exact "Ran N tests" check lines found in CI_YML the way GitHub Actions runs a
# `shell: bash` step (bash --noprofile --norc -eo pipefail), with `output` assigned by command
# substitution as in the workflow.
#   synthetic: match on the first line followed by a 1 MiB tail, so `grep -q` exits while the
#              writer still has bytes left (deterministic for a pipe writer)
#   real:      a captured complete-package unittest output, repeated (probabilistic for a pipe writer)
#   controls:  outputs that must be rejected or accepted, proving the check was not weakened
# Exit status: 0 GREEN, 1 RED, 2 MIXED, 3 extraction or control error.
set -u

ci_yml=$1
captured=$2
real_iterations=${3:-1000}
synthetic_iterations=${4:-20}
pattern="grep -Eq '^Ran [1-9][0-9]* tests'"
work=$(mktemp -d "${TMPDIR:-/tmp}/ci-epipe.XXXXXX")
trap 'rm -rf "$work"' EXIT

grep -nF -- "$pattern" "$ci_yml" > "$work/lines"
line_count=$(wc -l < "$work/lines" | tr -d ' ')
if [ "$line_count" -ne 3 ]; then
  echo "extraction: expected 3 check lines, found $line_count" >&2
  exit 3
fi
test -s "$captured" || { echo "captured output is missing or empty" >&2; exit 3; }

{
  printf 'Ran 7 tests in 0.100s\n'
  head -c 1048576 /dev/zero | tr '\0' 'x' | fold -w 99
} > "$work/synthetic"
printf 'OK\n' > "$work/no-ran-line"
printf 'Ran 0 tests in 0.000s\n\nOK\n' > "$work/ran-zero"
printf '  Ran 5 tests in 0.100s\n\nOK\n' > "$work/ran-indented"
printf 'Ran 12 tests in 0.100s\n\nOK\n' > "$work/ran-twelve"

# run_check SIGPIPE_MODE CHECK_LINE OUTPUT_FILE STDERR_FILE -> exit status of the step body
run_check() {
  local body
  body=$(printf 'output="$(cat "$REPRO_OUTPUT_FILE")"\n%s\n' "$2")
  if [ "$1" = ignored ]; then
    REPRO_OUTPUT_FILE=$3 REPRO_BODY=$body bash -c 'trap "" PIPE; exec bash --noprofile --norc -eo pipefail -c "$REPRO_BODY"' 2>> "$4" >/dev/null
  else
    REPRO_OUTPUT_FILE=$3 bash --noprofile --norc -eo pipefail -c "$body" 2>> "$4" >/dev/null
  fi
}

synthetic_runs=0 synthetic_failures=0 real_runs=0 real_failures=0 control_errors=0
while IFS= read -r numbered; do
  number=${numbered%%:*}
  check=$(printf '%s' "${numbered#*:}" | sed 's/^[[:space:]]*//')
  echo "line $number: $check"
  for mode in default ignored; do
    failures=0
    : > "$work/stderr"
    i=0
    while [ "$i" -lt "$synthetic_iterations" ]; do
      run_check "$mode" "$check" "$work/synthetic" "$work/stderr" || failures=$((failures + 1))
      i=$((i + 1))
    done
    broken=$(grep -c 'Broken pipe' "$work/stderr" | tr -d ' ')
    echo "  synthetic sigpipe=$mode failures=$failures/$synthetic_iterations broken_pipe_messages=$broken"
    synthetic_runs=$((synthetic_runs + synthetic_iterations))
    synthetic_failures=$((synthetic_failures + failures))
  done
  failures=0
  : > "$work/stderr"
  i=0
  while [ "$i" -lt "$real_iterations" ]; do
    run_check ignored "$check" "$captured" "$work/stderr" || failures=$((failures + 1))
    i=$((i + 1))
  done
  broken=$(grep -c 'Broken pipe' "$work/stderr" | tr -d ' ')
  echo "  real sigpipe=ignored failures=$failures/$real_iterations broken_pipe_messages=$broken"
  real_runs=$((real_runs + real_iterations))
  real_failures=$((real_failures + failures))
  for control in no-ran-line:reject ran-zero:reject ran-indented:reject ran-twelve:accept; do
    name=${control%%:*} expected=${control#*:}
    if run_check ignored "$check" "$work/$name" /dev/null; then actual=accept; else actual=reject; fi
    echo "  control $name expected=$expected actual=$actual"
    [ "$actual" = "$expected" ] || control_errors=$((control_errors + 1))
  done
done < "$work/lines"

if [ "$control_errors" -ne 0 ]; then
  verdict=CONTROL_ERROR status=3
elif [ "$synthetic_failures" -eq "$synthetic_runs" ]; then
  verdict=RED status=1
elif [ "$synthetic_failures" -eq 0 ] && [ "$real_failures" -eq 0 ]; then
  verdict=GREEN status=0
else
  verdict=MIXED status=2
fi
printf '{"verdict": "%s", "check_lines": %s, "synthetic_failures": %s, "synthetic_runs": %s, "real_failures": %s, "real_runs": %s, "control_errors": %s, "bash": "%s"}\n' \
  "$verdict" "$line_count" "$synthetic_failures" "$synthetic_runs" "$real_failures" "$real_runs" "$control_errors" "$BASH_VERSION"
exit "$status"
