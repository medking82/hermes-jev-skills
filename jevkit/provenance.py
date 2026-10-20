"""Read-only installed/check-out/published provenance. No install or network side effects."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import time

SHA=re.compile(r'^[0-9a-f]{40}$')

def _git(repo, *args):
    return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.PIPE,timeout=30)

def _installed_path(home, name):
    if name.startswith('jevkit/'):
        return home/'plugins/hermes-jev'/name
    if name.startswith('hermes/plugin/'):
        return home/'plugins'/name[len('hermes/plugin/'):]
    if name.startswith('skills/'):
        return home/'skills/jev'/name[len('skills/'):]
    return None

def inventory(repo, revision):
    """Hash tracked managed files at an exact commit without extracting/executing them."""
    if not isinstance(revision,str) or not SHA.fullmatch(revision):
        raise ValueError('Expected an exact lowercase Git SHA-1')
    data=_git(repo,'archive',revision)
    if len(data)>64*1024*1024:
        raise ValueError('Source archive exceeds bounded read size')
    result={}
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as archive:
        for item in archive:
            if not item.isfile() or _installed_path(Path('.'),item.name) is None:
                continue
            if item.size>2*1024*1024 or '..' in Path(item.name).parts:
                raise ValueError('Invalid managed source file')
            handle=archive.extractfile(item)
            if handle is None:
                raise ValueError('Missing managed source bytes')
            result[item.name]=hashlib.sha256(handle.read()).hexdigest()
    if not result:
        raise ValueError('No managed files in source revision')
    return result

def check_install(repo, home, main_sha, *, shared_homes=()):
    if not isinstance(main_sha,str) or not SHA.fullmatch(main_sha):
        raise ValueError('Expected an exact lowercase Git SHA-1')
    repo=Path(repo).resolve(); home=Path(home).resolve()
    shared_homes=tuple(Path(p).resolve() for p in shared_homes)
    head=_git(repo,'rev-parse','HEAD').decode().strip()
    current=inventory(repo,head); published=inventory(repo,main_sha)
    actual={}
    for name in current.keys() | published.keys():
        path=_installed_path(home,name)
        if path is None: raise ValueError('Unmapped managed source file')
        try:
            # Do not follow a foreign managed-file symlink into unrelated/private material.
            allowed={path.absolute(),(repo/name).resolve()}
            for shared in shared_homes:
                candidate=_installed_path(shared,name)
                if candidate is not None and (candidate.resolve()==candidate.absolute()
                        or candidate.resolve()==(repo/name).resolve()):
                    allowed.add(candidate.resolve())
            if path.resolve() not in allowed:
                actual[name]=None
                continue
            if path.stat().st_size>2*1024*1024:
                raise ValueError('Installed managed file too large')
            actual[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            actual[name]=None
    dirty=bool(_git(repo,'status','--porcelain','--untracked-files=no').strip())
    same=all(actual[name]==digest for name,digest in current.items())
    same_main=all(actual[name]==digest for name,digest in published.items())
    return dict(schema='jev.install_provenance_v1',checked_at=time.time(),
                main_sha=main_sha,checkout_sha=head,checkout_dirty=dirty,
                checkout_at_main=head==main_sha,installed_matches_checkout=same,
                installed_matches_main=same_main,matches_main=head==main_sha and not dirty and same_main,
                managed_files=len(current),missing_files=sum(x is None for x in actual.values()),
                installed_fingerprint=hashlib.sha256(json.dumps(actual,sort_keys=True).encode()).hexdigest(),
                loaded_runtime='unverified',scope='Expected tracked managed code and Jev skills, not running processes or foreign files')

def external_skill(path):
    """Fingerprint declared local dependencies, never their assets or foreign symlinks."""
    root=Path(path).resolve()
    if not (root/'SKILL.md').is_file():
        return {'status':'missing','files':0,'source_sha':None}
    if not (root/'SKILL.md').resolve().is_relative_to(root):
        return {'status':'unverified_foreign_entrypoint','files':0,'source_sha':None}
    files={};foreign=0;seen=0
    for pattern in ('SKILL.md','references/*.md','scripts/*.py','scripts/tests/*.py'):
        for item in root.glob(pattern):
            seen+=1
            if seen>256:raise ValueError('Dependency inventory exceeds bounded file count')
            if not item.resolve().is_relative_to(root):
                foreign+=1;continue
            if not item.is_file():continue
            if item.stat().st_size>2*1024*1024:raise ValueError('Dependency source file too large')
            files[item.relative_to(root).as_posix()]=hashlib.sha256(item.read_bytes()).hexdigest()
    revision=None;dirty=None
    try:
        revision=_git(root,'rev-parse','HEAD').decode().strip()
        if not SHA.fullmatch(revision):revision=None
        dirty=bool(_git(root,'status','--porcelain','--untracked-files=normal','--','.').strip())
    except (OSError,ValueError,subprocess.SubprocessError):
        pass
    return dict(status='files_verified',files=len(files),foreign_links=foreign,source_sha=revision,
                source_dirty=dirty,fingerprint=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),
                scope='SKILL.md, references/*.md, scripts/*.py, scripts/tests/*.py; no assets')


def describe(report):
    if not isinstance(report,dict):
        return 'installed provenance unavailable; runtime unverified'
    def short(key):
        value=report.get(key)
        return value[:7] if isinstance(value,str) and SHA.fullmatch(value) else 'unknown'
    if report.get('matches_main') is True:
        status='matches main '+short('main_sha')
    elif report.get('installed_matches_checkout') is True:
        status='matches checkout '+short('checkout_sha')+', not verified as published main '+short('main_sha')
    else:
        status='differs from checkout '+short('checkout_sha')+'; published main '+short('main_sha')
    if report.get('checkout_dirty') is True:
        status+='; checkout has tracked edits'
    return status+'; loaded runtime unverified'
