# Package identity observations

Build and verify a complete package with `scripts/skill_package.py`. The generated
manifest binds paths and hashes to the declared version. `runtime_identity(package_root=...)`
reports loaded module paths and the import-time manifest digest. `context_doctor.py`
checks package shape and performs isolated ledger smoke observations.

`checked_resume` returns identity diagnostics alongside any readable ledger brief.
Missing/mismatched binding or package identity is visible in `diagnostic`; it does not
suppress readable ledger context or control agent actions. Missing/corrupt storage may
leave context null, with its error recorded. Binding initialization remains available
for explicit package/workspace observations; it is not a dispatch prerequisite.
