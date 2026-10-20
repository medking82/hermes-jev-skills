Integrates the latest `kerpopule/hermes-jev-skills:main` while retaining the Codex
adapter, single Jev skill and explicit model/tool/scope policies.

The offline toolkit, Codex and dashboard tests and the release checks passed before
this integration branch was published. Review upstream behavior and privacy changes
before merging. Local runtime installation and hook trust remain separate steps;
this PR enables no new provider, model, worker, browser or image route.
