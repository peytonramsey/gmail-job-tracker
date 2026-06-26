# Tiny zero-dependency test runner shared by the test modules — the project
# intentionally does not depend on pytest. Run a suite with: python tests/test_*.py


def run(namespace):
    """Run every test_* callable in `namespace`, print PASS/FAIL/ERROR per test,
    and return the failure count (usable as a process exit code).

    Non-assertion exceptions are caught and reported as ERROR rather than
    aborting the whole suite.
    """
    tests = [(k, v) for k, v in sorted(namespace.items()) if k.startswith('test_')]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f'  PASS  {name}')
            passed += 1
        except AssertionError as e:
            print(f'  FAIL  {name}: {e}')
            failed += 1
        except Exception as e:
            print(f'  ERROR {name}: {type(e).__name__}: {e}')
            failed += 1
    print(f'\n{passed} passed, {failed} failed')
    return failed
