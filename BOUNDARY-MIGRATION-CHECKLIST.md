# V6 Boundary Migration Checklist

- [x] Public ownership/provenance markers added.
- [x] Proprietary-license notice added.
- [x] Security policy and basic credential guard added.
- [x] Dedicated protection branch created.
- [x] Protected runtime contract defined.
- [x] Public adapter fails closed when protected runtime is absent.
- [ ] Move V6 proprietary execution into a private/server-side runtime.
- [ ] Configure `MATCH_SIGNAL_PROTECTED_ENGINE_URL` as a protected deployment secret.
- [ ] Keep SportyBet/provider credentials out of the public repo and browser.
- [ ] Run shadow outputs against the frozen V6 baseline.
- [ ] Validate winner + total-games market parity and exact SportyBet line matching.
- [ ] Validate Odds Builder qualification / NO BET behavior.
- [ ] Switch public pages from direct execution to the protected boundary.
- [ ] Make the GitHub repository private after the migration is verified.
- [ ] Re-run production smoke tests and provenance checks.

## Important

Until the unchecked items are completed, the repository should be treated as publicly inspectable. This branch is preparation, not a claim that the proprietary engine is already private.
