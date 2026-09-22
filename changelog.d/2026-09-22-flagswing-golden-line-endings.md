### `flagswing`: the parity guard hashed the working tree, not the blob (2026-09-22)

`make_golden.py` hashed `flag_swing.py` as it sits on disk, so a Windows
checkout with `autocrlf` produced a hash the Linux CI could never reproduce:
the guard failed twice in one day for a line ending, both times with all 546 p
values identical. It now normalises CRLF to LF before hashing — a no-op on an
LF checkout, so both sides agree — and `golden.json` is regenerated against
`main`'s `flag_swing.py` (hash only; no p value moved).
