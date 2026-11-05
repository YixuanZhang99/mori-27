"""Registered Git artifact executor configuration; no generation or accounting."""
from core.composition.contracts import json_copy
from core.composition.git_artifacts import GitArtifactBackend
from core.composition.command_domain import CommandDomain
from core.composition.worktree import WorktreeCommandExecutor


class GitArtifactExecutor:
    def __init__(self, options):
        self.options = json_copy(options)

    def construction_backend(self, root, store):
        return GitArtifactBackend(root, store, **{k: v for k, v in self.options.items()
            if k not in {"sandbox", "resource_limits"}})

    def evaluation_executor(self, backend, store, domain):
        if not isinstance(domain, CommandDomain):
            return None
        executor = WorktreeCommandExecutor(backend.repo, backend.root / "evaluation-worktrees", store,
            base_ref=backend.base_commit, artifact_path=backend.artifact_path,
            protected_paths=backend.protected_paths, sandbox=self.options.get("sandbox", "bubblewrap"),
            resource_limits=self.options.get("resource_limits"))
        executor.validate_domain(domain)
        return executor

    async def execute(self, proposal, request, domain):
        raise RuntimeError('Git artifact evaluation requires the materialization protocol')


def register_git_construction(registry):
    def validate(options):
        if type(options) is not dict or set(options) - {
                'base_repo', 'base_ref', 'artifact_path', 'protected_paths', 'sandbox', 'resource_limits'}:
            raise ValueError('invalid Git artifact configuration')
    def factory(context, options):
        if context.execution is None:
            raise ValueError('Git artifact construction requires assembly schema 2')
        return GitArtifactExecutor(options)
    registry.register('executor', 'git_artifact', factory, validate_options=validate)
