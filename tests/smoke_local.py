import os, pathlib, shutil, subprocess, tempfile
source = pathlib.Path(__file__).resolve().parents[1]
base = pathlib.Path(tempfile.mkdtemp(prefix='project-os-e2e-'))
kit, project, home = base/'kit', base/'project', base/'home'
kit.mkdir(); project.mkdir(); home.mkdir()
files = subprocess.run(['git', '-C', str(source), 'ls-files', '-z'], check=True, stdout=subprocess.PIPE).stdout.decode().split('\0')
files += ['install.sh', 'tools/project_local.py', 'tests/test_install.py', 'tests/test_project_local.py', 'tests/smoke_local.py']
for rel in set(files):
    if not rel: continue
    # The fixture needs the kit only; never copy arbitrary repository files.
    parts = pathlib.PurePosixPath(rel).parts
    allowed = rel in {'AGENTS.md', 'PROJECT_OS.md', 'README.md', '.gitignore', 'install.sh'}
    allowed |= len(parts) >= 2 and parts[0] in {'docs', 'workflows', 'skills', 'templates', 'adapters'} and rel.endswith('.md')
    allowed |= len(parts) == 2 and parts[0] in {'tools', 'tests'} and rel.endswith('.py')
    allowed |= len(parts) == 3 and parts[:2] == ('.github', 'workflows') and rel.endswith('.yml')
    if not allowed: continue
    original = source/rel
    if not original.is_file(): continue
    dest = kit/rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, dest)
def run(label, argv, cwd=None, env=None):
    p = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True)
    print(label, 'exit=', p.returncode)
    if p.returncode: print((p.stderr or p.stdout)[-1200:])
    if p.returncode: raise SystemExit(p.returncode)
    return p.stdout.strip()
def git(root,*args):
    return run('git '+args[0], ['git','-C',str(root),*args])
git(kit,'init','-q')
git(kit,'add','.')
git(kit,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture kit')
sha=git(kit,'rev-parse','HEAD')
canonical_sha=git(source,'rev-parse','HEAD')
git(kit,'fetch','--no-tags',str(source),canonical_sha)
git(project,'init','-q')
(project/'AGENTS.md').write_text('Instrucciones v2 antiguas.\nRegla técnica: ejecutar pruebas locales.\n')
(project/'.env').write_text('SYNTHETIC=PRIVATE_TEST_VALUE_DO_NOT_PUBLISH\n')
env=dict(os.environ, HOME=str(home), PROJECT_OS_BIN_DIR=str(home/'bin'), PIP_DISABLE_PIP_VERSION_CHECK='1')
run('install real', [str(kit/'install.sh')], cwd=base, env=env)
launch=home/'bin/project-os-v3'
run('launcher desde /', [str(launch),'--help'],cwd='/',env=env)
run('configurar', [str(launch),'--project',str(project),'--configure','--repo','example/e2e'],cwd='/',env=env)
git(project,'check-ignore','.project-os/config.json')
run('generar adopción',[str(launch),'--project',str(project),'--adopt','--target-version',canonical_sha],cwd='/',env=env)
adopt=next((project/'.project-os/prompts').glob('*.md'))
assert canonical_sha in adopt.read_text() and 'No copies el kit' in adopt.read_text()
assert 'SHA confirmado en el repositorio canónico' in adopt.read_text()
# Simulate the agent's versioned edits locally; this is not an independent agent run.
(project/'AGENTS.md').write_text('codefusion-repo/project-os-v3\nProject-OS-Version: '+canonical_sha+'\nLeer PROJECT_OS.md del commit fijado.\nRegla técnica: ejecutar pruebas locales.\n')
(project/'.gitignore').write_text('.project-os/\n.env\n')
git(project,'add','AGENTS.md','.gitignore')
git(project,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Adopt fixture')
project_sha=git(project,'rev-parse','HEAD')
run('generar trabajo',[str(launch),'--project',str(project),'--workflow','implement','--skill','testing','--objective','Ejecutar una tarea controlada'],cwd='/',env=env)
prompt=next((project/'.project-os/prompts').glob('*.md'))
text=prompt.read_text()
assert canonical_sha in text and 'PRIVATE_TEST_VALUE_DO_NOT_PUBLISH' not in text
assert not (project/'workflows').exists()
assert git(project,'status','--porcelain','--untracked-files=all') == ''
print('fixture=',base)
print('sha_kit_fixture=',sha)
print('sha_canonico_verificado=',canonical_sha)
print('sha_proyecto_local=',project_sha)
print('prompt_actual=',prompt)
print('etapas_pendientes=agente independiente, PR/checks/comentario del fixture y cold start remoto')
